"""
Backend do Analisador de Monitoria (versão web) — reaproveita o motor
analise_funil.py do app desktop original via FastAPI.
"""

import json
import logging
import os
import re
import tempfile
import traceback
from typing import Optional

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

# base_de_dados.xlsx fica na raiz do projeto, um nível acima de backend/.
CAMINHO_BASE_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "base_de_dados.xlsx"
)

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
# Base de dados padrão (base_de_dados.xlsx na raiz do projeto)
# ---------------------------------------------------------------------------

# Cache em memória: recarrega do disco só quando o arquivo muda (a base tem
# ~570 mil linhas, recarregar em toda requisição seria lento).
_cache_base: dict = {"mtime": None, "df": None, "linhas_vazias": 0}


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


@app.get("/api/base")
def obter_base(usuario: str = Depends(exigir_login)):
    df, linhas_vazias = _carregar_base_padrao()

    qtd_nao_harmonizados = af.contar_produtos_nao_harmonizados(df)

    return {
        "linhas": len(df),
        "linhas_ignoradas": linhas_vazias,
        "qtd_nao_harmonizados": qtd_nao_harmonizados,
        "granularidades": af.GRANULARIDADES,
    }


# ---------------------------------------------------------------------------
# Prévia de grupos de clientes (segmentação por % de receita acumulada)
# ---------------------------------------------------------------------------

class ParametrosGrupos(BaseModel):
    clientes_excluidos: list[str] = []
    cortes_clientes: tuple[float, float, float] = (30.0, 50.0, 60.0)
    desconsiderar_balcao: bool = False


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


def _itens_clientes_previa(classificado: pd.DataFrame) -> list[dict]:
    if classificado.empty:
        return []
    frame = classificado[["Cliente", "Receita", "Percentual_Individual", "Percentual_Acumulado", "Faixa"]].copy()
    frame.columns = ["cliente", "receita", "percentual_receita", "percentual_acumulado", "grupo"]
    frame["receita"] = frame["receita"].astype(float)
    frame["percentual_receita"] = frame["percentual_receita"].astype(float)
    frame["percentual_acumulado"] = frame["percentual_acumulado"].map(_float_ou_none)
    return frame.to_dict(orient="records")


def _itens_produtos_previa(classificado: pd.DataFrame) -> list[dict]:
    if classificado.empty:
        return []
    frame = classificado[["descricao", "Receita", "Faixa", "Freq_Simples", "Freq_Acumulado"]].copy()
    frame.columns = ["produto", "receita", "grupo", "percentual_receita", "percentual_acumulado"]
    frame["receita"] = frame["receita"].astype(float)
    frame["percentual_receita"] = frame["percentual_receita"].astype(float)
    frame["percentual_acumulado"] = frame["percentual_acumulado"].astype(float)
    return frame.to_dict(orient="records")


@app.post("/api/grupos/previa")
def previa_grupos(parametros: ParametrosGrupos, usuario: str = Depends(exigir_login)):
    df, _ = _carregar_base_padrao()
    classificado = af.classificar_clientes_agregado(
        df, parametros.clientes_excluidos, parametros.cortes_clientes,
        desconsiderar_balcao=parametros.desconsiderar_balcao,
    )
    contagens = _contagens_de_classificado(classificado, list(parametros.cortes_clientes))
    return {
        "grupos": _contagens_para_grupos(list(parametros.cortes_clientes), contagens),
        "itens": _itens_clientes_previa(classificado),
    }


class ParametrosSugerirCortes(ParametrosGrupos):
    max_por_grupo: int = 20


@app.post("/api/grupos/sugerir-cortes")
def sugerir_cortes(parametros: ParametrosSugerirCortes, usuario: str = Depends(exigir_login)):
    df, _ = _carregar_base_padrao()
    cortes_ajustados, _contagens_sugeridas = af.sugerir_cortes_grupos(
        df, parametros.clientes_excluidos, parametros.cortes_clientes,
        max_por_grupo=parametros.max_por_grupo, desconsiderar_balcao=parametros.desconsiderar_balcao,
    )
    classificado = af.classificar_clientes_agregado(
        df, parametros.clientes_excluidos, cortes_ajustados,
        desconsiderar_balcao=parametros.desconsiderar_balcao,
    )
    contagens = _contagens_de_classificado(classificado, cortes_ajustados)
    return {
        "cortes_clientes": cortes_ajustados,
        "grupos": _contagens_para_grupos(cortes_ajustados, contagens),
        "itens": _itens_clientes_previa(classificado),
    }


