"""
Backend do Analisador de Monitoria (versão web) — reaproveita o motor
analise_funil.py do app desktop original via FastAPI.
"""

import json
import logging
import os
import re
import secrets
import unicodedata
import sys
import tempfile
import threading
import time
import traceback
import unicodedata
from collections import OrderedDict
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("uvicorn.error")

import pandas as pd
import numpy as np
from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

import db
from auth import criar_token, exigir_login
from dashboard_summary import (
    caminho_summary_dashboard,
    caminho_summary_dashboard_gz,
    gerar_e_gravar_summary_dashboard,
    invalidar_summary_dashboard,
    summary_dashboard_atualizado,
)
from engine import analise_funil as af
from engine.exportadores_pdf_word import exportar_relatorio_pdf
from exportar_html import exportar_relatorio_html
from monitor_empresas import METRICAS_MONITOR, montar_card, obter_resumo_monitor
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

from normalizar_base import (  # noqa: E402
    ErroNormalizacao,
    parse_numero_flexivel,
    resolver_arquivos_dados,
)
from normalizar_liquidez import normalizar_estoque, normalizar_vendas  # noqa: E402

CAMINHO_BASE_PADRAO = os.path.join(RAIZ_PROJETO, "base_de_dados.xlsx")

app = FastAPI(title="Analisador de Monitoria - API")

# Summary grande já vai pré-comprimido (.json.gz). Não usar GZipMiddleware
# global — recomprimir on-the-fly dezenas de MB estoura o tempo da splash.
app.add_middleware(
    CORSMiddleware,
    # Dev/preview: localhost + LAN (ex.: http://192.168.1.13:5173).
    # Com proxy Vite (/api relativo) o browser não precisa de CORS; isto cobre
    # chamadas diretas à porta 8003 e acesso pela IP da máquina.
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1|192\.168\.\d+\.\d+|10\.\d+\.\d+\.\d+)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Ultimo-Movimento", "X-Resultado-Analise", "X-Resultado-Cache"],
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
# caminho_fonte_dados  — somente leitura: /{empresa}/Dados Mais Atacado.xlsx
#                         + Estoque/Vendas legados opcionais, na mesma pasta
# caminho_trabalho     — escrita: /{cliente}/summary_dashboard.json, config.json, harm.xlsx, tags
#
# Chaves legadas (caminho_dados_dashboard / caminho_empresas) ainda são lidas
# como fallback na migração.
# ---------------------------------------------------------------------------

CHAVE_CAMINHO_FONTE_DADOS = "caminho_fonte_dados"
CHAVE_CAMINHO_TRABALHO = "caminho_trabalho"
# Flag manual: "1" = ainda aguardando a base de dados ser montada na fonte (mostra
# aviso no Dashboard público em vez de dados/erro). Liga/desliga em Configurações.
CHAVE_AGUARDANDO_BASE_DADOS = "aguardando_base_dados"
#: Empresas favoritas da tela de monitoramento (JSON com lista de nomes).
#: Fica no SQLite, não no navegador: o app é interno e sem separação de usuário,
#: então favoritar numa máquina precisa valer na outra.
CHAVE_EMPRESAS_FAVORITAS = "empresas_favoritas"
# Legadas — só leitura de fallback / aliases de rota
CHAVE_CAMINHO_DADOS_DASHBOARD = "caminho_dados_dashboard"
CHAVE_CAMINHO_EMPRESAS = "caminho_empresas"

NOME_PASTA_INVALIDO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CAMINHO_BASE_CLIENTES_PADRAO = os.path.join(RAIZ_PROJETO, "base-clientes")
NOME_ARQUIVO_TAGS_CLIENTES = "clientes_tags.json"
NOME_ARQUIVO_CONFIG = "config.json"
# Escopo "" = "Todas as lojas"; demais chaves = nome da loja.
FORMATO_POR_LOJA = "por_loja"
CHAVE_FORMATO = "_formato"
CHAVE_SCOPES = "scopes"
_CAMPOS_CONFIG_FLAT = frozenset({
    "cortesClientes", "corteProdutos", "periodosQueda", "desconsiderarBalcao",
    "desconsiderarDemaisProdutos", "desconsiderarNaoHarmonizados", "excluirPeriodoAtual",
    "nomeEmpresa", "topNProdutos", "reducaoMinimaErosao", "maxPorGrupo",
    "quedaMinimaAlertaRs", "quedaMinimaErosaoRs", "reducaoMinimaSemVenda",
    "topNPoderCompra", "clientesExcluidos", "produtosExcluidos",
    "chavesSelecionadas", "granularidade",
})
_CAMPOS_TAGS_FLAT = frozenset({"tags", "catalogo", "grupos", "clientes_balcao"})

TAGS_CATALOGO_PADRAO: list[dict] = [
    {"id": "alerta", "rotulo": "Alerta", "ativa": True, "cor": "#ec1818"},
    {"id": "inadimplente", "rotulo": "Inadimplente", "ativa": True, "cor": "#f43f5e"},
    {"id": "cliente_balcao", "rotulo": "Cliente Balcão", "ativa": True, "cor": "#f59e0b"},
    {"id": "encerrou_operacao", "rotulo": "Encerrou operação", "ativa": True, "cor": "#64748b"},
]

_REGEX_ID_TAG = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
_COR_TAG_PADRAO = "#64748b"


def _slug_de_rotulo(rotulo: str) -> str:
    texto = unicodedata.normalize("NFKD", rotulo.strip().lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    texto = re.sub(r"[^a-z0-9]+", "_", texto).strip("_")
    return (texto[:48] or "tag")


def _normalizar_id_tag(bruto, rotulo_fallback: str = "") -> str:
    tag_id = str(bruto or "").strip().lower()
    if tag_id and _REGEX_ID_TAG.match(tag_id):
        return tag_id
    candidato = _slug_de_rotulo(rotulo_fallback)
    return candidato if _REGEX_ID_TAG.match(candidato) else "tag"


def _ids_do_catalogo(catalogo: list[dict]) -> set[str]:
    return {item["id"] for item in catalogo if isinstance(item, dict) and item.get("id")}


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
            detail="Configure a pasta fonte de dados (somente leitura) antes de continuar.",
        )
    return caminho


