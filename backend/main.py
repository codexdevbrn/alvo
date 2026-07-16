"""
Backend do Analisador de Monitoria (versão web) — reaproveita o motor
analise_funil.py do app desktop original via FastAPI.
"""

import json
import logging
import os
import re
import sys
import tempfile
import traceback
import unicodedata
from typing import Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

import pandas as pd
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.background import BackgroundTask

import db
from auth import criar_token, exigir_login
from dashboard_summary import formatar_data_arquivo, gerar_summary
from engine import analise_funil as af
from engine.exportadores_pdf_word import exportar_relatorio_pdf
from exportar_excel import (
    CATALOGO_RELATORIOS,
    COLUNAS_MOEDA_POR_ANALISE,
    NOMES_ANALISE,
    exportar_relatorio_excel,
)

# Raiz do projeto, um nível acima de backend/. base_de_dados.xlsx e os
# scripts generalistas de normalização/harmonização (normalizar_base.py,
# harmonizar_descricoes.py) ficam lá.
RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if RAIZ_PROJETO not in sys.path:
    sys.path.insert(0, RAIZ_PROJETO)

from harmonizar_descricoes import ErroHarmonizacao  # noqa: E402
from normalizar_base import ErroNormalizacao, normalizar_pasta_empresa  # noqa: E402

CAMINHO_BASE_PADRAO = os.path.join(RAIZ_PROJETO, "base_de_dados.xlsx")