# ---------------------------------------------------------------------------
# Prévia de produtos (alto giro x demais, pelo corte de produtos por receita)
# ---------------------------------------------------------------------------

class ParametrosProdutos(BaseModel):
    produtos_excluidos: list[str] = []
    corte_produtos: float = 80.0


@app.post("/api/produtos/previa")
def previa_produtos(parametros: ParametrosProdutos, usuario: str = Depends(exigir_login)):
    df, _ = _carregar_base_padrao()
    # Classifica todos os produtos (sem filtrar excluídos) para a tabela de
    # prévia poder marcar/desmarcar "Considerar?" como no app desktop.
    classificado = af.classificar_produtos_agregado(df, parametros.corte_produtos)
    contagens = classificado["Faixa"].value_counts()
    return {
        "grupos": [
            {"nome": "Grupo 1 (alto giro)", "ate_percentual": parametros.corte_produtos,
             "quantidade": int(contagens.get("Grupo 1", 0))},
            {"nome": "Demais", "ate_percentual": None, "quantidade": int(contagens.get("Demais", 0))},
        ],
        "itens": _itens_produtos_previa(classificado),
    }


# ---------------------------------------------------------------------------
# Pasta base onde ficam as configurações salvas por empresa (uma subpasta por
# empresa, com um config.json dentro). Padrão: base-clientes/ na raiz do
# projeto; o usuário pode sobrescrever via ícone de engrenagem.
# ---------------------------------------------------------------------------

CHAVE_CAMINHO_EMPRESAS = "caminho_empresas"
NOME_PASTA_INVALIDO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CAMINHO_BASE_CLIENTES_PADRAO = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "base-clientes"
)


def _validar_nome_empresa(nome: str) -> str:
    nome = nome.strip()
    if not nome or nome in (".", "..") or NOME_PASTA_INVALIDO.search(nome):
        raise HTTPException(status_code=400, detail="Nome de empresa inválido.")
    return nome


def _resolver_caminho_empresas() -> Optional[str]:
    caminho = db.obter_config_app(CHAVE_CAMINHO_EMPRESAS)
    if caminho and os.path.isdir(caminho):
        return caminho
    if os.path.isdir(CAMINHO_BASE_CLIENTES_PADRAO):
        return CAMINHO_BASE_CLIENTES_PADRAO
    return caminho if caminho else None


def _caminho_base_empresas() -> str:
    caminho = _resolver_caminho_empresas()
    if not caminho:
        raise HTTPException(
            status_code=400,
            detail="Configure a pasta onde salvar as empresas (ícone de engrenagem) antes de salvar/carregar.",
        )
    return caminho


@app.get("/api/config/caminho-empresas")
def obter_caminho_empresas(usuario: str = Depends(exigir_login)):
    return {"caminho": _resolver_caminho_empresas()}


class CaminhoEmpresas(BaseModel):
    caminho: str