def _exigir_caminho_trabalho() -> str:
    caminho = _resolver_caminho_trabalho()
    if not caminho:
        raise HTTPException(
            status_code=400,
            detail="Configure a pasta de trabalho (summary_dashboard.json / config.json) antes de continuar.",
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
    """Lista subpastas com Dados Mais Atacado.xlsx diretamente dentro, somente leitura."""
    caminho = _resolver_caminho_fonte()
    if not caminho or not os.path.isdir(caminho):
        return []
    resultado = []
    for nome in os.listdir(caminho):
        pasta_empresa = os.path.join(caminho, nome)
        if not os.path.isdir(pasta_empresa):
            continue
        try:
            resolver_arquivos_dados(Path(pasta_empresa))
        except (ErroNormalizacao, OSError):
            continue
        resultado.append(nome)
    return sorted(resultado)


def _pastas_empresa(empresa: str) -> tuple[str, str]:
    """Retorna (pasta_fonte, pasta_trabalho) para a empresa."""
    empresa = _validar_nome_empresa(empresa)
    fonte_root = _exigir_caminho_fonte()
    trabalho_root = _exigir_caminho_trabalho()
    pasta_fonte = os.path.join(fonte_root, empresa)
    pasta_trabalho = os.path.join(trabalho_root, empresa)
    if not os.path.isdir(pasta_fonte):
        raise HTTPException(status_code=404, detail=f"Empresa '{empresa}' não encontrada na pasta fonte.")
    try:
        resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
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


def _caminho_config_empresa(empresa: str) -> str:
    return os.path.join(_pasta_trabalho_empresa(empresa), NOME_ARQUIVO_CONFIG)


def _chave_escopo_loja(loja: Optional[str]) -> str:
    """Chave de escopo: '' = todas as lojas; senão o nome da loja."""
    if loja is None:
        return ""
    return str(loja).strip()


def _scopes_de_arquivo_generico(bruto: dict, campos_flat: frozenset[str]) -> dict[str, dict]:
    """Normaliza arquivo flat legado ou `{_formato, scopes}` para mapa chave→slice."""
    if not isinstance(bruto, dict) or not bruto:
        return {}
    if bruto.get(CHAVE_FORMATO) == FORMATO_POR_LOJA:
        scopes = bruto.get(CHAVE_SCOPES)
        if not isinstance(scopes, dict):
            return {}
        saida: dict[str, dict] = {}
        for chave, slice_ in scopes.items():
            if isinstance(slice_, dict):
                saida[str(chave)] = dict(slice_)
        return saida
    if campos_flat.intersection(bruto.keys()):
        return {"": dict(bruto)}
    # Mapa já no formato chave→slice (sem marcador), sem campos flat no topo.
    if all(isinstance(v, dict) for v in bruto.values()):
        return {str(k): dict(v) for k, v in bruto.items()}
    return {"": dict(bruto)}


def _payload_arquivo_por_loja(scopes: dict[str, dict]) -> dict:
    return {CHAVE_FORMATO: FORMATO_POR_LOJA, CHAVE_SCOPES: scopes}


def _ler_json_trabalho(caminho: str) -> dict:
    if not os.path.isfile(caminho):
        return {}
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            bruto = json.load(arquivo)
    except (OSError, json.JSONDecodeError):
        return {}
    return bruto if isinstance(bruto, dict) else {}


def _gravar_json_trabalho(caminho: str, payload: dict) -> None:
    _assert_escrita_fora_da_fonte(caminho)
    try:
        with open(caminho, "w", encoding="utf-8") as arquivo:
            json.dump(payload, arquivo, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível gravar {os.path.basename(caminho)}: {exc}")


def _ler_scopes_config(empresa: str) -> dict[str, dict]:
    return _scopes_de_arquivo_generico(
        _ler_json_trabalho(_caminho_config_empresa(empresa)),
        _CAMPOS_CONFIG_FLAT,
    )


def _gravar_scopes_config(empresa: str, scopes: dict[str, dict]) -> str:
    caminho = _caminho_config_empresa(empresa)
    _gravar_json_trabalho(caminho, _payload_arquivo_por_loja(scopes))
    return caminho


def _ler_config_escopo(empresa: str, loja: Optional[str] = None) -> Optional[dict]:
    scopes = _ler_scopes_config(empresa)
    chave = _chave_escopo_loja(loja)
    if chave not in scopes:
        return None
    return dict(scopes[chave])


def _gravar_config_escopo(empresa: str, loja: Optional[str], dados: dict) -> str:
    scopes = _ler_scopes_config(empresa)
    scopes[_chave_escopo_loja(loja)] = dict(dados) if isinstance(dados, dict) else {}
    return _gravar_scopes_config(empresa, scopes)


def _ler_scopes_tags(empresa: str) -> dict[str, dict]:
    return _scopes_de_arquivo_generico(
        _ler_arquivo_tags_clientes_bruto(empresa),
        _CAMPOS_TAGS_FLAT,
    )


def _gravar_scopes_tags(empresa: str, scopes: dict[str, dict]) -> str:
    caminho = _caminho_tags_clientes(empresa)
    _gravar_json_trabalho(caminho, _payload_arquivo_por_loja(scopes))
    return caminho


def _normalizar_mapa_tags(tags_bruto, ids_validos: set[str] | None = None) -> dict[str, list[str]]:
    if ids_validos is None:
        ids_validos = _ids_do_catalogo(TAGS_CATALOGO_PADRAO)
    if not isinstance(tags_bruto, dict):
        return {}
    saida: dict[str, list[str]] = {}
    for nome, lista in tags_bruto.items():
        cliente = str(nome).strip()
        if not cliente:
            continue
        if not isinstance(lista, list):
            continue
        limpas = list(saida.get(cliente, []))
        for tag in lista:
            t = str(tag).strip().lower()
            if t in ids_validos and t not in limpas:
                limpas.append(t)
        if limpas:
            saida[cliente] = limpas
    return saida


def _tag_alerta_padrao() -> dict:
    for item in TAGS_CATALOGO_PADRAO:
        if item.get("id") == "alerta":
            return dict(item)
    return {"id": "alerta", "rotulo": "Alerta", "ativa": True, "cor": "#ec1818"}


def _catalogo_tem_tag_alerta(catalogo: list[dict]) -> bool:
    for item in catalogo:
        tag_id = str(item.get("id", "")).strip().lower()
        rotulo = _slug_de_rotulo(str(item.get("rotulo", "")))
        if tag_id == "alerta" or rotulo == "alerta":
            return True
    return False


def _garantir_tag_alerta(catalogo: list[dict]) -> list[dict]:
    """Garante a tag base Alerta em todas as empresas (mesmo com catálogo já salvo)."""
    if _catalogo_tem_tag_alerta(catalogo):
        return catalogo
    return [_tag_alerta_padrao(), *catalogo]


def _normalizar_catalogo_tags(catalogo_bruto) -> list[dict]:
    """Catálogo dinâmico por empresa; sem catálogo salvo, usa o padrão (inclui Alerta)."""
    if not isinstance(catalogo_bruto, list) or not catalogo_bruto:
        return _garantir_tag_alerta([dict(item) for item in TAGS_CATALOGO_PADRAO])

    saida: list[dict] = []
    vistos: set[str] = set()
    for item in catalogo_bruto:
        if not isinstance(item, dict):
            continue
        rotulo = str(item.get("rotulo", "")).strip()
        tag_id = _normalizar_id_tag(item.get("id"), rotulo)
        if tag_id in vistos:
            base = _slug_de_rotulo(rotulo or tag_id)
            sufixo = 2
            candidato = f"{base}_{sufixo}"
            while candidato in vistos:
                sufixo += 1
                candidato = f"{base}_{sufixo}"
            tag_id = candidato
        vistos.add(tag_id)
        if not rotulo:
            rotulo = tag_id.replace("_", " ").title()
        cor = str(item.get("cor", "")).strip()
        if not (cor.startswith("#") and len(cor) in (4, 7)):
            cor = _COR_TAG_PADRAO
        saida.append({
            "id": tag_id,
            "rotulo": rotulo,
            "ativa": bool(item.get("ativa", True)),
            "cor": cor,
        })

    if not saida:
        return _garantir_tag_alerta([dict(item) for item in TAGS_CATALOGO_PADRAO])
    return _garantir_tag_alerta(saida)


def _sincronizar_lista_balcao(tags: dict[str, list[str]]) -> list[str]:
    return sorted(
        nome for nome, lista in tags.items()
        if af.TAG_CLIENTE_BALCAO in lista
    )


def _ler_arquivo_tags_clientes_bruto(empresa: str) -> dict:
    caminho = os.path.join(_exigir_caminho_trabalho(), _validar_nome_empresa(empresa), NOME_ARQUIVO_TAGS_CLIENTES)
    return _ler_json_trabalho(caminho)


def _montar_resposta_tags_clientes(
    empresa: str,
    bruto: dict,
    tags: dict[str, list[str]],
    catalogo: list[dict] | None = None,
    grupos: list[dict] | None = None,
    loja: Optional[str] = None,
) -> dict:
    catalogo_norm = catalogo if catalogo is not None else _normalizar_catalogo_tags(bruto.get("catalogo"))
    balcao = _sincronizar_lista_balcao(tags)
    grupos_norm = grupos if grupos is not None else _normalizar_grupos_manuais(bruto.get("grupos"))
    return {
        "tags": tags,
        "clientes_balcao": balcao,
        "catalogo": catalogo_norm,
        "grupos": grupos_norm,
        "loja": _chave_escopo_loja(loja) or None,
    }


def _normalizar_grupos_manuais(grupos_bruto) -> list[dict]:
    """Grupos manuais: nome + lista de clientes. Um cliente só em um grupo (primeiro vence)."""
    if not isinstance(grupos_bruto, list):
        return []
    saida: list[dict] = []
    vistos_id: set[str] = set()
    clientes_em_grupo: set[str] = set()
    for item in grupos_bruto:
        if not isinstance(item, dict):
            continue
        nome = str(item.get("nome") or "").strip()
        if not nome:
            continue
        grupo_id = _normalizar_id_tag(item.get("id"), nome)
        if grupo_id in vistos_id:
            base = _slug_de_rotulo(nome)
            sufixo = 2
            candidato = f"{base}_{sufixo}"
            while candidato in vistos_id:
                sufixo += 1
                candidato = f"{base}_{sufixo}"
            grupo_id = candidato
        vistos_id.add(grupo_id)
        membros: list[str] = []
        for cliente in item.get("clientes") or []:
            chave = str(cliente).strip()
            if not chave or chave in clientes_em_grupo:
                continue
            clientes_em_grupo.add(chave)
            membros.append(chave)
        saida.append({"id": grupo_id, "nome": nome, "clientes": membros})
    return saida


def _payload_tags_completo(
    catalogo: list[dict],
    tags: dict[str, list[str]],
    grupos: list[dict] | None = None,
    bruto_atual: dict | None = None,
) -> dict:
    grupos_norm = (
        grupos if grupos is not None
        else _normalizar_grupos_manuais((bruto_atual or {}).get("grupos"))
    )
    return {
        "catalogo": catalogo,
        "tags": tags,
        "clientes_balcao": _sincronizar_lista_balcao(tags),
        "grupos": grupos_norm,
    }


def _slice_tags_do_escopo(empresa: str, loja: Optional[str] = None) -> dict:
    scopes = _ler_scopes_tags(empresa)
    return dict(scopes.get(_chave_escopo_loja(loja), {}))


def _gravar_arquivo_tags_clientes(
    empresa: str,
    payload: dict,
    loja: Optional[str] = None,
) -> dict:
    scopes = _ler_scopes_tags(empresa)
    chave = _chave_escopo_loja(loja)
    catalogo = _normalizar_catalogo_tags(payload.get("catalogo"))
    tags = _normalizar_mapa_tags(payload.get("tags"), _ids_do_catalogo(catalogo))
    grupos = _normalizar_grupos_manuais(payload.get("grupos"))
    slice_norm = _payload_tags_completo(catalogo, tags, grupos=grupos)
    scopes[chave] = slice_norm
    caminho = _gravar_scopes_tags(empresa, scopes)
    return {
        **_montar_resposta_tags_clientes(empresa, slice_norm, tags, catalogo, grupos, loja=loja),
        "caminho": caminho,
    }


def _ler_tags_clientes(empresa: str, loja: Optional[str] = None) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _normalizar_catalogo_tags(bruto.get("catalogo"))
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    grupos = _normalizar_grupos_manuais(bruto.get("grupos") if bruto else [])
    return _montar_resposta_tags_clientes(empresa, bruto, tags, catalogo, grupos, loja=loja)


def _gravar_tags_clientes(
    empresa: str,
    tags: dict[str, list[str]],
    loja: Optional[str] = None,
) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _normalizar_catalogo_tags(bruto.get("catalogo"))
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags_norm = _normalizar_mapa_tags(tags, ids_catalogo)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(catalogo, tags_norm, bruto_atual=bruto),
        loja=loja,
    )


def _gravar_catalogo_tags(empresa: str, catalogo_bruto, loja: Optional[str] = None) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _normalizar_catalogo_tags(catalogo_bruto)
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(catalogo, tags, bruto_atual=bruto),
        loja=loja,
    )


def _gravar_grupos_manuais(empresa: str, grupos_bruto, loja: Optional[str] = None) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _normalizar_catalogo_tags(bruto.get("catalogo"))
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    grupos = _normalizar_grupos_manuais(grupos_bruto)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(catalogo, tags, grupos=grupos),
        loja=loja,
    )


def _clientes_balcao_extra(empresa: Optional[str], loja: Optional[str] = None) -> list[str]:
    if not empresa or not str(empresa).strip():
        return []
    try:
        return list(_ler_tags_clientes(empresa.strip(), loja=loja)["clientes_balcao"])
    except HTTPException:
        return []


def _grupos_manuais_empresa(empresa: Optional[str], loja: Optional[str] = None) -> list[dict]:
    if not empresa or not str(empresa).strip():
        return []
    try:
        return list(_ler_tags_clientes(empresa.strip(), loja=loja).get("grupos") or [])
    except HTTPException:
        return []


# Máximo de empresas em cache (cada DF/summary pode ser grande).
_CACHE_EMPRESA_MAX = 3
# DataFrame aberto ocupa muitas vezes o tamanho do XLSX comprimido. O Analisador
# usa uma empresa por vez; manter três bases foi observado levando o processo a
# gigabytes em repouso. Summaries compactos continuam com o LRU maior acima.
_CACHE_BASE_EMPRESA_MAX = 1

# Cache por empresa do DataFrame lido direto da fonte (mtime do XLSX -> df).
# LRU via OrderedDict. Não há mais Base.csv em disco — nada é persistido no trabalho
# além do summary_dashboard.json/config/harm/tags.
_cache_base_empresa: OrderedDict[str, dict] = OrderedDict()

# Cache do Excel padrão (sem empresa selecionada).
_cache_base: dict = {"mtime": None, "df": None, "linhas_vazias": 0}

# Cache do summary do dashboard por empresa. LRU via OrderedDict.
_cache_summary_dashboard: OrderedDict[str, dict] = OrderedDict()

# Uma mesma empresa pode ser solicitada várias vezes em paralelo (F5, StrictMode,
# vários clientes na LAN). Sem single-flight, cada request relê o XLSX e gera o
# mesmo summary, multiplicando CPU/RAM e deixando até o seletor sem resposta.
_travas_summary_empresa: dict[str, threading.RLock] = {}
_travas_summary_empresa_guard = threading.Lock()


def _trava_summary_empresa(empresa: str):
    """Retorna trava reentrante estável para geração/cache de uma empresa."""
    with _travas_summary_empresa_guard:
        trava = _travas_summary_empresa.get(empresa)
        if trava is None:
            trava = threading.RLock()
            _travas_summary_empresa[empresa] = trava
        return trava

def _lru_touch(cache: OrderedDict, key: str) -> None:
    """Marca key como mais recentemente usada (hit)."""
    if key in cache:
        cache.move_to_end(key)


def _lru_set(cache: OrderedDict, key: str, value: dict, max_size: int = _CACHE_EMPRESA_MAX) -> None:
    """Insere/atualiza e evicta a entrada mais antiga se passar do limite."""
    if key in cache:
        cache.move_to_end(key)
    cache[key] = value
    while len(cache) > max_size:
        cache.popitem(last=False)


def _data_ultimo_movimento_bi(pasta_fonte: str) -> Optional[date]:
    """Data de modificação da base XLSX na fonte (somente leitura).

    O arquivo novo só tem Ano/Mês (sem dia) — usa-se a data de última escrita
    do arquivo como proxy de "última atualização" em vez de tentar extrair
    um dia exato dos dados.
    """
    try:
        caminho_atacado, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
        return date.fromtimestamp(os.path.getmtime(caminho_atacado))
    except ErroNormalizacao as exc:
        logger.warning("Dados indisponíveis para data de atualização em %s: %s", pasta_fonte, exc)
        return None
    except Exception as exc:
        logger.warning("Falha ao ler data de atualização em %s: %s", pasta_fonte, exc)
        return None