app = FastAPI(title="Analisador de Monitoria - API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup():
    db.inicializar_banco()


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginRequest(BaseModel):
    usuario: str
    senha: str


@app.post("/api/login")
def login(dados: LoginRequest):
    if not db.verificar_login(dados.usuario, dados.senha):
        raise HTTPException(status_code=401, detail="Usuário ou senha inválidos.")
    return {"token": criar_token(dados.usuario)}


# ---------------------------------------------------------------------------
# Catálogo de relatórios
# ---------------------------------------------------------------------------

@app.get("/api/catalogo")
def obter_catalogo(usuario: str = Depends(exigir_login)):
    return [
        {"categoria": categoria, "itens": [{"chave": chave, "titulo": titulo} for chave, titulo in itens]}
        for categoria, itens in CATALOGO_RELATORIOS
    ]


# ---------------------------------------------------------------------------
# Dois caminhos compartilhados (Dashboard + Analisador)
#
# caminho_fonte_dados  — somente leitura: /{cliente}/BI/{cliente}_MOVIMENTO_* + _PRODUTO
# caminho_trabalho     — escrita: /{cliente}/Base.csv, config.json, harm.xlsx, backups
#
# Chaves legadas (caminho_dados_dashboard / caminho_empresas) ainda são lidas
# como fallback na migração.
# ---------------------------------------------------------------------------

CHAVE_CAMINHO_FONTE_DADOS = "caminho_fonte_dados"
CHAVE_CAMINHO_TRABALHO = "caminho_trabalho"
# Legadas — só leitura de fallback / aliases de rota
CHAVE_CAMINHO_DADOS_DASHBOARD = "caminho_dados_dashboard"
CHAVE_CAMINHO_EMPRESAS = "caminho_empresas"

NOME_PASTA_INVALIDO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CAMINHO_BASE_CLIENTES_PADRAO = os.path.join(RAIZ_PROJETO, "base-clientes")
NOME_ARQUIVO_TAGS_CLIENTES = "clientes_tags.json"


def _normpath(caminho: str) -> str:
    # realpath resolve junctions/symlinks no Windows — abspath sozinho
    # deixaria um "trabalho" que aponta para dentro da fonte passar no assert.
    return os.path.normcase(os.path.realpath(caminho))


def _esta_sob(caminho: str, raiz: str) -> bool:
    """True se `caminho` é a própria `raiz` ou está dentro dela."""
    c = _normpath(caminho)
    r = _normpath(raiz)
    return c == r or c.startswith(r + os.sep)


def _resolver_config_dir(
    chaves: tuple[str, ...], *, usar_padrao_base_clientes: bool = False,
) -> Optional[str]:
    """Primeiro caminho configurado que existe como pasta; senão o valor bruto.

    O fallback `base-clientes/` só é usado quando `usar_padrao_base_clientes=True`
    (pasta fonte). A pasta de trabalho NÃO herda esse padrão — senão fonte e
    trabalho viram a mesma árvore e qualquer escrita poderia atingir a fonte.
    """
    ultimo: Optional[str] = None
    for chave in chaves:
        caminho = db.obter_config_app(chave)
        if caminho:
            ultimo = caminho
            if os.path.isdir(caminho):
                return caminho
    if usar_padrao_base_clientes and os.path.isdir(CAMINHO_BASE_CLIENTES_PADRAO):
        return CAMINHO_BASE_CLIENTES_PADRAO
    return ultimo


def _resolver_caminho_fonte() -> Optional[str]:
    return _resolver_config_dir(
        (CHAVE_CAMINHO_FONTE_DADOS, CHAVE_CAMINHO_DADOS_DASHBOARD),
        usar_padrao_base_clientes=True,
    )


def _resolver_caminho_trabalho() -> Optional[str]:
    return _resolver_config_dir(
        (CHAVE_CAMINHO_TRABALHO, CHAVE_CAMINHO_EMPRESAS),
        usar_padrao_base_clientes=False,
    )


def _exigir_caminho_fonte() -> str:
    caminho = _resolver_caminho_fonte()
    if not caminho or not os.path.isdir(caminho):
        raise HTTPException(
            status_code=400,
            detail="Configure a pasta fonte de dados (BI, somente leitura) antes de continuar.",
        )
    return caminho


def _exigir_caminho_trabalho() -> str:
    caminho = _resolver_caminho_trabalho()
    if not caminho:
        raise HTTPException(
            status_code=400,
            detail="Configure a pasta de trabalho (Base.csv / config.json) antes de continuar.",
        )
    return caminho


def _assert_fonte_diferente_de_trabalho() -> None:
    fonte = _resolver_caminho_fonte()
    trabalho = _resolver_caminho_trabalho()
    if not fonte or not trabalho:
        return
    if _esta_sob(trabalho, fonte) or _esta_sob(fonte, trabalho):
        raise HTTPException(
            status_code=400,
            detail=(
                "Pasta fonte e pasta de trabalho não podem ser a mesma nem uma "
                "dentro da outra. A fonte é somente leitura; configure pastas distintas."
            ),
        )


def _assert_escrita_fora_da_fonte(destino: str) -> None:
    """Recusa qualquer escrita sob o path da fonte (chame ANTES de makedirs/open)."""
    fonte = _resolver_caminho_fonte()
    if not fonte:
        return
    if _esta_sob(destino, fonte):
        raise HTTPException(
            status_code=400,
            detail="Escrita proibida na pasta fonte de dados (somente leitura).",
        )


def _validar_nome_empresa(nome: str) -> str:
    nome = nome.strip()
    if not nome or nome in (".", "..") or NOME_PASTA_INVALIDO.search(nome):
        raise HTTPException(status_code=400, detail="Nome de empresa inválido.")
    return nome


def _listar_empresas_fonte() -> list[str]:
    """Subpastas da fonte que contêm BI/ (somente leitura)."""
    caminho = _resolver_caminho_fonte()
    if not caminho or not os.path.isdir(caminho):
        return []
    return sorted(
        nome
        for nome in os.listdir(caminho)
        if os.path.isdir(os.path.join(caminho, nome))
        and os.path.isdir(os.path.join(caminho, nome, "BI"))
    )


def _pastas_empresa(empresa: str) -> tuple[str, str]:
    """Retorna (pasta_fonte, pasta_trabalho) para a empresa."""
    empresa = _validar_nome_empresa(empresa)
    fonte_root = _exigir_caminho_fonte()
    trabalho_root = _exigir_caminho_trabalho()
    pasta_fonte = os.path.join(fonte_root, empresa)
    pasta_trabalho = os.path.join(trabalho_root, empresa)
    if not os.path.isdir(pasta_fonte):
        raise HTTPException(status_code=404, detail=f"Empresa '{empresa}' não encontrada na pasta fonte.")
    if not os.path.isdir(os.path.join(pasta_fonte, "BI")):
        raise HTTPException(
            status_code=404,
            detail=f"Pasta BI/ não encontrada para a empresa '{empresa}' na fonte.",
        )
    return pasta_fonte, pasta_trabalho


def _pasta_trabalho_empresa(empresa: str) -> str:
    """Pasta de trabalho da empresa (cria se preciso; nunca sob a fonte)."""
    empresa = _validar_nome_empresa(empresa)
    pasta = os.path.join(_exigir_caminho_trabalho(), empresa)
    _assert_escrita_fora_da_fonte(pasta)
    try:
        os.makedirs(pasta, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível criar a pasta de trabalho: {exc}")
    return pasta


def _caminho_tags_clientes(empresa: str) -> str:
    return os.path.join(_pasta_trabalho_empresa(empresa), NOME_ARQUIVO_TAGS_CLIENTES)


def _normalizar_mapa_tags(tags_bruto) -> dict[str, list[str]]:
    if not isinstance(tags_bruto, dict):
        return {}
    saida: dict[str, list[str]] = {}
    for nome, lista in tags_bruto.items():
        cliente = str(nome).strip()
        if not cliente:
            continue
        if not isinstance(lista, list):
            continue
        limpas = []
        for tag in lista:
            t = str(tag).strip().lower()
            if t in af.TAGS_CLIENTE_VALIDAS and t not in limpas:
                limpas.append(t)
        if limpas:
            saida[cliente] = limpas
    return saida


def _sincronizar_lista_balcao(tags: dict[str, list[str]]) -> list[str]:
    return sorted(
        nome for nome, lista in tags.items()
        if af.TAG_CLIENTE_BALCAO in lista
    )


def _ler_tags_clientes(empresa: str) -> dict:
    caminho = os.path.join(_exigir_caminho_trabalho(), _validar_nome_empresa(empresa), NOME_ARQUIVO_TAGS_CLIENTES)
    if not os.path.isfile(caminho):
        return {"tags": {}, "clientes_balcao": []}
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            bruto = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        return {"tags": {}, "clientes_balcao": []}
    tags = _normalizar_mapa_tags(bruto.get("tags") if isinstance(bruto, dict) else {})
    return {"tags": tags, "clientes_balcao": _sincronizar_lista_balcao(tags)}


def _gravar_tags_clientes(empresa: str, tags: dict[str, list[str]]) -> dict:
    tags_norm = _normalizar_mapa_tags(tags)
    balcao = _sincronizar_lista_balcao(tags_norm)
    payload = {"tags": tags_norm, "clientes_balcao": balcao}
    caminho = _caminho_tags_clientes(empresa)
    _assert_escrita_fora_da_fonte(caminho)
    try:
        with open(caminho, "w", encoding="utf-8") as arquivo:
            json.dump(payload, arquivo, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível gravar {NOME_ARQUIVO_TAGS_CLIENTES}: {exc}")
    return {**payload, "caminho": caminho}


def _clientes_balcao_extra(empresa: Optional[str]) -> list[str]:
    if not empresa or not str(empresa).strip():
        return []
    try:
        return list(_ler_tags_clientes(empresa.strip())["clientes_balcao"])
    except HTTPException:
        return []


# Cache por empresa do Base.csv no trabalho (mtime -> df).
_cache_base_empresa: dict[str, dict] = {}

# Cache do Excel padrão (sem empresa selecionada).
_cache_base: dict = {"mtime": None, "df": None, "linhas_vazias": 0}

# Cache do summary do dashboard por empresa.
_cache_summary_dashboard: dict[str, dict] = {}


def _arquivos_origem_mais_recentes(
    pasta_fonte: str, pasta_trabalho: str, mtime_base_csv: Optional[float],
) -> bool:
    """True se BI/ na fonte (ou harm.xlsx no trabalho) for mais novo que o Base.csv."""
    pasta_bi = os.path.join(pasta_fonte, "BI")
    candidatos: list[str] = []
    if os.path.isdir(pasta_bi):
        candidatos.extend(os.path.join(pasta_bi, nome) for nome in os.listdir(pasta_bi))
    for nome_harm in ("harm.xlsx", "harm.xls"):
        caminho_harm = os.path.join(pasta_trabalho, nome_harm)
        if os.path.exists(caminho_harm):
            candidatos.append(caminho_harm)

    if mtime_base_csv is None:
        return bool(candidatos) or os.path.isdir(pasta_bi)
    return any(os.path.getmtime(c) > mtime_base_csv for c in candidatos if os.path.isfile(c))


def _ensure_base_csv(pasta_fonte: str, pasta_trabalho: str, empresa: str) -> str:
    """Garante Base.csv no trabalho, regenerando a partir do BI da fonte se preciso.

    Nunca escreve sob pasta_fonte. Recusa se fonte == trabalho.
    """
    _assert_fonte_diferente_de_trabalho()
    _assert_escrita_fora_da_fonte(pasta_trabalho)
    caminho_csv = os.path.join(pasta_trabalho, "Base.csv")
    _assert_escrita_fora_da_fonte(caminho_csv)

    try:
        os.makedirs(pasta_trabalho, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Não foi possível criar a pasta de trabalho da empresa: {exc}",
        )

    mtime_atual = os.path.getmtime(caminho_csv) if os.path.exists(caminho_csv) else None

    if mtime_atual is not None and not _arquivos_origem_mais_recentes(
        pasta_fonte, pasta_trabalho, mtime_atual,
    ):
        return caminho_csv

    if mtime_atual is None:
        logger.info("Base.csv ausente para %s — normalizando BI da fonte -> trabalho.", empresa)
    else:
        logger.info("Origem mais recente para %s — renormalizando no trabalho.", empresa)

    try:
        normalizar_pasta_empresa(pasta_fonte, pasta_trabalho=pasta_trabalho)
    except ErroNormalizacao as exc:
        if mtime_atual is not None:
            logger.warning("Falha ao renormalizar %s, mantendo Base.csv existente: %s", empresa, exc)
            return caminho_csv
        raise HTTPException(status_code=400, detail=str(exc))
    except ErroHarmonizacao as exc:
        raise HTTPException(status_code=400, detail=f"Falha ao harmonizar descrições: {exc}")
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Falha inesperada ao normalizar a empresa %s:\n%s", empresa, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao normalizar a base: {exc}")

    _cache_summary_dashboard.pop(empresa, None)
    _cache_base_empresa.pop(empresa, None)
    return caminho_csv


def _carregar_base_padrao() -> tuple[pd.DataFrame, int]:
    if not os.path.exists(CAMINHO_BASE_PADRAO):
        raise HTTPException(
            status_code=400,
            detail=f"base_de_dados.xlsx não encontrado em {CAMINHO_BASE_PADRAO}.",
        )

    mtime = os.path.getmtime(CAMINHO_BASE_PADRAO)
    if _cache_base["mtime"] != mtime:
        try:
            df, linhas_vazias = af.carregar_excel_base(CAMINHO_BASE_PADRAO)
        except af.ErroCarregamentoCSV as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        except Exception as exc:
            logger.error("Falha inesperada ao carregar a base padrão:\n%s", traceback.format_exc())
            raise HTTPException(status_code=400, detail=f"Falha inesperada ao carregar a base: {exc}")
        _cache_base.update(mtime=mtime, df=df, linhas_vazias=linhas_vazias)

    return _cache_base["df"], _cache_base["linhas_vazias"]


def _carregar_base_empresa(empresa: str) -> tuple[pd.DataFrame, int]:
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    caminho_csv = _ensure_base_csv(pasta_fonte, pasta_trabalho, empresa)
    mtime = os.path.getmtime(caminho_csv)
    em_cache = _cache_base_empresa.get(empresa)
    if em_cache and em_cache["mtime"] == mtime:
        return em_cache["df"], em_cache["linhas_vazias"]

    try:
        df, linhas_vazias = af.carregar_csv(caminho_csv)
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao carregar Base.csv de %s:\n%s", empresa, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao carregar a base: {exc}")

    _cache_base_empresa[empresa] = {"mtime": mtime, "df": df, "linhas_vazias": linhas_vazias}
    return df, linhas_vazias


def _carregar_base(empresa: Optional[str] = None) -> tuple[pd.DataFrame, int]:
    """Com empresa: Base.csv do trabalho (após ensure). Sem empresa: Excel padrão da raiz."""
    if empresa and empresa.strip():
        return _carregar_base_empresa(empresa.strip())
    return _carregar_base_padrao()


@app.get("/api/base")
def obter_base(empresa: Optional[str] = None, usuario: str = Depends(exigir_login)):
    df, linhas_vazias = _carregar_base(empresa)

    qtd_nao_harmonizados = af.contar_produtos_nao_harmonizados(df)

    return {
        "linhas": len(df),
        "linhas_ignoradas": linhas_vazias,
        "qtd_nao_harmonizados": qtd_nao_harmonizados,
        "granularidades": af.GRANULARIDADES,
        "empresa": empresa.strip() if empresa and empresa.strip() else None,
    }


# ---------------------------------------------------------------------------
# Prévia de grupos de clientes (segmentação por % de receita acumulada)
# ---------------------------------------------------------------------------

class ParametrosGrupos(BaseModel):
    clientes_excluidos: list[str] = []
    cortes_clientes: tuple[float, float, float] = (30.0, 50.0, 60.0)
    desconsiderar_balcao: bool = False
    empresa: Optional[str] = None
    max_itens_por_grupo: int = 20
    # True = recalcula cortes como "sugerir"; False = usa os cortes informados (ex.: config.json).
    ajustar_cortes: bool = True


def _contagens_para_grupos(cortes: list[float], contagens: list[int]) -> list[dict]:
    grupos = [
        {"nome": f"Grupo {i + 1}", "ate_percentual": corte, "quantidade": contagem}
        for i, (corte, contagem) in enumerate(zip(cortes, contagens[:-1]))
    ]
    grupos.append({"nome": "Demais", "ate_percentual": None, "quantidade": contagens[-1]})
    return grupos


def _contagens_de_classificado(classificado: pd.DataFrame, cortes: list[float]) -> list[int]:
    """Contagens Grupo 1..N + Demais a partir do DataFrame já classificado (sem 2º pass)."""
    contagens = []
    for i in range(len(cortes)):
        contagens.append(int((classificado["Faixa"] == f"Grupo {i + 1}").sum()))
    contagens.append(int((classificado["Faixa"] == "Demais").sum()))
    return contagens


def _float_ou_none(valor) -> Optional[float]:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    return float(valor)


def _eh_produto_nao_harmonizado(nome: str) -> bool:
    """Espelha o critério do frontend (texto normalizado contém 'harmonizad')."""
    normalizado = unicodedata.normalize("NFD", str(nome))
    sem_acento = "".join(c for c in normalizado if unicodedata.category(c) != "Mn")
    return "harmonizad" in sem_acento.lower()


# Após sugerir cortes, grupos 1..N já cabem no max; Demais pode ser enorme.
MAX_ITENS_DEMAIS_PREVIA = 300


def _rede_seguranca_demais(frame: pd.DataFrame, max_demais: int = MAX_ITENS_DEMAIS_PREVIA) -> pd.DataFrame:
    """Mantém grupos inteiros; limita só a faixa Demais (já ordenada por receita)."""
    if frame.empty or max_demais <= 0:
        return frame
    partes = []
    for faixa, parte in frame.groupby("Faixa", sort=False):
        partes.append(parte.head(max_demais) if faixa == "Demais" else parte)
    return pd.concat(partes, ignore_index=True) if partes else frame.iloc[0:0]


def _itens_clientes_previa(classificado: pd.DataFrame) -> list[dict]:
    """Serializa a prévia. Clientes Faixa=Balcão entram na lista (visíveis, fora dos
    cortes ABC); o frontend marca a checkbox como desmarcada quando
    desconsiderar_balcao está ativo."""
    if classificado.empty:
        return []
    frame = classificado[["Cliente", "Receita", "Percentual_Individual", "Percentual_Acumulado", "Faixa"]].copy()
    if frame.empty:
        return []
    frame = frame.sort_values("Receita", ascending=False)
    frame = _rede_seguranca_demais(frame)
    # Lista de dicts (não Series float) para None não voltar a virar NaN no JSON.
    percentual_receita = [
        _float_ou_none(v) for v in frame["Percentual_Individual"].tolist()
    ]
    percentual_acumulado = [
        _float_ou_none(v) for v in frame["Percentual_Acumulado"].tolist()
    ]
    receita = pd.to_numeric(frame["Receita"], errors="coerce").fillna(0.0).tolist()
    return [
        {
            "cliente": str(cliente),
            "receita": float(rec),
            "percentual_receita": pct_rec,
            "percentual_acumulado": pct_acum,
            "grupo": str(grupo),
        }
        for cliente, rec, pct_rec, pct_acum, grupo in zip(
            frame["Cliente"].tolist(),
            receita,
            percentual_receita,
            percentual_acumulado,
            frame["Faixa"].tolist(),
        )
    ]


def _itens_produtos_previa(classificado: pd.DataFrame) -> list[dict]:
    if classificado.empty:
        return []
    frame = classificado[["descricao", "Receita", "Faixa", "Freq_Simples", "Freq_Acumulado"]].copy()
    frame = frame.sort_values("Receita", ascending=False)
    frame = _rede_seguranca_demais(frame)
    receita = pd.to_numeric(frame["Receita"], errors="coerce").fillna(0.0).tolist()
    return [
        {
            "produto": str(produto),
            "receita": float(rec),
            "grupo": str(grupo),
            "percentual_receita": _float_ou_none(pct_rec),
            "percentual_acumulado": _float_ou_none(pct_acum),
        }
        for produto, rec, grupo, pct_rec, pct_acum in zip(
            frame["descricao"].tolist(),
            receita,
            frame["Faixa"].tolist(),
            frame["Freq_Simples"].tolist(),
            frame["Freq_Acumulado"].tolist(),
        )
    ]


def _previa_grupos_resposta(
    df: pd.DataFrame,
    clientes_excluidos: list[str],
    cortes_iniciais,
    max_por_grupo: int,
    desconsiderar_balcao: bool,
    ajustar_cortes: bool = True,
    clientes_balcao_extra: Optional[List[str]] = None,
) -> dict:
    if ajustar_cortes:
        cortes, _ = af.sugerir_cortes_grupos(
            df, clientes_excluidos, cortes_iniciais,
            max_por_grupo=max_por_grupo, desconsiderar_balcao=desconsiderar_balcao,
            clientes_balcao_extra=clientes_balcao_extra,
        )
    else:
        cortes = list(cortes_iniciais)
    classificado = af.classificar_clientes_agregado(
        df, clientes_excluidos, cortes,
        desconsiderar_balcao=desconsiderar_balcao,
        clientes_balcao_extra=clientes_balcao_extra,
    )
    contagens = _contagens_de_classificado(classificado, cortes)
    return {
        "cortes_clientes": cortes,
        "grupos": _contagens_para_grupos(cortes, contagens),
        "itens": _itens_clientes_previa(classificado),
    }


@app.post("/api/grupos/previa")
def previa_grupos(parametros: ParametrosGrupos, usuario: str = Depends(exigir_login)):
    """Prévia de grupos; por padrão recalcula cortes para caber em max_itens_por_grupo."""
    df, _ = _carregar_base(parametros.empresa)
    return _previa_grupos_resposta(
        df,
        parametros.clientes_excluidos,
        parametros.cortes_clientes,
        parametros.max_itens_por_grupo,
        parametros.desconsiderar_balcao,
        ajustar_cortes=parametros.ajustar_cortes,
        clientes_balcao_extra=_clientes_balcao_extra(parametros.empresa),
    )


class ParametrosSugerirCortes(ParametrosGrupos):
    max_por_grupo: int = 20


@app.post("/api/grupos/sugerir-cortes")
def sugerir_cortes(parametros: ParametrosSugerirCortes, usuario: str = Depends(exigir_login)):
    df, _ = _carregar_base(parametros.empresa)
    return _previa_grupos_resposta(
        df,
        parametros.clientes_excluidos,
        parametros.cortes_clientes,
        parametros.max_por_grupo,
        parametros.desconsiderar_balcao,
        ajustar_cortes=True,
        clientes_balcao_extra=_clientes_balcao_extra(parametros.empresa),
    )


# ---------------------------------------------------------------------------
# Prévia de produtos (alto giro x demais, pelo corte de produtos por receita)
# ---------------------------------------------------------------------------

class ParametrosProdutos(BaseModel):
    produtos_excluidos: list[str] = []
    corte_produtos: float = 80.0
    empresa: Optional[str] = None
    max_itens_por_grupo: int = 20
    ajustar_cortes: bool = True


@app.post("/api/produtos/previa")
def previa_produtos(parametros: ParametrosProdutos, usuario: str = Depends(exigir_login)):
    df, _ = _carregar_base(parametros.empresa)
    # Classifica todos os produtos (sem filtrar excluídos) para a tabela de
    # prévia poder marcar/desmarcar "Considerar?" como no app desktop.
    if parametros.ajustar_cortes:
        corte, _ = af.sugerir_corte_produtos(
            df, parametros.corte_produtos, max_por_grupo=parametros.max_itens_por_grupo,
        )
    else:
        corte = float(parametros.corte_produtos)
    classificado = af.classificar_produtos_agregado(df, corte)
    contagens = classificado["Faixa"].value_counts()
    demais = classificado.loc[classificado["Faixa"] == "Demais", "descricao"].astype(str)
    return {
        "corte_produtos": corte,
        "grupos": [
            {"nome": "Grupo 1 (alto giro)", "ate_percentual": corte,
             "quantidade": int(contagens.get("Grupo 1", 0))},
            {"nome": "Demais", "ate_percentual": None, "quantidade": int(contagens.get("Demais", 0))},
        ],
        "itens": _itens_produtos_previa(classificado),
        # Listas completas (sem teto da prévia) para toggles de exclusão em massa.
        "produtos_demais": demais.tolist(),
        "produtos_nao_harmonizados": [
            nome for nome in classificado["descricao"].astype(str).tolist()
            if _eh_produto_nao_harmonizado(nome)
        ],
    }


# ---------------------------------------------------------------------------
# Rotas de caminhos (fonte RO + trabalho RW) e config.json por empresa
# ---------------------------------------------------------------------------

class CaminhoPasta(BaseModel):
    caminho: str


def _salvar_caminho_fonte(caminho: str) -> str:
    caminho = caminho.strip()
    if not caminho:
        raise HTTPException(status_code=400, detail="Informe um caminho de pasta.")
    if not os.path.isdir(caminho):
        raise HTTPException(
            status_code=400,
            detail=(
                "A pasta fonte deve existir e ser acessível (somente leitura — "
                "o app não cria pastas sob a fonte)."
            ),
        )
    trabalho = _resolver_caminho_trabalho()
    if trabalho and (_esta_sob(trabalho, caminho) or _esta_sob(caminho, trabalho)):
        raise HTTPException(
            status_code=400,
            detail=(
                "Pasta fonte e pasta de trabalho não podem ser a mesma nem uma "
                "dentro da outra."
            ),
        )
    db.definir_config_app(CHAVE_CAMINHO_FONTE_DADOS, caminho)
    return caminho


def _salvar_caminho_trabalho(caminho: str) -> str:
    caminho = caminho.strip()
    if not caminho:
        raise HTTPException(status_code=400, detail="Informe um caminho de pasta.")
    # Assert ANTES de qualquer makedirs — senão criar trabalho sob a fonte
    # já altera a árvore da fonte antes do 400.
    _assert_escrita_fora_da_fonte(caminho)
    fonte = _resolver_caminho_fonte()
    if fonte and (_esta_sob(caminho, fonte) or _esta_sob(fonte, caminho)):
        raise HTTPException(
            status_code=400,
            detail=(
                "Pasta fonte e pasta de trabalho não podem ser a mesma nem uma "
                "dentro da outra."
            ),
        )
    try:
        os.makedirs(caminho, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível criar/acessar essa pasta: {exc}")
    db.definir_config_app(CHAVE_CAMINHO_TRABALHO, caminho)
    return caminho


@app.get("/api/config/caminho-fonte-dados")
def obter_caminho_fonte_dados(usuario: str = Depends(exigir_login)):
    return {"caminho": _resolver_caminho_fonte()}


@app.post("/api/config/caminho-fonte-dados")
def definir_caminho_fonte_dados(corpo: CaminhoPasta, usuario: str = Depends(exigir_login)):
    return {"caminho": _salvar_caminho_fonte(corpo.caminho)}


@app.get("/api/config/caminho-trabalho")
def obter_caminho_trabalho(usuario: str = Depends(exigir_login)):
    return {"caminho": _resolver_caminho_trabalho()}


@app.post("/api/config/caminho-trabalho")
def definir_caminho_trabalho(corpo: CaminhoPasta, usuario: str = Depends(exigir_login)):
    return {"caminho": _salvar_caminho_trabalho(corpo.caminho)}


# Aliases legados do Analisador (caminho-empresas -> trabalho)
@app.get("/api/config/caminho-empresas")
def obter_caminho_empresas(usuario: str = Depends(exigir_login)):
    return {"caminho": _resolver_caminho_trabalho()}


@app.post("/api/config/caminho-empresas")
def definir_caminho_empresas(corpo: CaminhoPasta, usuario: str = Depends(exigir_login)):
    return {"caminho": _salvar_caminho_trabalho(corpo.caminho)}


@app.get("/api/empresas")
def listar_empresas(usuario: str = Depends(exigir_login)):
    return _listar_empresas_fonte()


class ConfiguracaoEmpresa(BaseModel):
    dados: dict


@app.post("/api/empresas/{nome}/configuracao")
def salvar_configuracao_empresa(nome: str, corpo: ConfiguracaoEmpresa, usuario: str = Depends(exigir_login)):
    nome = _validar_nome_empresa(nome)
    trabalho_root = _exigir_caminho_trabalho()
    pasta_empresa = os.path.join(trabalho_root, nome)
    _assert_escrita_fora_da_fonte(pasta_empresa)
    try:
        os.makedirs(pasta_empresa, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível criar a pasta da empresa: {exc}")
    caminho_arquivo = os.path.join(pasta_empresa, "config.json")
    _assert_escrita_fora_da_fonte(caminho_arquivo)
    try:
        with open(caminho_arquivo, "w", encoding="utf-8") as arquivo:
            json.dump(corpo.dados, arquivo, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível gravar config.json: {exc}")
    return {"ok": True, "caminho": caminho_arquivo}


@app.get("/api/empresas/{nome}/configuracao")
def carregar_configuracao_empresa(nome: str, usuario: str = Depends(exigir_login)):
    nome = _validar_nome_empresa(nome)
    caminho_arquivo = os.path.join(_exigir_caminho_trabalho(), nome, "config.json")
    if not os.path.exists(caminho_arquivo):
        raise HTTPException(status_code=404, detail="Configuração não encontrada para esta empresa.")
    with open(caminho_arquivo, "r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


class TagsClientesBody(BaseModel):
    tags: dict


class TagClienteBody(BaseModel):
    cliente: str
    tags: list[str]


@app.get("/api/empresas/{nome}/clientes-tags")
def obter_tags_clientes(nome: str, usuario: str = Depends(exigir_login)):
    return _ler_tags_clientes(nome)


@app.put("/api/empresas/{nome}/clientes-tags")
def salvar_tags_clientes(nome: str, corpo: TagsClientesBody, usuario: str = Depends(exigir_login)):
    return _gravar_tags_clientes(nome, corpo.tags if isinstance(corpo.tags, dict) else {})


@app.put("/api/empresas/{nome}/clientes-tags/cliente")
def salvar_tags_um_cliente(nome: str, corpo: TagClienteBody, usuario: str = Depends(exigir_login)):
    """Atualiza as tags de um único cliente e sincroniza clientes_balcao."""
    atual = _ler_tags_clientes(nome)
    tags = dict(atual["tags"])
    cliente = corpo.cliente.strip()
    if not cliente:
        raise HTTPException(status_code=400, detail="Informe o nome do cliente.")
    limpas = [
        t for t in (str(x).strip().lower() for x in corpo.tags)
        if t in af.TAGS_CLIENTE_VALIDAS
    ]
    # dedupe preserving order
    vistas = set()
    ordenadas = []
    for t in limpas:
        if t not in vistas:
            vistas.add(t)
            ordenadas.append(t)
    if ordenadas:
        tags[cliente] = ordenadas
    else:
        tags.pop(cliente, None)
    return _gravar_tags_clientes(nome, tags)


@app.post("/api/empresas/{nome}/ensure-base")
def ensure_base_empresa(nome: str, usuario: str = Depends(exigir_login)):
    """Garante Base.csv no trabalho a partir do BI da fonte (Analisador / dash)."""
    pasta_fonte, pasta_trabalho = _pastas_empresa(nome)
    caminho_csv = _ensure_base_csv(pasta_fonte, pasta_trabalho, nome)
    return {"ok": True, "caminho": caminho_csv}


# ---------------------------------------------------------------------------
# Dashboard (público) — mesmos dois caminhos; aliases legados mantidos
# ---------------------------------------------------------------------------

@app.get("/api/dashboard/caminho-fonte-dados")
def obter_caminho_fonte_dashboard():
    return {"caminho": _resolver_caminho_fonte()}


@app.post("/api/dashboard/caminho-fonte-dados")
def definir_caminho_fonte_dashboard(corpo: CaminhoPasta):
    return {"caminho": _salvar_caminho_fonte(corpo.caminho)}


@app.get("/api/dashboard/caminho-trabalho")
def obter_caminho_trabalho_dashboard():
    return {"caminho": _resolver_caminho_trabalho()}


@app.post("/api/dashboard/caminho-trabalho")
def definir_caminho_trabalho_dashboard(corpo: CaminhoPasta):
    return {"caminho": _salvar_caminho_trabalho(corpo.caminho)}


# Alias legado: caminho-dados do dash = fonte (somente leitura)
@app.get("/api/dashboard/caminho-dados")
def obter_caminho_dados_dashboard():
    return {"caminho": _resolver_caminho_fonte()}


@app.post("/api/dashboard/caminho-dados")
def definir_caminho_dados_dashboard(corpo: CaminhoPasta):
    return {"caminho": _salvar_caminho_fonte(corpo.caminho)}


@app.get("/api/dashboard/empresas")
def listar_empresas_dashboard():
    return _listar_empresas_fonte()


@app.get("/api/dashboard/summary/{empresa}")
def obter_summary_dashboard(empresa: str):
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    caminho_csv = _ensure_base_csv(pasta_fonte, pasta_trabalho, empresa)

    mtime = os.path.getmtime(caminho_csv)
    em_cache = _cache_summary_dashboard.get(empresa)
    if em_cache and em_cache["mtime"] == mtime:
        return em_cache["summary"]

    try:
        df, _linhas_vazias = af.carregar_csv(caminho_csv)
        summary = gerar_summary(df, updated_at=formatar_data_arquivo(mtime))
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao gerar summary da empresa %s:\n%s", empresa, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao processar a base: {exc}")

    _cache_summary_dashboard[empresa] = {"mtime": mtime, "summary": summary}
    return summary


# ---------------------------------------------------------------------------
# Parâmetros compartilhados por /analisar e /exportar
# ---------------------------------------------------------------------------

class ParametrosAnalise(BaseModel):
    granularidades: list[str]
    chaves_selecionadas: list[str]
    clientes_excluidos: list[str] = []
    produtos_excluidos: list[str] = []
    cortes_clientes: tuple[float, float, float] = (30.0, 50.0, 60.0)
    corte_produtos: float = 80.0
    periodos_queda_consecutiva: int = 2
    desconsiderar_balcao: bool = False
    excluir_periodo_atual: bool = True
    top_n_produtos: Optional[int] = None
    reducao_minima_erosao: float = 50.0
    queda_minima_alerta_rs: float = 0.0
    queda_minima_erosao_rs: float = 0.0
    reducao_minima_sem_venda: float = 90.0
    top_n_poder_compra: Optional[int] = None
    nome_empresa: str = ""
    nome_usuario: str = ""
    empresa: Optional[str] = None


def _carregar_df_filtrado(produtos_excluidos: list[str], empresa: Optional[str] = None) -> pd.DataFrame:
    df, _ = _carregar_base(empresa)
    if produtos_excluidos:
        df = df[~df["descricao"].isin(produtos_excluidos)]
    return df


def _rodar_analises(parametros: ParametrosAnalise) -> dict:
    empresa = parametros.empresa.strip() if parametros.empresa and parametros.empresa.strip() else None
    df_filtrado = _carregar_df_filtrado(parametros.produtos_excluidos, empresa)
    if df_filtrado.empty:
        raise HTTPException(status_code=400, detail="Nenhuma linha restante após excluir os produtos desmarcados.")

    return af.gerar_analises_completas(
        df_filtrado,
        parametros.granularidades,
        clientes_excluidos=parametros.clientes_excluidos,
        cortes_clientes=parametros.cortes_clientes,
        corte_produtos=parametros.corte_produtos,
        periodos_queda_consecutiva=parametros.periodos_queda_consecutiva,
        chaves_solicitadas=set(parametros.chaves_selecionadas),
        desconsiderar_balcao=parametros.desconsiderar_balcao,
        excluir_periodo_atual=parametros.excluir_periodo_atual,
        top_n_produtos=parametros.top_n_produtos,
        reducao_minima_erosao=parametros.reducao_minima_erosao,
        queda_minima_alerta_rs=parametros.queda_minima_alerta_rs,
        queda_minima_erosao_rs=parametros.queda_minima_erosao_rs,
        reducao_minima_sem_venda=parametros.reducao_minima_sem_venda,
        top_n_poder_compra=parametros.top_n_poder_compra,
        clientes_balcao_extra=_clientes_balcao_extra(empresa),
    )


def _df_para_json(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"colunas": [], "linhas": []}
    df_normalizado = df.reset_index() if df.index.name or isinstance(df.index, pd.MultiIndex) else df
    return {
        "colunas": [str(c) for c in df_normalizado.columns],
        "linhas": df_normalizado.astype(object).where(pd.notnull(df_normalizado), None).values.tolist(),
    }


@app.post("/api/analisar")
def analisar(parametros: ParametrosAnalise, usuario: str = Depends(exigir_login)):
    try:
        resultados = _rodar_analises(parametros)
    except HTTPException:
        raise
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao analisar dados de %s:\n%s", usuario, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao gerar as análises: {exc}")
    return {
        granularidade: {chave: _df_para_json(df_analise) for chave, df_analise in analises.items()}
        for granularidade, analises in resultados.items()
    }


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

@app.post("/api/exportar/{formato}")
def exportar(formato: str, parametros: ParametrosAnalise, usuario: str = Depends(exigir_login)):
    if formato not in ("excel", "pdf"):
        raise HTTPException(status_code=400, detail="Formato inválido. Use 'excel' ou 'pdf'.")

    try:
        resultados = _rodar_analises(parametros)
    except HTTPException:
        raise
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao exportar dados de %s:\n%s", usuario, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao gerar as análises: {exc}")

    extensao = ".xlsx" if formato == "excel" else ".pdf"
    arquivo_temp = tempfile.NamedTemporaryFile(delete=False, suffix=extensao)
    caminho_saida = arquivo_temp.name
    arquivo_temp.close()

    if formato == "excel":
        exportar_relatorio_excel(
            caminho_saida, resultados, nome_usuario=parametros.nome_usuario, nome_empresa=parametros.nome_empresa,
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        nome_arquivo = "relatorio.xlsx"
    else:
        exportar_relatorio_pdf(
            caminho_saida, resultados, NOMES_ANALISE, nome_usuario=parametros.nome_usuario,
            colunas_moeda_por_analise=COLUNAS_MOEDA_POR_ANALISE, nome_empresa=parametros.nome_empresa,
        )
        media_type = "application/pdf"
        nome_arquivo = "relatorio.pdf"

    return FileResponse(
        caminho_saida, media_type=media_type, filename=nome_arquivo,
        background=BackgroundTask(os.remove, caminho_saida),
    )