@app.post("/api/config/caminho-empresas")
def definir_caminho_empresas(corpo: CaminhoEmpresas, usuario: str = Depends(exigir_login)):
    caminho = corpo.caminho.strip()
    if not caminho:
        raise HTTPException(status_code=400, detail="Informe um caminho de pasta.")
    try:
        os.makedirs(caminho, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível criar/acessar essa pasta: {exc}")
    db.definir_config_app(CHAVE_CAMINHO_EMPRESAS, caminho)
    return {"caminho": caminho}


@app.get("/api/empresas")
def listar_empresas(usuario: str = Depends(exigir_login)):
    caminho = _resolver_caminho_empresas()
    if not caminho or not os.path.isdir(caminho):
        return []
    return sorted(
        nome for nome in os.listdir(caminho) if os.path.isdir(os.path.join(caminho, nome))
    )


class ConfiguracaoEmpresa(BaseModel):
    dados: dict


@app.post("/api/empresas/{nome}/configuracao")
def salvar_configuracao_empresa(nome: str, corpo: ConfiguracaoEmpresa, usuario: str = Depends(exigir_login)):
    nome = _validar_nome_empresa(nome)
    pasta_empresa = os.path.join(_caminho_base_empresas(), nome)
    os.makedirs(pasta_empresa, exist_ok=True)
    with open(os.path.join(pasta_empresa, "config.json"), "w", encoding="utf-8") as arquivo:
        json.dump(corpo.dados, arquivo, ensure_ascii=False, indent=2)
    return {"ok": True}


@app.get("/api/empresas/{nome}/configuracao")
def carregar_configuracao_empresa(nome: str, usuario: str = Depends(exigir_login)):
    nome = _validar_nome_empresa(nome)
    caminho_arquivo = os.path.join(_caminho_base_empresas(), nome, "config.json")
    if not os.path.exists(caminho_arquivo):
        raise HTTPException(status_code=404, detail="Configuração não encontrada para esta empresa.")
    with open(caminho_arquivo, "r", encoding="utf-8") as arquivo:
        return json.load(arquivo)


# ---------------------------------------------------------------------------
# Dashboard (rota / do frontend) — dados por empresa.
#
# Chave de config SEPARADA da caminho_empresas do Analisador: aquela guarda
# as configurações salvas por empresa (config.json), esta aponta para as
# pastas de DADOS das empresas (uma subpasta por empresa contendo Base.csv).
# Na prática hoje podem apontar para o mesmo lugar (base-clientes/), mas são
# configurações independentes.
#
# AUTENTICAÇÃO: o dashboard é público (a rota / não tem login e o navegador
# não tem token), então estes endpoints — inclusive o POST do caminho — ficam
# sem Depends(exigir_login) por enquanto (app de uso interno).
# ---------------------------------------------------------------------------

CHAVE_CAMINHO_DADOS_DASHBOARD = "caminho_dados_dashboard"


def _resolver_caminho_dados_dashboard() -> Optional[str]:
    caminho = db.obter_config_app(CHAVE_CAMINHO_DADOS_DASHBOARD)
    if caminho and os.path.isdir(caminho):
        return caminho
    if os.path.isdir(CAMINHO_BASE_CLIENTES_PADRAO):
        return CAMINHO_BASE_CLIENTES_PADRAO
    return caminho if caminho else None


@app.get("/api/dashboard/caminho-dados")
def obter_caminho_dados_dashboard():
    return {"caminho": _resolver_caminho_dados_dashboard()}


@app.post("/api/dashboard/caminho-dados")
def definir_caminho_dados_dashboard(corpo: CaminhoEmpresas):
    caminho = corpo.caminho.strip()
    if not caminho:
        raise HTTPException(status_code=400, detail="Informe um caminho de pasta.")
    try:
        os.makedirs(caminho, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível criar/acessar essa pasta: {exc}")
    db.definir_config_app(CHAVE_CAMINHO_DADOS_DASHBOARD, caminho)
    return {"caminho": caminho}


@app.get("/api/dashboard/empresas")
def listar_empresas_dashboard():
    """Nomes das subpastas diretas do caminho configurado (uma por empresa).

    Caminho não configurado/inexistente -> lista vazia (o frontend orienta o
    usuário a configurar via engrenagem), em vez de erro.
    """
    caminho = _resolver_caminho_dados_dashboard()
    if not caminho or not os.path.isdir(caminho):
        return []
    return sorted(
        nome for nome in os.listdir(caminho) if os.path.isdir(os.path.join(caminho, nome))
    )


# Cache por empresa: reprocessa só quando o Base.csv muda (mesmo padrão do
# _cache_base — o summary de 647k linhas leva alguns segundos para gerar).
_cache_summary_dashboard: dict[str, dict] = {}


@app.get("/api/dashboard/summary/{empresa}")
def obter_summary_dashboard(empresa: str):
    empresa = _validar_nome_empresa(empresa)
    caminho = _resolver_caminho_dados_dashboard()
    if not caminho or not os.path.isdir(caminho):
        raise HTTPException(
            status_code=400,
            detail="Configure a pasta de dados das empresas (ícone de engrenagem) antes de selecionar uma empresa.",
        )

    caminho_csv = os.path.join(caminho, empresa, "Base.csv")
    if not os.path.exists(caminho_csv):
        raise HTTPException(
            status_code=404,
            detail=f"Base.csv não encontrado para a empresa '{empresa}'.",
        )

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


def _carregar_df_filtrado(produtos_excluidos: list[str]) -> pd.DataFrame:
    df, _ = _carregar_base_padrao()
    if produtos_excluidos:
        df = df[~df["descricao"].isin(produtos_excluidos)]
    return df


def _rodar_analises(parametros: ParametrosAnalise) -> dict:
    df_filtrado = _carregar_df_filtrado(parametros.produtos_excluidos)
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