def _carregar_atacado_df(pasta_fonte: str) -> pd.DataFrame:
    """Lê a base XLSX da empresa direto da fonte.

    O arquivo já chega normalizado. Este fluxo só lê, mapeia colunas em memória
    e nunca cria Base.csv, harm.xlsx ou qualquer outro arquivo na fonte."""
    caminho_atacado, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    return af.carregar_excel_base_empresa(caminho_atacado)


def _garantir_summary_dashboard_arquivo(
    empresa: str,
    pasta_fonte: str,
    pasta_trabalho: str,
    caminho_atacado: str,
) -> Path:
    """Single-flight: somente uma geração do summary por empresa por vez."""
    with _trava_summary_empresa(empresa):
        return _garantir_summary_dashboard_arquivo_sem_trava(
            empresa,
            pasta_fonte,
            pasta_trabalho,
            caminho_atacado,
        )


def _garantir_summary_dashboard_arquivo_sem_trava(
    empresa: str,
    pasta_fonte: str,
    pasta_trabalho: str,
    caminho_atacado: str,
) -> Path:
    """Garante summary_dashboard.json(.gz) fresco vs a fonte; regenera se preciso.

    Frescor é comparado contra o mtime de Dados Mais Atacado.xlsx na fonte (não
    há mais Base.csv intermediário). Prefere o .gz (pré-comprimido) para evitar
    gzip on-the-fly no hot path.
    """
    caminho_gz = caminho_summary_dashboard_gz(pasta_trabalho)
    caminho_json = caminho_summary_dashboard(pasta_trabalho)

    if summary_dashboard_atualizado(pasta_trabalho, caminho_atacado):
        if caminho_gz.is_file():
            return caminho_gz
        if caminho_json.is_file():
            # JSON legado sem .gz — comprime uma vez a partir do arquivo existente.
            try:
                import gzip as _gzip
                payload = caminho_json.read_bytes()
                fd_gz, tmp_gz = tempfile.mkstemp(
                    prefix="summary_dashboard_",
                    suffix=".json.gz.tmp",
                    dir=str(Path(pasta_trabalho)),
                )
                try:
                    os.close(fd_gz)
                    with _gzip.open(tmp_gz, "wb", compresslevel=4) as f:
                        f.write(payload)
                    os.replace(tmp_gz, caminho_gz)
                except Exception:
                    try:
                        os.unlink(tmp_gz)
                    except OSError:
                        pass
                    raise
                return caminho_gz
            except Exception as exc:
                logger.warning(
                    "Falha ao comprimir summary legado de %s; servindo JSON: %s",
                    empresa,
                    exc,
                )
                return caminho_json

    _assert_fonte_diferente_de_trabalho()
    _assert_escrita_fora_da_fonte(pasta_trabalho)

    try:
        df, _linhas_vazias = _carregar_base_empresa(empresa)
        data_ultimo = _data_ultimo_movimento_bi(pasta_fonte)
        caminho = gerar_e_gravar_summary_dashboard(
            pasta_trabalho,
            df,
            data_ultimo_movimento=data_ultimo,
        )
    except HTTPException:
        raise
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error(
            "Falha inesperada ao gerar summary da empresa %s:\n%s",
            empresa,
            traceback.format_exc(),
        )
        raise HTTPException(
            status_code=400,
            detail=f"Falha inesperada ao processar a base: {exc}",
        )

    return caminho


def _corpo_summary_cacheado(empresa: str, caminho_summary: Path, mtime_csv: float) -> bytes:
    """Bytes do arquivo summary (preferência .gz), com cache LRU em RAM."""
    em_cache = _cache_summary_dashboard.get(empresa)
    if (
        em_cache
        and em_cache.get("mtime") == mtime_csv
        and em_cache.get("path") == str(caminho_summary)
        and isinstance(em_cache.get("body"), (bytes, bytearray))
    ):
        _lru_touch(_cache_summary_dashboard, empresa)
        return em_cache["body"]

    body = Path(caminho_summary).read_bytes()
    _lru_set(
        _cache_summary_dashboard,
        empresa,
        {
            "mtime": mtime_csv,
            "path": str(caminho_summary),
            "body": body,
            "gzip": caminho_summary.name.endswith(".json.gz"),
        },
    )
    return body


def _resposta_summary_arquivo(
    empresa: str,
    caminho_summary: Path,
    pasta_fonte: str,
    caminho_atacado: str,
) -> Response:
    """Serve summary pré-serializado (RAM/disco); header com data da fonte."""
    mtime_csv = os.path.getmtime(caminho_atacado)
    body = _corpo_summary_cacheado(empresa, caminho_summary, mtime_csv)
    headers: dict[str, str] = {}
    data_ultimo = _data_ultimo_movimento_bi(pasta_fonte)
    if data_ultimo is not None:
        headers["X-Ultimo-Movimento"] = data_ultimo.strftime("%d/%m/%Y")
    if caminho_summary.name.endswith(".json.gz"):
        headers["Content-Encoding"] = "gzip"
    return Response(
        content=body,
        media_type="application/json",
        headers=headers,
    )


def _regenerar_base_empresa(empresa: str) -> dict:
    """Limpa caches (RAM + summary em disco) e força reprocessamento direto da fonte."""
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_atacado, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # A trava também cobre invalidação; evita apagar arquivo enquanto outra
    # request ainda o lê. É RLock porque a função garantir reutiliza a mesma trava.
    with _trava_summary_empresa(empresa):
        _cache_summary_dashboard.pop(empresa, None)
        _cache_base_empresa.pop(empresa, None)
        invalidar_summary_dashboard(pasta_trabalho)

        caminho_summary = _garantir_summary_dashboard_arquivo(
            empresa, pasta_fonte, pasta_trabalho, str(caminho_atacado),
        )
    return {
        "ok": True,
        "empresa": empresa,
        "summary": str(caminho_summary),
    }


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
        df = _normalizar_coluna_loja_inplace(df)
        _cache_base.update(mtime=mtime, df=df, linhas_vazias=linhas_vazias)

    return _cache_base["df"], _cache_base["linhas_vazias"]


def _carregar_base_empresa(empresa: str) -> tuple[pd.DataFrame, int]:
    """Single-flight compartilhado por Dashboard e Analisador."""
    with _trava_summary_empresa(empresa):
        return _carregar_base_empresa_sem_trava(empresa)


def _carregar_base_empresa_sem_trava(empresa: str) -> tuple[pd.DataFrame, int]:
    """Lê Dados Mais Atacado.xlsx direto da fonte (sem arquivo intermediário).

    Cache LRU em RAM chaveado no mtime do XLSX na fonte.
    """
    pasta_fonte, _pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_atacado, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    mtime = os.path.getmtime(caminho_atacado)
    em_cache = _cache_base_empresa.get(empresa)
    if em_cache and em_cache["mtime"] == mtime:
        _lru_touch(_cache_base_empresa, empresa)
        return em_cache["df"], em_cache["linhas_vazias"]

    try:
        df_bruto = _carregar_atacado_df(pasta_fonte)
        df, linhas_vazias = af.validar_e_limpar(df_bruto, receita_em_texto_br=False)
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao carregar dados de %s:\n%s", empresa, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao carregar a base: {exc}")

    df = _normalizar_coluna_loja_inplace(df)
    # Master DF no cache. Callers mutáveis recebem cópia por padrão; as rotas
    # explicitamente somente-leitura podem compartilhar este objeto.
    _lru_set(
        _cache_base_empresa,
        empresa,
        {"mtime": mtime, "df": df, "linhas_vazias": linhas_vazias},
        max_size=_CACHE_BASE_EMPRESA_MAX,
    )
    return df, linhas_vazias


def _normalizar_loja(loja: Optional[str]) -> Optional[str]:
    if loja is None:
        return None
    nome = str(loja).strip()
    return nome or None


def _normalizar_coluna_loja_inplace(df: pd.DataFrame) -> pd.DataFrame:
    """Normaliza Loja uma vez ao entrar no cache (strip); evita astype/str por request."""
    if df is None or df.empty or "Loja" not in df.columns:
        return df
    df["Loja"] = df["Loja"].fillna("").astype(str).str.strip()
    return df


def _listar_lojas(df: pd.DataFrame) -> list[str]:
    """Nomes distintos da coluna Loja (já normalizada no cache)."""
    if df is None or df.empty or "Loja" not in df.columns:
        return []
    nomes = [n for n in df["Loja"].unique().tolist() if n]
    return sorted(nomes, key=lambda s: s.casefold())


def _filtrar_loja(df: pd.DataFrame, loja: Optional[str]) -> pd.DataFrame:
    """Filtra pela coluna Loja (já normalizada). loja vazia/None = todas.

    Sempre devolve cópia quando filtra, para não expor view do DF em cache.
    """
    nome = _normalizar_loja(loja)
    if not nome or df is None or df.empty or "Loja" not in df.columns:
        return df
    return df.loc[df["Loja"] == nome].copy()


def _carregar_base(
    empresa: Optional[str] = None,
    loja: Optional[str] = None,
    *,
    copiar: bool = True,
) -> tuple[pd.DataFrame, int]:
    """Com empresa: dados direto da fonte (Dados Mais Atacado.xlsx). Sem empresa: Excel padrão da raiz.

    loja opcional filtra a coluna Loja depois do cache (o cache guarda o DF completo
    com Loja já normalizada). `copiar=False` é reservado a callers somente-leitura;
    o padrão defensivo continua isolando o cache contra mutações acidentais.
    """
    if empresa and empresa.strip():
        df, linhas_vazias = _carregar_base_empresa(empresa.strip())
    else:
        df, linhas_vazias = _carregar_base_padrao()
    nome = _normalizar_loja(loja)
    if nome:
        if "Loja" not in df.columns:
            raise HTTPException(status_code=400, detail=f"Loja '{nome}' não encontrada na base.")
        mask = df["Loja"] == nome
        if not bool(mask.any()):
            raise HTTPException(
                status_code=400,
                detail=f"Loja '{nome}' não encontrada na base.",
            )
        filtrado = df.loc[mask]
        return (filtrado.copy() if copiar else filtrado), linhas_vazias
    # Sem filtro de loja: cópia defensiva para callers nunca mutarem o DF em cache.
    return (df.copy() if copiar else df), linhas_vazias


@app.get("/api/base")
def obter_base(
    empresa: Optional[str] = None,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    # A rota apenas lista/conta; não precisa duplicar centenas de milhares de linhas.
    df_completo, linhas_vazias = _carregar_base(empresa, copiar=False)
    lojas = _listar_lojas(df_completo)
    loja_norm = _normalizar_loja(loja)
    if loja_norm and loja_norm not in lojas:
        raise HTTPException(
            status_code=400,
            detail=f"Loja '{loja_norm}' não encontrada na base.",
        )
    df = _filtrar_loja(df_completo, loja_norm) if loja_norm else df_completo

    qtd_nao_harmonizados = af.contar_produtos_nao_harmonizados(df)

    return {
        "linhas": len(df),
        "linhas_ignoradas": linhas_vazias,
        "qtd_nao_harmonizados": qtd_nao_harmonizados,
        "granularidades": af.GRANULARIDADES,
        "empresa": empresa.strip() if empresa and empresa.strip() else None,
        "lojas": lojas,
        "loja": loja_norm,
    }


# ---------------------------------------------------------------------------
# Prévia de grupos de clientes (segmentação por % de receita acumulada)
# ---------------------------------------------------------------------------

class ParametrosGrupos(BaseModel):
    clientes_excluidos: list[str] = []
    cortes_clientes: tuple[float, float, float] = (30.0, 50.0, 60.0)
    desconsiderar_balcao: bool = False
    empresa: Optional[str] = None
    loja: Optional[str] = None
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
    """Regra única, no motor — espelhada também pelo frontend."""
    return af.eh_produto_nao_harmonizado(nome)


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
            "cliente": str(cliente).strip(),
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
        if str(cliente).strip()
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
    max_itens_por_grupo: int,
    desconsiderar_balcao: bool,
    ajustar_cortes: bool = True,
    clientes_balcao_extra: Optional[List[str]] = None,
    grupos_manuais: Optional[list] = None,
) -> dict:
    # Grupos manuais substituem os indivíduos antes dos cortes ABC: a receita
    # do grupo é a soma dos membros; % e Faixa são recalculados; membros
    # deixam de aparecer como linhas próprias.
    df = af.aplicar_grupos_manuais_em_cliente(df, grupos_manuais)
    mapa = af.mapa_cliente_para_grupo_manual(grupos_manuais)
    excluidos = [mapa.get(c, c) for c in (clientes_excluidos or [])]
    balcao_extra = [
        mapa.get(c, c) for c in (clientes_balcao_extra or [])
    ]
    # dedupe preservando ordem
    def _uniq(seq):
        vistos = set()
        out = []
        for x in seq:
            if x not in vistos:
                vistos.add(x)
                out.append(x)
        return out
    excluidos = _uniq(excluidos)
    balcao_extra = _uniq(balcao_extra)

    if ajustar_cortes:
        cortes, _ = af.sugerir_cortes_grupos(
            df, excluidos, cortes_iniciais,
            max_por_grupo=max_itens_por_grupo, desconsiderar_balcao=desconsiderar_balcao,
            clientes_balcao_extra=balcao_extra,
        )
    else:
        cortes = list(cortes_iniciais)
    classificado = af.classificar_clientes_agregado(
        df, excluidos, cortes,
        desconsiderar_balcao=desconsiderar_balcao,
        clientes_balcao_extra=balcao_extra,
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
    # As funções abaixo agregam em novos DataFrames; a base cacheada é somente lida.
    df, _ = _carregar_base(parametros.empresa, loja=parametros.loja, copiar=False)
    return _previa_grupos_resposta(
        df,
        parametros.clientes_excluidos,
        parametros.cortes_clientes,
        parametros.max_itens_por_grupo,
        parametros.desconsiderar_balcao,
        ajustar_cortes=parametros.ajustar_cortes,
        clientes_balcao_extra=_clientes_balcao_extra(parametros.empresa, loja=parametros.loja),
        grupos_manuais=_grupos_manuais_empresa(parametros.empresa, loja=parametros.loja),
    )


class ParametrosSugerirCortes(ParametrosGrupos):
    """Alias legado: aceita max_por_grupo e mapeia para max_itens_por_grupo."""
    max_por_grupo: Optional[int] = None


@app.post("/api/grupos/sugerir-cortes")
def sugerir_cortes(parametros: ParametrosSugerirCortes, usuario: str = Depends(exigir_login)):
    """Alias de /api/grupos/previa com ajustar_cortes=True."""
    max_itens = (
        parametros.max_por_grupo
        if parametros.max_por_grupo is not None
        else parametros.max_itens_por_grupo
    )
    return previa_grupos(
        ParametrosGrupos(
            clientes_excluidos=parametros.clientes_excluidos,
            cortes_clientes=parametros.cortes_clientes,
            desconsiderar_balcao=parametros.desconsiderar_balcao,
            empresa=parametros.empresa,
            loja=parametros.loja,
            max_itens_por_grupo=max_itens,
            ajustar_cortes=True,
        ),
        usuario,
    )


# ---------------------------------------------------------------------------
# Prévia de produtos (alto giro x demais, pelo corte de produtos por receita)
# ---------------------------------------------------------------------------

class ParametrosProdutos(BaseModel):
    produtos_excluidos: list[str] = []
    corte_produtos: float = 80.0
    empresa: Optional[str] = None
    loja: Optional[str] = None
    max_itens_por_grupo: int = 20
    ajustar_cortes: bool = True


@app.post("/api/produtos/previa")
def previa_produtos(parametros: ParametrosProdutos, usuario: str = Depends(exigir_login)):
    # Classificação usa groupby e devolve outro frame; não altera a base cacheada.
    df, _ = _carregar_base(parametros.empresa, loja=parametros.loja, copiar=False)
    excluidos = {
        str(produto).strip()
        for produto in (parametros.produtos_excluidos or [])
        if str(produto).strip()
    }
    nomes_produtos = df["descricao"].astype(str)
    mascara_excluidos = nomes_produtos.isin(excluidos)
    base_incluida = df.loc[~mascara_excluidos]

    # A análise final remove produtos excluídos antes de montar a curva. A
    # prévia precisa usar exatamente a mesma base para grupo e percentuais.
    if parametros.ajustar_cortes:
        corte, _ = af.sugerir_corte_produtos(
            base_incluida,
            parametros.corte_produtos,
            max_por_grupo=parametros.max_itens_por_grupo,
        )
    else:
        corte = float(parametros.corte_produtos)
    classificado = af.classificar_produtos_agregado(base_incluida, corte)
    contagens = classificado["Faixa"].value_counts()
    demais = classificado.loc[classificado["Faixa"] == "Demais", "descricao"].astype(str)

    # Mantém excluídos visíveis para permitir reativação, mas sem atribuir uma
    # faixa incorreta. Receita continua informativa; percentuais ficam vazios
    # porque esses produtos não participam do denominador da curva.
    if bool(mascara_excluidos.any()):
        fora = (
            df.loc[mascara_excluidos]
            .groupby("descricao", as_index=False)["Receita"]
            .sum()
        )
        fora["Faixa"] = ""
        fora["Freq_Simples"] = None
        fora["Freq_Acumulado"] = None
        classificado_tabela = pd.concat([classificado, fora], ignore_index=True)
    else:
        classificado_tabela = classificado

    return {
        "corte_produtos": corte,
        "grupos": [
            {"nome": "Grupo 1 (alto giro)", "ate_percentual": corte,
             "quantidade": int(contagens.get("Grupo 1", 0))},
            {"nome": "Demais", "ate_percentual": None, "quantidade": int(contagens.get("Demais", 0))},
        ],
        "itens": _itens_produtos_previa(classificado_tabela),
        # Listas completas (sem teto da prévia) para toggles de exclusão em massa.
        "produtos_demais": demais.tolist(),
        "produtos_nao_harmonizados": [
            nome for nome in classificado_tabela["descricao"].astype(str).tolist()
            if _eh_produto_nao_harmonizado(nome)
        ],
    }


# ---------------------------------------------------------------------------
# Rotas de caminhos (fonte RO + trabalho RW) e config.json por empresa
# ---------------------------------------------------------------------------

class CaminhoPasta(BaseModel):
    caminho: str


# ---------------------------------------------------------------------------
# Navegador de pastas server-side
#
# O backend roda como serviço do Windows (NSSM/LocalSystem, sessão 0) e é
# acessado pelo navegador — possivelmente de outra máquina da rede. Diálogo
# nativo (tkinter/IFileDialog) não funciona nesse cenário: abriria numa área de
# trabalho invisível e travaria a requisição até o timeout do proxy. Em vez
# disso, o frontend navega pelo sistema de arquivos do servidor via listagem
# somente leitura.
# ---------------------------------------------------------------------------

def _raizes_sistema() -> list[str]:
    """Raízes navegáveis: letras de unidade no Windows, "/" no POSIX."""
    if sys.platform != "win32":
        return ["/"]
    raizes = []
    for letra in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        raiz = f"{letra}:\\"
        if os.path.isdir(raiz):
            raizes.append(raiz)
    return raizes


def _listar_pastas(caminho: Optional[str]) -> dict:
    """Lista subpastas de `caminho` (somente leitura, nunca escreve nada).

    Sem `caminho`, devolve as raízes do sistema. `pai` é None quando o caminho
    já é uma raiz (o frontend usa isso para voltar à lista de unidades).
    """
    bruto = (caminho or "").strip()
    if not bruto:
        return {
            "caminho": None,
            "pai": None,
            "pastas": [{"nome": r, "caminho": r} for r in _raizes_sistema()],
        }

    alvo = os.path.abspath(os.path.expandvars(bruto))
    if not os.path.isdir(alvo):
        raise HTTPException(status_code=404, detail=f"Pasta não encontrada: {alvo}")

    try:
        with os.scandir(alvo) as entradas:
            pastas = []
            for entrada in entradas:
                if entrada.name.startswith("."):
                    continue
                try:
                    if entrada.is_dir():
                        pastas.append({"nome": entrada.name, "caminho": entrada.path})
                except OSError:
                    continue  # link quebrado / sem permissão
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Sem permissão de leitura em {alvo}")
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler {alvo}: {exc}")

    pastas.sort(key=lambda p: p["nome"].casefold())
    pai = os.path.dirname(alvo)
    return {
        "caminho": alvo,
        "pai": None if pai == alvo else pai,
        "pastas": pastas,
    }

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


class AguardandoBaseDadosBody(BaseModel):
    aguardando: bool


@app.get("/api/config/aguardando-base-dados")
def obter_aguardando_base_dados(usuario: str = Depends(exigir_login)):
    return {"aguardando": db.obter_config_app(CHAVE_AGUARDANDO_BASE_DADOS, "0") == "1"}


@app.post("/api/config/aguardando-base-dados")
def definir_aguardando_base_dados(
    corpo: AguardandoBaseDadosBody, usuario: str = Depends(exigir_login),
):
    db.definir_config_app(CHAVE_AGUARDANDO_BASE_DADOS, "1" if corpo.aguardando else "0")
    return {"aguardando": corpo.aguardando}


@app.get("/api/config/listar-pastas")
def listar_pastas_config(
    caminho: Optional[str] = None, usuario: str = Depends(exigir_login),
):
    return _listar_pastas(caminho)


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
def salvar_configuracao_empresa(
    nome: str,
    corpo: ConfiguracaoEmpresa,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    nome = _validar_nome_empresa(nome)
    trabalho_root = _exigir_caminho_trabalho()
    pasta_empresa = os.path.join(trabalho_root, nome)
    _assert_escrita_fora_da_fonte(pasta_empresa)
    try:
        os.makedirs(pasta_empresa, exist_ok=True)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível criar a pasta da empresa: {exc}")
    dados = corpo.dados if isinstance(corpo.dados, dict) else {}
    caminho_arquivo = _gravar_config_escopo(nome, loja, dados)
    return {
        "ok": True,
        "caminho": caminho_arquivo,
        "loja": _chave_escopo_loja(loja) or None,
    }


@app.get("/api/empresas/{nome}/configuracao")
def carregar_configuracao_empresa(
    nome: str,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    nome = _validar_nome_empresa(nome)
    dados = _ler_config_escopo(nome, loja)
    if dados is None:
        # Ausência é estado inicial normal, não falha HTTP. Retornar null evita
        # ruído 404 no console e mantém o contrato opcional usado pelo frontend.
        return None
    return dados


class TagsClientesBody(BaseModel):
    tags: dict


class TagClienteBody(BaseModel):
    cliente: str
    tags: list[str]


class TagsCatalogoBody(BaseModel):
    catalogo: list


@app.get("/api/empresas/{nome}/clientes-tags")
def obter_tags_clientes(
    nome: str,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    return _ler_tags_clientes(nome, loja=loja)


@app.put("/api/empresas/{nome}/clientes-tags/catalogo")
def salvar_catalogo_tags(
    nome: str,
    corpo: TagsCatalogoBody,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    return _gravar_catalogo_tags(
        nome,
        corpo.catalogo if isinstance(corpo.catalogo, list) else [],
        loja=loja,
    )


class GruposManuaisBody(BaseModel):
    grupos: list


@app.put("/api/empresas/{nome}/clientes-grupos")
def salvar_grupos_manuais(
    nome: str,
    corpo: GruposManuaisBody,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Persiste grupos manuais de clientes (agregados no concentrado ABC)."""
    return _gravar_grupos_manuais(
        nome,
        corpo.grupos if isinstance(corpo.grupos, list) else [],
        loja=loja,
    )


@app.get("/api/clientes/buscar")
def buscar_clientes(
    q: str = "",
    empresa: Optional[str] = None,
    loja: Optional[str] = None,
    limite: int = 40,
    usuario: str = Depends(exigir_login),
):
    """Busca clientes na base bruta (sem agregar grupos manuais) para o criador de grupos."""
    df, _ = _carregar_base(empresa, loja=loja)
    if "Cliente" not in df.columns or df.empty:
        return {"itens": []}
    agregado = (
        df.groupby("Cliente", dropna=False, as_index=False)["Receita"]
        .sum()
        .sort_values("Receita", ascending=False)
    )
    termo = (q or "").strip().lower()
    if termo:
        nomes = agregado["Cliente"].astype(str)
        mascara = nomes.str.lower().str.contains(re.escape(termo), na=False)
        agregado = agregado[mascara]
    limite = max(1, min(int(limite or 40), 100))
    agregado = agregado.head(limite)
    receita = pd.to_numeric(agregado["Receita"], errors="coerce").fillna(0.0)
    return {
        "itens": [
            {"cliente": str(nome), "receita": float(rec)}
            for nome, rec in zip(agregado["Cliente"].tolist(), receita.tolist())
        ],
    }


@app.put("/api/empresas/{nome}/clientes-tags")
def salvar_tags_clientes(
    nome: str,
    corpo: TagsClientesBody,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    return _gravar_tags_clientes(
        nome,
        corpo.tags if isinstance(corpo.tags, dict) else {},
        loja=loja,
    )


@app.put("/api/empresas/{nome}/clientes-tags/cliente")
def salvar_tags_um_cliente(
    nome: str,
    corpo: TagClienteBody,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Atualiza as tags de um único cliente e sincroniza clientes_balcao."""
    atual = _ler_tags_clientes(nome, loja=loja)
    tags = dict(atual["tags"])
    cliente = corpo.cliente.strip()
    if not cliente:
        raise HTTPException(status_code=400, detail="Informe o nome do cliente.")
    ids_catalogo = _ids_do_catalogo(atual["catalogo"])
    limpas = [
        t for t in (str(x).strip().lower() for x in corpo.tags)
        if t in ids_catalogo
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
    return _gravar_tags_clientes(nome, tags, loja=loja)


@app.post("/api/empresas/{nome}/ensure-base")
def ensure_base_empresa(
    nome: str,
    forcar: bool = False,
    usuario: str = Depends(exigir_login),
):
    """Confirma que a fonte tem os dados da empresa (Analisador / dash).

    Não há mais Base.csv persistido — os dados são lidos direto da fonte a cada
    seleção. ``forcar=true`` limpa os caches e regenera o summary do zero
    (equivalente a Regenerar base).
    """
    if forcar:
        return _regenerar_base_empresa(nome)
    _pastas_empresa(nome)  # 404 se a empresa não tiver o XLSX na fonte
    return {"ok": True, "empresa": nome}


@app.post("/api/empresas/{nome}/regenerar-base")
def regenerar_base_empresa(nome: str, usuario: str = Depends(exigir_login)):
    """Limpa caches e força reprocessamento direto da fonte (Analisador)."""
    return _regenerar_base_empresa(nome)


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


@app.get("/api/dashboard/listar-pastas")
def listar_pastas_dashboard(caminho: Optional[str] = None):
    return _listar_pastas(caminho)


# Alias legado: caminho-dados do dash = fonte (somente leitura)
@app.get("/api/dashboard/caminho-dados")
def obter_caminho_dados_dashboard():
    return {"caminho": _resolver_caminho_fonte()}


@app.post("/api/dashboard/caminho-dados")
def definir_caminho_dados_dashboard(corpo: CaminhoPasta):
    return {"caminho": _salvar_caminho_fonte(corpo.caminho)}


@app.get("/api/dashboard/aguardando-base-dados")
def obter_aguardando_base_dados_dashboard():
    """Público — o Dashboard usa isso para mostrar o aviso de base em montagem."""
    return {"aguardando": db.obter_config_app(CHAVE_AGUARDANDO_BASE_DADOS, "0") == "1"}


@app.post("/api/dashboard/aguardando-base-dados")
def definir_aguardando_base_dados_dashboard(corpo: AguardandoBaseDadosBody):
    """Público — mesma flag do /api/config, sem exigir login (igual caminho-fonte/trabalho)."""
    db.definir_config_app(CHAVE_AGUARDANDO_BASE_DADOS, "1" if corpo.aguardando else "0")
    return {"aguardando": corpo.aguardando}


@app.get("/api/dashboard/empresas")
def listar_empresas_dashboard():
    return _listar_empresas_fonte()


# ---------------------------------------------------------------------------
# Monitoramento (visão de todas as empresas)
# ---------------------------------------------------------------------------

@app.get("/api/monitor/empresas")
def monitor_empresas(
    metrica: str = "receita",
    meses: int = 12,
    forcar: bool = False,
):
    """Uma linha por empresa com a série da métrica pedida e a variação anual.

    Responde SEMPRE 200 com o que conseguiu montar: uma empresa sem base (ou com
    summary corrompido) entra com `estado` próprio em vez de derrubar a tela toda —
    com 59 empresas, a chance de uma estar em manutenção é alta.
    """
    if metrica not in METRICAS_MONITOR:
        raise HTTPException(
            status_code=400,
            detail=f"Métrica inválida. Use uma de: {', '.join(METRICAS_MONITOR)}.",
        )
    meses = max(1, min(int(meses or 12), 60))

    trabalho_root = _exigir_caminho_trabalho()
    cards: list[dict] = []
    for empresa in _listar_empresas_fonte():
        pasta_trabalho = os.path.join(trabalho_root, empresa)
        try:
            resumo = obter_resumo_monitor(pasta_trabalho, forcar=forcar)
        except Exception:
            logger.error("Falha ao resumir %s para o monitor:\n%s", empresa, traceback.format_exc())
            cards.append({
                "empresa": empresa,
                "estado": "erro",
                "detalhe": "Não foi possível ler os dados desta empresa.",
            })
            continue

        if resumo is None:
            cards.append({
                "empresa": empresa,
                "estado": "sem_base",
                "detalhe": "Base ainda não gerada para esta empresa.",
            })
            continue

        cards.append(montar_card(empresa, resumo, metrica=metrica, meses=meses))

    # Favoritas vão na mesma resposta: a tela precisa das duas coisas para o
    # primeiro render, e duas requisições atrasariam o destaque das favoritas.
    return {
        "metrica": metrica,
        "meses": meses,
        "empresas": cards,
        "favoritas": _ler_favoritas(),
    }


def _ler_favoritas() -> list[str]:
    """Favoritas gravadas, já filtradas pelas empresas que ainda existem na fonte.

    Empresa removida da fonte não deve continuar aparecendo como favorita — mas
    também não apago a preferência: se a pasta voltar, o favorito volta com ela.
    """
    bruto = db.obter_config_app(CHAVE_EMPRESAS_FAVORITAS, "[]")
    try:
        salvas = json.loads(bruto or "[]")
    except json.JSONDecodeError:
        logger.warning("Favoritas com JSON inválido em config_app; tratando como vazio.")
        return []
    if not isinstance(salvas, list):
        return []
    existentes = set(_listar_empresas_fonte())
    return [nome for nome in salvas if isinstance(nome, str) and nome in existentes]


class FavoritasBody(BaseModel):
    empresas: list[str]


@app.get("/api/monitor/favoritas")
def obter_favoritas():
    return {"empresas": _ler_favoritas()}


@app.post("/api/monitor/favoritas")
def definir_favoritas(corpo: FavoritasBody):
    """Substitui a lista inteira (a tela manda o estado final, não um diff)."""
    existentes = set(_listar_empresas_fonte())
    # dedupe preservando a ordem em que o usuário favoritou
    limpas: list[str] = []
    for nome in corpo.empresas:
        nome = (nome or "").strip()
        if not nome or nome in limpas:
            continue
        if nome not in existentes:
            raise HTTPException(
                status_code=400,
                detail=f"Empresa '{nome}' não existe na pasta fonte.",
            )
        limpas.append(nome)

    db.definir_config_app(CHAVE_EMPRESAS_FAVORITAS, json.dumps(limpas, ensure_ascii=False))
    return {"empresas": limpas}


@app.post("/api/dashboard/empresas/{empresa}/regenerar-base")
def regenerar_base_dashboard(empresa: str):
    """Limpa caches e força reprocessamento direto da fonte (Dashboard público)."""
    return _regenerar_base_empresa(empresa)


@app.get("/api/dashboard/summary/{empresa}")
def obter_summary_dashboard(empresa: str):
    """Serve summary_dashboard.json(.gz) em disco/RAM. Regenera só se a fonte for mais nova."""
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_atacado, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    caminho_summary = _garantir_summary_dashboard_arquivo(
        empresa, pasta_fonte, pasta_trabalho, str(caminho_atacado),
    )
    return _resposta_summary_arquivo(empresa, caminho_summary, pasta_fonte, str(caminho_atacado))


# ---------------------------------------------------------------------------
# Exploração livre (gráficos / tabelas dinâmicas) — agregação no servidor
# ---------------------------------------------------------------------------

DIMENSOES_EXPLORAR = (
    "Loja", "NOME_FABRICANTE", "Cliente", "descricao",
    "Código Interno", "Código de referêcia",
    "Ano", "Mês",
    "Periodo_Mensal", "Periodo_Trimestral", "Periodo_Semestral", "Periodo_Anual",
)
METRICAS_EXPLORAR = ("Receita", "QTD", "Clientes")
LIMITE_EXPLORAR_MAX = 500


class ParametrosExplorar(BaseModel):
    empresa: Optional[str] = None
    loja: Optional[str] = None
    dimensoes: list[str] = []
    metricas: list[str] = ["Receita"]
    filtros: dict[str, list[str]] = {}
    aplicar_grupos: bool = True
    limite: int = 100
    ordenar_por: Optional[str] = None
    ordem: str = "desc"
    # agregar (padrão) | histograma | boxplot | dispersao
    modo_viz: str = "agregar"
    bins: int = 20
    #: Soma tudo o que ficou fora do top N numa linha "Outros" (só modo agregar).
    #: Sem isso o corte por `limite` some com o resto sem dizer quanto era.
    agrupar_resto: bool = False
    #: Repete a agregação para o ano anterior, gerando as colunas
    #: `<métrica>_Ano_Anterior` e `Variacao_Percentual`.
    comparar_ano_anterior: bool = False


#: Dimensões que já carregam o ano dentro do valor ("2026-03", "2026-T1", 2026).
#: Comparar ano anterior com elas no eixo não faz sentido: cada valor pertence a
#: um único ano, então as duas séries nunca cairiam na mesma categoria.
DIMENSOES_COM_ANO = ("Ano", "Periodo_Mensal", "Periodo_Trimestral", "Periodo_Semestral", "Periodo_Anual")

#: Rótulo da linha/série que soma o que ficou fora do top N.
ROTULO_RESTO = "Outros"

#: Sufixo das colunas do ano anterior.
SUFIXO_ANO_ANTERIOR = "_Ano_Anterior"


def _agregar_explorar(df: pd.DataFrame, dimensoes: list[str], agg: dict) -> pd.DataFrame:
    """groupby + agregações do explorador (ou uma linha só, sem dimensão)."""
    if dimensoes:
        return df.groupby(dimensoes, dropna=False).agg(**agg).reset_index()
    linha = {
        nome: float(df[src].sum()) if fn == "sum" else int(df[src].nunique())
        for nome, (src, fn) in agg.items()
    }
    return pd.DataFrame([linha])


def _linha_resto_explorar(
    resto: pd.DataFrame, dimensoes: list[str], metricas: list[str],
) -> dict:
    """Uma linha "Outros" com a soma do que foi cortado pelo top N.

    `Clientes` fica nulo de propósito: é contagem distinta, e somar os nunique de
    cada linha cortada contaria o mesmo cliente várias vezes. Melhor vazio do que
    um número inflado que ninguém consegue conferir.
    """
    linha: dict = {}
    for indice, dim in enumerate(dimensoes):
        linha[dim] = ROTULO_RESTO if indice == 0 else None
    for metrica in metricas:
        if metrica == "Clientes":
            linha[metrica] = None
        elif metrica in resto.columns:
            linha[metrica] = float(pd.to_numeric(resto[metrica], errors="coerce").fillna(0).sum())
    return linha


def _aplicar_filtros_explorar(df: pd.DataFrame, filtros: Optional[dict]) -> pd.DataFrame:
    for coluna, valores in (filtros or {}).items():
        if coluna not in df.columns or not valores:
            continue
        df = df[df[coluna].astype(str).isin([str(v) for v in valores])]
    return df


def _metrica_numerica_explorar(metricas: list[str]) -> str:
    for m in metricas:
        if m in ("Receita", "QTD"):
            return m
    raise HTTPException(
        status_code=400,
        detail="Histograma/boxplot/dispersão exigem métrica Receita ou QTD.",
    )


def _explorar_histograma(
    df: pd.DataFrame,
    metrica: str,
    bins: int,
    limite: int,
    dimensoes: Optional[list[str]] = None,
) -> dict:
    """Histograma da distribuição da métrica por entidade (em geral Cliente).

    Corrige a assimetria típica de vendas: ignora valores <= 0 (devoluções/
    zeros), corta outliers acima do P99 e usa bins em escala log quando a
    amplitude for grande — evita o efeito de "uma barra só".
    """
    entidade = "Cliente"
    if dimensoes:
        # Se a dimensão for uma entidade "fina", usa ela; períodos/ano viram
        # agrupamento fraco demais para histograma de distribuição.
        candidata = dimensoes[0]
        if candidata in ("Cliente", "Loja", "NOME_FABRICANTE", "descricao", "Código Interno"):
            entidade = candidata
    if entidade not in df.columns:
        if "Cliente" not in df.columns:
            raise HTTPException(status_code=400, detail="Base sem coluna adequada para histograma.")
        entidade = "Cliente"

    serie = df.groupby(entidade, dropna=False)[metrica].sum()
    serie = pd.to_numeric(serie, errors="coerce").dropna()
    # Devoluções geram QTD/Receita líquida <= 0; histograma de distribuição
    # de volume/receita positiva é o que o usuário espera ver.
    serie = serie[serie > 0]
    if serie.empty:
        return {
            "colunas": ["bin", "frequencia", "inicio", "fim", "centro", "faixa"],
            "linhas": [],
            "total_linhas": 0,
            "limite": limite,
            "dimensoes": ["bin"],
            "metricas": ["frequencia"],
            "modo_viz": "histograma",
        }

    valores = serie.to_numpy(dtype=float)
    n_bins = max(5, min(int(bins or 20), 60))
    p99 = float(np.quantile(valores, 0.99))
    vmin = float(valores.min())
    # Corta cauda extrema para as bordas dos bins (outliers vão no último bin).
    vmax = max(p99, vmin * 1.01)
    usar_log = vmax / max(vmin, 1e-9) >= 50 and vmin > 0

    if usar_log:
        edges = np.logspace(np.log10(vmin), np.log10(vmax), n_bins + 1)
    else:
        edges = np.linspace(vmin, vmax, n_bins + 1)

    # Inclui valores acima de vmax no último bin
    valores_clip = np.clip(valores, edges[0], edges[-1])
    counts, edges = np.histogram(valores_clip, bins=edges)

    def _fmt_eixo(v: float) -> str:
        """Rótulo curto para o eixo X (só a borda esquerda do bin)."""
        av = abs(v)
        if av >= 1_000_000:
            s = f"{v / 1_000_000:.1f}".rstrip("0").rstrip(".")
            return f"{s}M"
        if av >= 10_000:
            return f"{v / 1_000:.0f}k"
        if av >= 1_000:
            s = f"{v / 1_000:.1f}".rstrip("0").rstrip(".")
            return f"{s}k"
        if av >= 10:
            return f"{v:.0f}"
        if av >= 1:
            return f"{v:.1f}".rstrip("0").rstrip(".")
        return f"{v:.2f}".rstrip("0").rstrip(".")

    def _fmt_tooltip(v: float) -> str:
        if abs(v) >= 1000:
            return f"{v:,.0f}".replace(",", ".")
        if abs(v) >= 10:
            return f"{v:,.1f}".replace(",", ".")
        return f"{v:,.2f}".replace(",", ".")

    linhas = []
    for i, freq in enumerate(counts):
        inicio = float(edges[i])
        fim = float(edges[i + 1])
        centro = (inicio + fim) / 2 if not usar_log else float(np.sqrt(inicio * fim))
        if i == len(counts) - 1 and float(valores.max()) > vmax:
            rotulo = f"{_fmt_eixo(inicio)}+"
            faixa = f"{_fmt_tooltip(inicio)}+"
        else:
            rotulo = _fmt_eixo(inicio)
            faixa = f"{_fmt_tooltip(inicio)} – {_fmt_tooltip(fim)}"
        linhas.append([rotulo, int(freq), inicio, fim, centro, faixa])

    # Remove bins vazios nas pontas para não poluir o eixo (mantém internos).
    while len(linhas) > 1 and linhas[0][1] == 0:
        linhas.pop(0)
    while len(linhas) > 1 and linhas[-1][1] == 0:
        linhas.pop()

    return {
        "colunas": ["bin", "frequencia", "inicio", "fim", "centro", "faixa"],
        "linhas": linhas[:limite],
        "total_linhas": len(linhas),
        "limite": limite,
        "dimensoes": ["bin"],
        "metricas": ["frequencia"],
        "modo_viz": "histograma",
        "entidade": entidade,
        "observacoes": int(len(valores)),
        "escala": "log" if usar_log else "linear",
    }


def _explorar_boxplot(df: pd.DataFrame, dimensoes: list[str], metrica: str, limite: int) -> dict:
    """Boxplot: distribuição da métrica por entidade dentro de cada categoria (1ª dimensão)."""
    if not dimensoes:
        raise HTTPException(
            status_code=400,
            detail="Boxplot exige ao menos uma dimensão (categoria no eixo X).",
        )
    dim = dimensoes[0]
    entidade = "Cliente" if dim != "Cliente" else (
        "Periodo_Mensal" if "Periodo_Mensal" in df.columns else None
    )
    if entidade is None or entidade not in df.columns:
        raise HTTPException(status_code=400, detail="Não foi possível montar observações para o boxplot.")

    por_entidade = (
        df.groupby([dim, entidade], dropna=False)[metrica]
        .sum()
        .reset_index()
    )
    por_entidade[metrica] = pd.to_numeric(por_entidade[metrica], errors="coerce")
    por_entidade = por_entidade.dropna(subset=[metrica])

    if por_entidade.empty:
        return {
            "colunas": [dim, "min", "q1", "median", "q3", "max", "n"],
            "linhas": [],
            "total_linhas": 0,
            "limite": limite,
            "dimensoes": [dim],
            "metricas": [metrica],
            "modo_viz": "boxplot",
        }

    linhas_stats = []
    for nome, grupo in por_entidade.groupby(dim, dropna=False):
        serie = grupo[metrica]
        linhas_stats.append({
            dim: nome,
            "min": float(serie.min()),
            "q1": float(serie.quantile(0.25)),
            "median": float(serie.median()),
            "q3": float(serie.quantile(0.75)),
            "max": float(serie.max()),
            "n": int(serie.count()),
        })
    stats = pd.DataFrame(linhas_stats).sort_values("median", ascending=False)
    total = len(stats)
    stats = stats.head(limite)
    return {
        **_df_para_json(stats),
        "total_linhas": total,
        "limite": limite,
        "dimensoes": [dim],
        "metricas": [metrica],
        "modo_viz": "boxplot",
    }


def _explorar_dispersao(
    df: pd.DataFrame, dimensoes: list[str], metricas: list[str], limite: int,
) -> dict:
    """Dispersão: pontos por combinação de dimensões com eixos X/Y numéricos."""
    nums = [m for m in metricas if m in ("Receita", "QTD")]
    if not nums:
        raise HTTPException(status_code=400, detail="Dispersão exige Receita e/ou QTD.")

    if len(nums) >= 2:
        x_col, y_col = nums[0], nums[1]
    else:
        y_col = nums[0]
        x_col = "QTD" if y_col == "Receita" and "QTD" in df.columns else (
            "Receita" if y_col == "QTD" and "Receita" in df.columns else y_col
        )

    dims = [d for d in dimensoes if d in df.columns][:2]
    group_cols = dims if dims else (["Cliente"] if "Cliente" in df.columns else [])
    if not group_cols:
        raise HTTPException(status_code=400, detail="Dispersão precisa de dimensão ou Cliente.")

    if x_col == y_col:
        agrupado = df.groupby(group_cols, dropna=False).agg(**{x_col: (x_col, "sum")}).reset_index()
        agrupado["y"] = agrupado[x_col]
        y_out = "y"
    else:
        agrupado = df.groupby(group_cols, dropna=False).agg(
            **{x_col: (x_col, "sum"), y_col: (y_col, "sum")}
        ).reset_index()
        y_out = y_col

    agrupado = agrupado.sort_values(y_out, ascending=False)
    total = len(agrupado)
    agrupado = agrupado.head(limite)
    rotulo = agrupado[group_cols].astype(str).agg(" · ".join, axis=1)
    out = pd.DataFrame({
        "nome": rotulo,
        "x": pd.to_numeric(agrupado[x_col], errors="coerce").fillna(0.0),
        "y": pd.to_numeric(agrupado[y_out], errors="coerce").fillna(0.0),
    })
    return {
        **_df_para_json(out),
        "total_linhas": total,
        "limite": limite,
        "dimensoes": group_cols,
        "metricas": [x_col, y_col],
        "modo_viz": "dispersao",
        "eixos": {"x": x_col, "y": y_col},
    }


@app.get("/api/explorar/schema")
def explorar_schema(
    empresa: Optional[str] = None,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Colunas e métricas disponíveis para o builder livre."""
    df, _ = _carregar_base(empresa, loja=loja)
    dimensoes = [c for c in DIMENSOES_EXPLORAR if c in df.columns]
    return {
        "dimensoes": dimensoes,
        "metricas": list(METRICAS_EXPLORAR),
        "linhas": len(df),
        "empresa": empresa.strip() if empresa and empresa.strip() else None,
        "loja": _normalizar_loja(loja),
    }


@app.post("/api/explorar/agregar")
def explorar_agregar(parametros: ParametrosExplorar, usuario: str = Depends(exigir_login)):
    """Agrega a base sob demanda para gráficos/tabelas personalizados."""
    empresa = parametros.empresa.strip() if parametros.empresa and parametros.empresa.strip() else None
    df, _ = _carregar_base(empresa, loja=parametros.loja)
    if parametros.aplicar_grupos:
        df = af.aplicar_grupos_manuais_em_cliente(
            df, _grupos_manuais_empresa(empresa, loja=parametros.loja),
        )

    dimensoes = [d for d in parametros.dimensoes if d in DIMENSOES_EXPLORAR and d in df.columns]
    metricas = [m for m in parametros.metricas if m in METRICAS_EXPLORAR]
    if not metricas:
        raise HTTPException(status_code=400, detail="Selecione ao menos uma métrica (Receita, QTD ou Clientes).")
    if len(dimensoes) > 4:
        raise HTTPException(status_code=400, detail="No máximo 4 dimensões por consulta.")

    df = _aplicar_filtros_explorar(df, parametros.filtros)
    limite = max(1, min(int(parametros.limite or 100), LIMITE_EXPLORAR_MAX))
    modo = (parametros.modo_viz or "agregar").strip().lower()

    if df.empty:
        return {
            "colunas": dimensoes + metricas,
            "linhas": [],
            "total_linhas": 0,
            "limite": limite,
            "dimensoes": dimensoes,
            "metricas": metricas,
            "modo_viz": modo,
        }

    if modo == "histograma":
        return _explorar_histograma(
            df, _metrica_numerica_explorar(metricas), parametros.bins, limite, dimensoes,
        )
    if modo == "boxplot":
        return _explorar_boxplot(df, dimensoes, _metrica_numerica_explorar(metricas), limite)
    if modo == "dispersao":
        return _explorar_dispersao(df, dimensoes, metricas, limite)

    agg: dict = {}
    if "Receita" in metricas:
        agg["Receita"] = ("Receita", "sum")
    if "QTD" in metricas:
        agg["QTD"] = ("QTD", "sum")
    if "Clientes" in metricas:
        agg["Clientes"] = ("Cliente", "nunique")

    comparar = bool(parametros.comparar_ano_anterior)
    ano_atual = ano_anterior = None
    if comparar:
        if "Ano" not in df.columns:
            raise HTTPException(
                status_code=400,
                detail="A base não tem a coluna Ano — não é possível comparar com o ano anterior.",
            )
        conflito = [d for d in dimensoes if d in DIMENSOES_COM_ANO]
        if conflito:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{conflito[0]}' já separa os anos, então não há o que comparar. "
                    "Para comparar ano contra ano, use a dimensão 'Mês' (ou uma dimensão "
                    "não temporal, como Fabricante ou Cliente)."
                ),
            )
        anos = sorted({int(a) for a in pd.to_numeric(df["Ano"], errors="coerce").dropna().unique()})
        if len(anos) < 2:
            raise HTTPException(
                status_code=400,
                detail="A base só tem um ano de dados — não há ano anterior para comparar.",
            )
        ano_atual, ano_anterior = anos[-1], anos[-2]
        coluna_ano = pd.to_numeric(df["Ano"], errors="coerce")
        df_atual = df[coluna_ano == ano_atual]
        df_anterior = df[coluna_ano == ano_anterior]

        # YoY justo: o ano anterior entra SÓ com os meses que existem no ano
        # atual. Sem isso, um ano fechado (12 meses) é comparado com um ano em
        # curso (ex.: jan–ago) e o "ano anterior" aparece maior por ter 4 meses
        # extras — não por ter vendido mais. Foi exatamente o que apareceu ao
        # agregar por Fabricante: NGK "2025 = 1,14 M vs 2026 = 869 k".
        # A coluna canônica é "Mês" (ver RENOMEAR_COLUNAS em engine/analise_funil.py).
        if "Mês" in df.columns:
            meses_atual = {
                str(m).strip().lower() for m in df_atual["Mês"].dropna().unique()
            }
            if meses_atual:
                df_anterior = df_anterior[
                    df_anterior["Mês"].astype(str).str.strip().str.lower().isin(meses_atual)
                ]
                meses_ignorados = sorted(
                    {str(m).strip() for m in df["Mês"].dropna().unique()}
                    - {str(m).strip() for m in df_atual["Mês"].dropna().unique()}
                )
            else:
                meses_ignorados = []
        else:
            meses_ignorados = []
        agrupado = _agregar_explorar(df_atual, dimensoes, agg)
        anterior = _agregar_explorar(df_anterior, dimensoes, agg)
        renomear = {m: f"{m}{SUFIXO_ANO_ANTERIOR}" for m in metricas}
        anterior = anterior.rename(columns=renomear)
        if dimensoes:
            agrupado = agrupado.merge(anterior, on=dimensoes, how="outer")
        else:
            agrupado = pd.concat([agrupado, anterior], axis=1)
        for metrica in metricas:
            for coluna in (metrica, f"{metrica}{SUFIXO_ANO_ANTERIOR}"):
                if coluna in agrupado.columns:
                    agrupado[coluna] = pd.to_numeric(agrupado[coluna], errors="coerce").fillna(0)
        base_metrica = metricas[0]
        coluna_anterior = f"{base_metrica}{SUFIXO_ANO_ANTERIOR}"
        # Variação vazia quando não havia base no ano anterior: não existe
        # percentual de crescimento a partir de zero.
        agrupado["Variacao_Percentual"] = np.where(
            agrupado[coluna_anterior] > 0,
            (agrupado[base_metrica] - agrupado[coluna_anterior]) / agrupado[coluna_anterior] * 100,
            np.nan,
        )
    else:
        agrupado = _agregar_explorar(df, dimensoes, agg)

    ordenar = parametros.ordenar_por if parametros.ordenar_por in agrupado.columns else (
        metricas[0] if metricas[0] in agrupado.columns else None
    )
    if ordenar:
        ascending = str(parametros.ordem or "desc").lower() == "asc"
        agrupado = agrupado.sort_values(ordenar, ascending=ascending)

    total = len(agrupado)
    resto = agrupado.iloc[limite:]
    agrupado = agrupado.head(limite)

    colunas_numericas = list(metricas)
    if comparar:
        colunas_numericas += [f"{m}{SUFIXO_ANO_ANTERIOR}" for m in metricas]

    if parametros.agrupar_resto and dimensoes and not resto.empty:
        linha_resto = _linha_resto_explorar(resto, dimensoes, colunas_numericas)
        if comparar:
            atual = linha_resto.get(metricas[0]) or 0.0
            anterior_resto = linha_resto.get(f"{metricas[0]}{SUFIXO_ANO_ANTERIOR}") or 0.0
            linha_resto["Variacao_Percentual"] = (
                (atual - anterior_resto) / anterior_resto * 100 if anterior_resto > 0 else None
            )
        agrupado = pd.concat([agrupado, pd.DataFrame([linha_resto])], ignore_index=True)

    for col in colunas_numericas:
        if col not in agrupado.columns:
            continue
        if col == "Clientes":
            # Mantém nulo na linha "Outros" (ver _linha_resto_explorar).
            agrupado[col] = pd.to_numeric(agrupado[col], errors="coerce").astype("Int64")
        else:
            agrupado[col] = pd.to_numeric(agrupado[col], errors="coerce").fillna(0.0)

    resposta = {
        **_df_para_json(agrupado),
        "total_linhas": total,
        "limite": limite,
        "dimensoes": dimensoes,
        "metricas": metricas,
        "modo_viz": "agregar",
        "resto_agrupado": bool(parametros.agrupar_resto and dimensoes and not resto.empty),
    }
    if comparar:
        resposta["comparacao"] = {
            "ano_atual": ano_atual,
            "ano_anterior": ano_anterior,
            # Meses que existem só no ano anterior e ficaram FORA da comparação
            # (o ano atual ainda não chegou neles). A tela avisa o usuário.
            "meses_ignorados": meses_ignorados,
        }
    return resposta


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
    # False = erosão/correlação/churn olham a base inteira (mantém a Receita
    # Sob Risco comparável entre períodos). True = só os produtos em alerta.
    erosao_somente_produtos_em_alerta: bool = False
    nome_empresa: str = ""
    nome_usuario: str = ""
    empresa: Optional[str] = None
    loja: Optional[str] = None


# O resultado recém-calculado pode ser reaproveitado pela exportação. Guardamos
# apenas uma análise, por pouco tempo e com teto de memória: o objetivo é evitar
# o segundo cálculo imediato sem transformar o processo num depósito de bases.
_CACHE_RESULTADO_ANALISE_TTL_S = 10 * 60
_CACHE_RESULTADO_ANALISE_MAX_BYTES = 256 * 1024 * 1024
_CACHE_RESULTADO_ANALISE_MAX_ENTRADAS = 4
_cache_resultado_analise: OrderedDict[str, dict] = OrderedDict()
_cache_resultado_analise_lock = threading.Lock()


def _dados_parametros_analise(parametros: ParametrosAnalise) -> dict:
    """Converte o modelo Pydantic 1/2 para dados simples e comparáveis."""
    if hasattr(parametros, "model_dump"):
        return parametros.model_dump()
    return parametros.dict()


def _assinatura_parametros_analise(parametros: ParametrosAnalise) -> str:
    """Assinatura do cálculo, sem campos que só mudam apresentação/exportação."""
    dados = _dados_parametros_analise(parametros)
    for campo in ("chaves_selecionadas", "nome_empresa", "nome_usuario"):
        dados.pop(campo, None)
    return json.dumps(dados, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _tamanho_resultados_analise(resultados: dict) -> int:
    """Estima memória profunda dos DataFrames antes de admitir o cache."""
    total = 0
    for analises in resultados.values():
        for dataframe in analises.values():
            if isinstance(dataframe, pd.DataFrame):
                total += int(dataframe.memory_usage(index=True, deep=True).sum())
    return total


def _expurgar_cache_resultado_analise(agora: Optional[float] = None) -> None:
    """Remove entradas vencidas. Deve ser chamado com o lock já adquirido."""
    instante = time.monotonic() if agora is None else agora
    vencidos = [
        token for token, entrada in _cache_resultado_analise.items()
        if instante - entrada["criado_em"] > _CACHE_RESULTADO_ANALISE_TTL_S
    ]
    for token in vencidos:
        _cache_resultado_analise.pop(token, None)


def _limitar_cache_resultado_analise() -> None:
    """Aplica limites globais de quantidade e memória; remove LRU primeiro."""
    total_bytes = sum(
        int(entrada.get("tamanho_bytes", 0))
        for entrada in _cache_resultado_analise.values()
    )
    while _cache_resultado_analise and (
        len(_cache_resultado_analise) > _CACHE_RESULTADO_ANALISE_MAX_ENTRADAS
        or total_bytes > _CACHE_RESULTADO_ANALISE_MAX_BYTES
    ):
        _token, removida = _cache_resultado_analise.popitem(last=False)
        total_bytes -= int(removida.get("tamanho_bytes", 0))


def _guardar_resultado_analise(
    usuario: str, parametros: ParametrosAnalise, resultados: dict,
) -> Optional[str]:
    """Guarda a análise recém-gerada e devolve token opaco para a exportação."""
    tamanho_bytes = _tamanho_resultados_analise(resultados)
    if tamanho_bytes > _CACHE_RESULTADO_ANALISE_MAX_BYTES:
        logger.info(
            "Resultado de %s não cacheado: %.1f MB excedem o teto de %.1f MB.",
            usuario, tamanho_bytes / 1024 / 1024,
            _CACHE_RESULTADO_ANALISE_MAX_BYTES / 1024 / 1024,
        )
        return None

    token = secrets.token_urlsafe(24)
    entrada = {
        "usuario": usuario,
        "assinatura": _assinatura_parametros_analise(parametros),
        "chaves": frozenset(parametros.chaves_selecionadas or []),
        "resultados": resultados,
        "criado_em": time.monotonic(),
        "tamanho_bytes": tamanho_bytes,
    }
    with _cache_resultado_analise_lock:
        _expurgar_cache_resultado_analise(entrada["criado_em"])
        _cache_resultado_analise[token] = entrada
        # Várias exportações/usuários recentes podem coexistir, mas nunca acima
        # do teto global. Evita recalcular ao alternar entre relatórios.
        _limitar_cache_resultado_analise()
    return token


def _filtrar_resultados_cache(resultados: dict, chaves_solicitadas: set[str]) -> dict:
    """Replica o recorte de _rodar_analises sem copiar os DataFrames."""
    chaves_resultado = set(chaves_solicitadas)
    if "migracao_abc" in chaves_solicitadas:
        chaves_resultado.update({"migracao_resumo", "migracao_score_clientes"})
    if "liquidez" in chaves_solicitadas:
        chaves_resultado.update({"liquidez_estoque", "liquidez_vendas"})

    return {
        granularidade: {
            chave: dataframe
            for chave, dataframe in analises.items()
            if chave in chaves_resultado
        }
        for granularidade, analises in resultados.items()
        if any(chave in chaves_resultado for chave in analises)
    }


def _obter_resultado_analise(
    token: Optional[str], usuario: str, parametros: ParametrosAnalise,
) -> Optional[dict]:
    """Valida dono, prazo, parâmetros e subconjunto antes de reutilizar dados."""
    if not token:
        return None
    agora = time.monotonic()
    with _cache_resultado_analise_lock:
        _expurgar_cache_resultado_analise(agora)
        entrada = _cache_resultado_analise.get(token)
        if entrada is None:
            return None
        if entrada["usuario"] != usuario:
            return None
        if entrada["assinatura"] != _assinatura_parametros_analise(parametros):
            return None
        solicitadas = set(parametros.chaves_selecionadas or [])
        if not solicitadas:
            return None
        if not solicitadas.issubset(entrada["chaves"]):
            return None
        _cache_resultado_analise.move_to_end(token)
        resultados = entrada["resultados"]
    return _filtrar_resultados_cache(resultados, solicitadas)


def _carregar_df_filtrado(
    produtos_excluidos: list[str],
    empresa: Optional[str] = None,
    loja: Optional[str] = None,
) -> pd.DataFrame:
    # Motor somente lê o DataFrame; compartilha master cacheado. Quando há
    # exclusão, o filtro já materializa DataFrame separado.
    df, _ = _carregar_base(empresa, loja=loja, copiar=False)
    if produtos_excluidos:
        df = df.loc[~df["descricao"].isin(produtos_excluidos)].copy()
    return df


CHAVES_ALVOS = frozenset({"mais_atacado", "liquidez"})


def _filtrar_loja_coluna(
    df: pd.DataFrame, loja: Optional[str], coluna: str, origem: str,
) -> pd.DataFrame:
    """Filtra `df` por `coluna` == loja. loja vazia/None = todas (sem filtro).

    Usado nos Alvos, que leem arquivos próprios da fonte (nomes de coluna de loja
    diferentes do schema canônico: `Loja` no estoque, `Nome_Loja` nas vendas).
    """
    nome = _normalizar_loja(loja)
    if not nome:
        return df
    if df is None or df.empty or coluna not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"{origem} não tem a coluna '{coluna}' para filtrar por loja.",
        )
    filtrado = df.loc[df[coluna].fillna("").astype(str).str.strip() == nome].copy()
    if filtrado.empty:
        raise HTTPException(
            status_code=400,
            detail=f"Loja '{nome}' não encontrada em {origem}.",
        )
    return filtrado


def _analises_alvos(
    empresa: Optional[str], chaves: set[str], loja: Optional[str] = None,
) -> dict[str, pd.DataFrame]:
    """Gera os DataFrames da seção Alvos direto da fonte, em memória (sem CSV em disco).

    `loja` restringe os três arquivos ao escopo selecionado, igual ao resto do
    Analisador — sem isso os relatórios Alvos mostrariam todas as lojas.
    """
    if not empresa:
        raise HTTPException(
            status_code=400,
            detail="Selecione uma empresa para gerar os relatórios Alvos (Mais Atacado / Liquidez).",
        )
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_atacado, caminho_estoque, caminho_vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    analises: dict[str, pd.DataFrame] = {}

    if "mais_atacado" in chaves:
        # Reutiliza XLSX já validado e normalizado no cache; antes esta análise
        # relia dezenas de MB mesmo após Dashboard/Analisador carregarem a base.
        df, _linhas_vazias = _carregar_base_empresa(empresa)
        df = _filtrar_loja_coluna(df, loja, "Loja", "Dados Mais Atacado.xlsx")
        colunas_origem = [
            "Loja", "NOME_FABRICANTE", "Cliente", "descricao", "Ano", "Mês",
            "Código Interno", "Código de referêcia", "Receita Acumulada 11 Meses", "QTD",
        ]
        analises["mais_atacado"] = df.loc[:, [c for c in colunas_origem if c in df.columns]].copy()

    if "liquidez" in chaves:
        if caminho_estoque is None or caminho_vendas is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Liquidez exige Dados_Estoque_{Path(pasta_fonte).name}.* "
                    f"e Dados_Vendas_{Path(pasta_fonte).name}.* na pasta fonte."
                ),
            )
        estoque = normalizar_estoque(caminho_estoque)
        estoque = _filtrar_loja_coluna(estoque, loja, "Loja", caminho_estoque.name)
        for col in ("Qtd_estoque", "Preço_médio_de_venda", "Preço_médio_cmv", "Último_custo"):
            if col in estoque.columns:
                estoque[col] = parse_numero_flexivel(estoque[col])
        vendas = normalizar_vendas(caminho_vendas)
        vendas = _filtrar_loja_coluna(vendas, loja, "Nome_Loja", caminho_vendas.name)
        if "QTD" in vendas.columns:
            vendas["QTD"] = parse_numero_flexivel(vendas["QTD"])
        analises["liquidez_estoque"] = estoque
        analises["liquidez_vendas"] = vendas

    return analises


def _rodar_analises(parametros: ParametrosAnalise) -> dict:
    empresa = parametros.empresa.strip() if parametros.empresa and parametros.empresa.strip() else None
    chaves = set(parametros.chaves_selecionadas or [])
    chaves_alvos = chaves & CHAVES_ALVOS
    chaves_motor = chaves - CHAVES_ALVOS

    resultados: dict = {}

    if chaves_motor:
        df_filtrado = _carregar_df_filtrado(
            parametros.produtos_excluidos, empresa, loja=parametros.loja,
        )
        if df_filtrado.empty:
            raise HTTPException(
                status_code=400,
                detail="Nenhuma linha restante após excluir os produtos desmarcados.",
            )
        resultados = af.gerar_analises_completas(
            df_filtrado,
            parametros.granularidades,
            clientes_excluidos=parametros.clientes_excluidos,
            cortes_clientes=parametros.cortes_clientes,
            corte_produtos=parametros.corte_produtos,
            periodos_queda_consecutiva=parametros.periodos_queda_consecutiva,
            chaves_solicitadas=chaves_motor,
            desconsiderar_balcao=parametros.desconsiderar_balcao,
            excluir_periodo_atual=parametros.excluir_periodo_atual,
            top_n_produtos=parametros.top_n_produtos,
            reducao_minima_erosao=parametros.reducao_minima_erosao,
            queda_minima_alerta_rs=parametros.queda_minima_alerta_rs,
            queda_minima_erosao_rs=parametros.queda_minima_erosao_rs,
            reducao_minima_sem_venda=parametros.reducao_minima_sem_venda,
            top_n_poder_compra=parametros.top_n_poder_compra,
            erosao_somente_produtos_em_alerta=parametros.erosao_somente_produtos_em_alerta,
            clientes_balcao_extra=_clientes_balcao_extra(empresa, loja=parametros.loja),
            grupos_manuais=_grupos_manuais_empresa(empresa, loja=parametros.loja),
        )

    if chaves_alvos:
        resultados["Alvos"] = _analises_alvos(empresa, chaves_alvos, loja=parametros.loja)

    if not resultados:
        raise HTTPException(status_code=400, detail="Nenhum relatório selecionado.")

    return resultados


def _df_para_json(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {"colunas": [], "linhas": []}
    df_normalizado = df.reset_index() if df.index.name or isinstance(df.index, pd.MultiIndex) else df
    return {
        "colunas": [str(c) for c in df_normalizado.columns],
        "linhas": df_normalizado.astype(object).where(pd.notnull(df_normalizado), None).values.tolist(),
    }


@app.post("/api/analisar")
def analisar(
    parametros: ParametrosAnalise,
    response: Response,
    usuario: str = Depends(exigir_login),
):
    inicio = time.perf_counter()
    try:
        resultados = _rodar_analises(parametros)
    except HTTPException:
        raise
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao analisar dados de %s:\n%s", usuario, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao gerar as análises: {exc}")
    resultado_id = _guardar_resultado_analise(usuario, parametros, resultados)
    if resultado_id:
        response.headers["X-Resultado-Analise"] = resultado_id
    logger.info(
        "Análise concluída para %s em %.2fs; cache=%s.",
        usuario, time.perf_counter() - inicio, "armazenado" if resultado_id else "ignorado",
    )
    return {
        granularidade: {chave: _df_para_json(df_analise) for chave, df_analise in analises.items()}
        for granularidade, analises in resultados.items()
    }


# ---------------------------------------------------------------------------
# Exportação
# ---------------------------------------------------------------------------

@app.post("/api/exportar/{formato}")
def exportar(
    formato: str,
    parametros: ParametrosAnalise,
    usuario: str = Depends(exigir_login),
    resultado_id: Optional[str] = Header(None, alias="X-Resultado-Analise"),
):
    if formato not in ("excel", "pdf", "html"):
        raise HTTPException(status_code=400, detail="Formato inválido. Use 'excel', 'pdf' ou 'html'.")

    inicio = time.perf_counter()
    resultados = _obter_resultado_analise(resultado_id, usuario, parametros)
    cache_hit = resultados is not None
    try:
        if resultados is None:
            resultados = _rodar_analises(parametros)
    except HTTPException:
        raise
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao exportar dados de %s:\n%s", usuario, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao gerar as análises: {exc}")

    extensao = {"excel": ".xlsx", "pdf": ".pdf", "html": ".html"}[formato]
    arquivo_temp = tempfile.NamedTemporaryFile(delete=False, suffix=extensao)
    caminho_saida = arquivo_temp.name
    arquivo_temp.close()

    if formato == "excel":
        exportar_relatorio_excel(
            caminho_saida, resultados, nome_usuario=parametros.nome_usuario, nome_empresa=parametros.nome_empresa,
        )
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        nome_arquivo = "relatorio.xlsx"
    elif formato == "html":
        exportar_relatorio_html(
            caminho_saida, resultados, nome_usuario=parametros.nome_usuario,
            nome_empresa=parametros.nome_empresa,
            colunas_moeda_por_analise=COLUNAS_MOEDA_POR_ANALISE,
        )
        media_type = "text/html; charset=utf-8"
        nome_arquivo = "relatorio.html"
    else:
        exportar_relatorio_pdf(
            caminho_saida, resultados, NOMES_ANALISE, nome_usuario=parametros.nome_usuario,
            colunas_moeda_por_analise=COLUNAS_MOEDA_POR_ANALISE, nome_empresa=parametros.nome_empresa,
        )
        media_type = "application/pdf"
        nome_arquivo = "relatorio.pdf"

    logger.info(
        "Exportação %s concluída para %s em %.2fs; cache=%s.",
        formato, usuario, time.perf_counter() - inicio, "HIT" if cache_hit else "MISS",
    )
    return FileResponse(
        caminho_saida, media_type=media_type, filename=nome_arquivo,
        background=BackgroundTask(os.remove, caminho_saida),
        headers={"X-Resultado-Cache": "HIT" if cache_hit else "MISS"},
    )
