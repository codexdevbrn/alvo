"""
Backend do Analisador de Monitoria (versão web) — reaproveita o motor
analise_funil.py do app desktop original via FastAPI.
"""

import json
import gzip
import logging
import os
import re
import secrets
import shutil
import subprocess
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
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
from starlette.background import BackgroundTask

import atualizacoes
import caminhos_padrao
import chat_ia as chat_carteira
import dados_no_disco
import db
import inicio_automatico
import harmonizar_clientes
import base_duckdb
import cache_telas
import consulta_parquet
import margem_price as mgp
import a_precificar
import historico_precificacao as hist_prec
import versao
from alertas_clientes import avaliar_alertas_clientes, normalizar_regras_alerta
from auth import criar_token, exigir_login
from dashboard_summary import (
    aplicar_cortes_no_summary,
    caminho_summary_dashboard,
    caminho_summary_dashboard_gz,
    gerar_e_gravar_summary_dashboard,
    invalidar_summary_dashboard,
    summary_dashboard_atualizado,
)
from engine import analise_funil as af
from engine.recursos import pasta_base_execucao, pasta_web
from engine.exportadores_pdf_word import exportar_relatorio_pdf
from exportar_html import exportar_relatorio_html
from monitor_empresas import (
    METRICAS_COM_CMV,
    METRICAS_VALIDAS,
    montar_card,
    obter_resumo_monitor,
)
from relatorio_cliente import (
    ErroPainelCliente,
    gerar_painel_cliente_pdf,
    montar_dados_painel_cliente,
)
from exportar_excel import (
    CATALOGO_RELATORIOS,
    COLUNAS_MOEDA_POR_ANALISE,
    NOMES_ANALISE,
    exportar_relatorio_excel,
)

# Raiz do projeto, um nível acima de backend/. base_de_dados.xlsx e os
# scripts generalistas de normalização (normalizar_base.py, normalizar_liquidez.py)
# ficam lá.
#
# Congelado, `__file__` aponta para dentro do bundle (`_internal/`), que é
# somente leitura e é substituído a cada atualização — não serve para achar
# dados. `pasta_base_execucao()` devolve a pasta do executável, onde
# base_de_dados.xlsx e base-clientes/ ficam ao lado dele, sobrevivendo aos
# updates. Os módulos de normalização vêm embutidos, então o sys.path só
# precisa de ajuste rodando do fonte.
if getattr(sys, "frozen", False):
    RAIZ_PROJETO = pasta_base_execucao()
else:
    RAIZ_PROJETO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if RAIZ_PROJETO not in sys.path:
        sys.path.insert(0, RAIZ_PROJETO)

from normalizar_base import (  # noqa: E402
    ErroNormalizacao,
    parse_numero_flexivel,
    resolver_arquivos_dados,
    resolver_caminho_controladoria,
    resolver_caminho_precificacao,
)
from normalizar_liquidez import normalizar_estoque, normalizar_vendas  # noqa: E402
from analise_vendedores import (  # noqa: E402
    ErroFichaVendedor,
    coluna_vendedor_preenchida,
    montar_ficha_vendedor,
    montar_ranking_vendedores,
    preencher_vendedores_demo,
)
from analise_clientes import causa_migracao_cliente, montar_painel_clientes, top_produtos_potencial_cliente  # noqa: E402
from painel_diagnostico import montar_painel_diagnostico  # noqa: E402
from estoque_cobertura import montar_cobertura_estoque, montar_resumo_estoque  # noqa: E402
from despesas import montar_detalhe_despesas, montar_resumo_despesas  # noqa: E402
from precificacao import (  # noqa: E402
    filtrar_rodada,
    listar_rodadas_dump,
    montar_pos_precificacao,
)

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
    # Consulta o canal de atualização já no boot, em thread separada, para o
    # indicador da sidebar aparecer sem o usuário precisar abrir Configurações.
    # Em background porque o canal é pasta de rede: esperar por ele aqui atrasaria
    # o servidor a ficar de pé.
    atualizacoes.aquecer_em_background(_resolver_caminho_atualizacoes())
    # E segue verificando a cada 6h: o app agora fica dias no ar sem ninguém
    # navegar, e a verificação por navegação sozinha deixaria máquinas para trás.
    atualizacoes.iniciar_verificacao_periodica(_resolver_caminho_atualizacoes)


# ---------------------------------------------------------------------------
# Versão
# ---------------------------------------------------------------------------

@app.get("/api/versao")
def obter_versao():
    """Versão em execução. Sem login: o Dashboard é público e a versão é o
    primeiro dado que suporte pede quando alguém reporta um problema."""
    return {"versao": versao.VERSAO, "app": versao.IDENTIFICADOR_APP}


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
# Assistente IA da carteira
# ---------------------------------------------------------------------------

CHAT_REQUISICOES_POR_MINUTO = 8
_chat_rate_lock = threading.Lock()
_chat_rate: dict[str, list[float]] = {}


class ChatMensagemBody(BaseModel):
    role: str
    content: str


class ChatEmpresaBody(BaseModel):
    empresa: str
    mensagens: list[ChatMensagemBody]


def _limitar_chat(chave: str) -> None:
    """Rate limit em memória; protege custo sem persistir conteúdo da conversa."""
    agora = time.monotonic()
    inicio = agora - 60.0
    with _chat_rate_lock:
        recentes = [instante for instante in _chat_rate.get(chave, []) if instante >= inicio]
        if len(recentes) >= CHAT_REQUISICOES_POR_MINUTO:
            raise HTTPException(
                status_code=429,
                detail="Muitas perguntas em pouco tempo. Aguarde um minuto e tente novamente.",
            )
        recentes.append(agora)
        _chat_rate[chave] = recentes


def _contexto_chat_empresa(empresa: str) -> chat_carteira.ContextoEmpresa:
    database = caminhos_padrao.database_carteira()
    dossie = caminhos_padrao.dossie_carteira()
    if not database or not dossie:
        raise chat_carteira.ErroChatIA(
            "carteira_nao_configurada",
            "Database ou pasta de dossiês da carteira não está disponível.",
        )
    # Pasta de trabalho entra como opcional: sem ela o chat segue só com os MDs.
    return chat_carteira.carregar_contexto_empresa(
        empresa,
        database=database,
        dossie=dossie,
        trabalho=_resolver_caminho_trabalho(),
    )


def _erro_http_chat(exc: chat_carteira.ErroChatIA) -> HTTPException:
    if exc.codigo in {"empresa_ausente", "mensagem_invalida", "mensagem_vazia", "pergunta_ausente", "pergunta_extensa", "historico_extenso"}:
        status = 400
    elif exc.codigo in {"empresa_sem_dossie"}:
        status = 404
    elif exc.codigo in {"crm_md_ausente", "analise_md_ausente", "analise_indisponivel"}:
        status = 409
    elif exc.codigo.startswith("ollama_"):
        status = 503 if "key" in exc.codigo else 502
    else:
        status = 422
    return HTTPException(status_code=status, detail=str(exc))


@app.get("/api/ia/contexto")
def obter_contexto_chat_empresa(
    empresa: str,
    _usuario: str = Depends(exigir_login),
):
    """Informa presença/atualização dos MDs, sem devolver seu conteúdo."""
    try:
        return chat_carteira.status_contexto(_contexto_chat_empresa(empresa))
    except chat_carteira.ErroChatIA as exc:
        raise _erro_http_chat(exc) from exc


@app.post("/api/ia/chat")
def conversar_com_empresa(
    corpo: ChatEmpresaBody,
    request: Request,
    usuario: str = Depends(exigir_login),
):
    """Conversa sobre os MDs; não grava histórico nem devolve os documentos."""
    host = request.client.host if request.client else "sem-host"
    _limitar_chat(f"{usuario}:{host}")
    try:
        contexto = _contexto_chat_empresa(corpo.empresa)
        chave = chat_carteira.carregar_api_key_ollama()
        resposta = chat_carteira.responder_chat(
            contexto,
            [mensagem.model_dump() for mensagem in corpo.mensagens],
            chave,
        )
        return {
            "resposta": resposta,
            "empresa": contexto.empresa_carteira,
            "client_id": contexto.client_id,
            "modelo": chat_carteira.MODELO_OLLAMA,
        }
    except chat_carteira.ErroChatIA as exc:
        logger.warning("Chat IA falhou usuario=%s codigo=%s", usuario, exc.codigo)
        raise _erro_http_chat(exc) from exc


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
# caminho_fonte_dados  — somente leitura: /{empresa}/{empresa}_MOVIMENTO_ATUAL
#                         + /{empresa}/{empresa}_PRODUTO (parquet)
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
#: Pasta compartilhada (OneDrive da empresa) com version.json + o pacote da
#: release. Somente leitura, como a fonte de dados: o app consome o canal, quem
#: publica é o build. Configurável em vez de fixa porque o caminho local do
#: OneDrive muda de máquina para máquina.
CHAVE_CAMINHO_ATUALIZACOES = "caminho_atualizacoes"
#: "1" = esta instalação pode regenerar bases na pasta de trabalho.
#:
#: Existe porque a pasta de trabalho é compartilhada e, com o app distribuído como
#: executável, várias máquinas passam a poder escrever nela. Duas regenerando a
#: mesma empresa ao mesmo tempo não dá erro: o OneDrive resolve criando cópia de
#: conflito, em silêncio, e alguém depois lê o arquivo errado. A pré-geração é
#: tarefa do lote noturno; as demais máquinas só leem.
#:
#: É guarda contra acidente, não controle de acesso — quem tem a tela pode ligar.
CHAVE_REGENERACAO_PERMITIDA = "regeneracao_permitida"
#: "1" = Dashboard, Clientes, Vendedores e Estoque usam os cortes do Relatórios
#: (config.json do escopo: exclusões e regras de cliente/produto).
CHAVE_APLICAR_CORTES_RELATORIOS = "aplicar_cortes_relatorios"
# Legadas — só leitura de fallback / aliases de rota
CHAVE_CAMINHO_DADOS_DASHBOARD = "caminho_dados_dashboard"
CHAVE_CAMINHO_EMPRESAS = "caminho_empresas"

NOME_PASTA_INVALIDO = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
CAMINHO_BASE_CLIENTES_PADRAO = os.path.join(RAIZ_PROJETO, "base-clientes")
NOME_ARQUIVO_TAGS_CLIENTES = "clientes_tags.json"
NOME_ARQUIVO_CONFIG = "config.json"
CAMINHO_BANCO_CENTRALIZADO_TAGS = r"C:\Users\bi_2d_gzgh6n0\OneDrive - 2dconsultores.com.br\01 - Marco + Monitores\Ecossistema-Monitoria\Bancos\tags.json"
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
_CAMPOS_TAGS_FLAT = frozenset({
    "tags", "catalogo", "grupos", "clientes_balcao", "regras_alerta",
})

TAGS_CATALOGO_PADRAO: list[dict] = [
    {"id": "alerta", "rotulo": "Alerta", "ativa": True, "entra_na_analise": True, "cor": "#ec1818"},
    {"id": "inadimplente", "rotulo": "Inadimplente", "ativa": True, "entra_na_analise": True, "cor": "#f43f5e"},
    {"id": "cliente_balcao", "rotulo": "Cliente Balcão", "ativa": True, "entra_na_analise": True, "cor": "#f59e0b"},
    {"id": "encerrou_operacao", "rotulo": "Encerrou operação", "ativa": True, "entra_na_analise": True, "cor": "#64748b"},
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
    chaves: tuple[str, ...],
    *,
    usar_padrao_base_clientes: bool = False,
    padrao_onedrive=None,
) -> Optional[str]:
    """Primeiro caminho configurado que existe como pasta; senão o padrão; senão
    o valor bruto configurado.

    `padrao_onedrive` é a função de `caminhos_padrao` correspondente. Ela entra
    antes do fallback `base-clientes/` porque é o lugar real dos dados: uma
    instalação nova precisa funcionar sem ninguém digitar caminho, e a pasta do
    OneDrive corporativo é a mesma em toda máquina da empresa (só a raiz local
    muda, e ela é resolvida em tempo de execução).

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
    if padrao_onedrive is not None:
        # A função só devolve pasta que existe, então não há risco de apontar o
        # app para um caminho inválido.
        padrao = padrao_onedrive()
        if padrao:
            return padrao
    if usar_padrao_base_clientes and os.path.isdir(CAMINHO_BASE_CLIENTES_PADRAO):
        return CAMINHO_BASE_CLIENTES_PADRAO
    return ultimo


def _resolver_caminho_fonte() -> Optional[str]:
    return _resolver_config_dir(
        (CHAVE_CAMINHO_FONTE_DADOS, CHAVE_CAMINHO_DADOS_DASHBOARD),
        usar_padrao_base_clientes=True,
        padrao_onedrive=caminhos_padrao.fonte_dados,
    )


def _resolver_caminho_trabalho() -> Optional[str]:
    return _resolver_config_dir(
        (CHAVE_CAMINHO_TRABALHO, CHAVE_CAMINHO_EMPRESAS),
        usar_padrao_base_clientes=False,
        padrao_onedrive=caminhos_padrao.trabalho,
    )


def _resolver_caminho_atualizacoes() -> Optional[str]:
    """Canal de atualização: o configurado, senão o padrão do OneDrive.

    Diferente dos outros dois, aceita ficar vazio de propósito — canal em branco
    é como se desliga a verificação de atualizações. Por isso o valor salvo vazio
    NÃO cai no padrão: se o usuário limpou o campo, foi porque quis.
    """
    salvo = db.obter_config_app(CHAVE_CAMINHO_ATUALIZACOES)
    if salvo is not None:
        return salvo
    return caminhos_padrao.atualizacoes()


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
    """Lista subpastas com MOVIMENTO_ATUAL + PRODUTO (parquet) diretamente dentro, somente leitura."""
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
    return _normalizar_loja(loja) or ""


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


def _ler_catalogo_centralizado() -> list[dict]:
    if not os.path.isfile(CAMINHO_BANCO_CENTRALIZADO_TAGS):
        return _garantir_tag_alerta([dict(item) for item in TAGS_CATALOGO_PADRAO])
    try:
        with open(CAMINHO_BANCO_CENTRALIZADO_TAGS, "r", encoding="utf-8") as arquivo:
            bruto = json.load(arquivo)
            return _normalizar_catalogo_tags(bruto)
    except (OSError, json.JSONDecodeError):
        return _garantir_tag_alerta([dict(item) for item in TAGS_CATALOGO_PADRAO])


def _gravar_catalogo_centralizado(catalogo: list[dict]) -> None:
    try:
        os.makedirs(os.path.dirname(CAMINHO_BANCO_CENTRALIZADO_TAGS), exist_ok=True)
        with open(CAMINHO_BANCO_CENTRALIZADO_TAGS, "w", encoding="utf-8") as arquivo:
            json.dump(catalogo, arquivo, ensure_ascii=False, indent=2)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível gravar catálogo centralizado: {exc}")


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
    return {
        "id": "alerta",
        "rotulo": "Alerta",
        "ativa": True,
        "entra_na_analise": True,
        "cor": "#ec1818",
    }


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
            # Arquivos existentes não tinham esta chave. Mantê-los na análise
            # evita esconder tags já cadastradas após atualização.
            "entra_na_analise": bool(item.get("entra_na_analise", True)),
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
    regras_alerta: list[dict] | None = None,
    loja: Optional[str] = None,
) -> dict:
    catalogo_norm = catalogo if catalogo is not None else _normalizar_catalogo_tags(bruto.get("catalogo"))
    balcao = _sincronizar_lista_balcao(tags)
    grupos_norm = grupos if grupos is not None else _normalizar_grupos_manuais(bruto.get("grupos"))
    regras_norm = regras_alerta if regras_alerta is not None else normalizar_regras_alerta(
        bruto.get("regras_alerta"), _ids_do_catalogo(catalogo_norm)
    )
    return {
        "tags": tags,
        "clientes_balcao": balcao,
        "catalogo": catalogo_norm,
        "grupos": grupos_norm,
        "regras_alerta": regras_norm,
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
    regras_alerta: list[dict] | None = None,
    bruto_atual: dict | None = None,
) -> dict:
    grupos_norm = (
        grupos if grupos is not None
        else _normalizar_grupos_manuais((bruto_atual or {}).get("grupos"))
    )
    regras_norm = regras_alerta if regras_alerta is not None else normalizar_regras_alerta(
        (bruto_atual or {}).get("regras_alerta"), _ids_do_catalogo(catalogo)
    )
    return {
        "catalogo": catalogo,
        "tags": tags,
        "clientes_balcao": _sincronizar_lista_balcao(tags),
        "grupos": grupos_norm,
        "regras_alerta": regras_norm,
    }


def _slice_tags_do_escopo(empresa: str, loja: Optional[str] = None) -> dict:
    scopes = _ler_scopes_tags(empresa)
    return dict(scopes.get(_chave_escopo_loja(loja), {}))


def _catalogo_tags_da_empresa(empresa: str, loja: Optional[str], bruto_escopo: dict) -> list[dict]:
    """Retorna o catálogo do banco centralizado no OneDrive. Ignora o legado por loja ou global da empresa.
    
    As tags editadas e cadastradas passam a refletir para todas as empresas.
    """
    return _ler_catalogo_centralizado()


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
    regras = normalizar_regras_alerta(payload.get("regras_alerta"), _ids_do_catalogo(catalogo))
    slice_norm = _payload_tags_completo(catalogo, tags, grupos=grupos, regras_alerta=regras)
    scopes[chave] = slice_norm
    caminho = _gravar_scopes_tags(empresa, scopes)
    return {
        **_montar_resposta_tags_clientes(
            empresa, slice_norm, tags, catalogo, grupos, regras, loja=loja,
        ),
        "caminho": caminho,
    }


def _ler_tags_clientes(empresa: str, loja: Optional[str] = None) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _catalogo_tags_da_empresa(empresa, loja, bruto)
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    grupos = _normalizar_grupos_manuais(bruto.get("grupos") if bruto else [])
    regras = normalizar_regras_alerta(
        bruto.get("regras_alerta") if bruto else [], ids_catalogo,
    )
    return _montar_resposta_tags_clientes(
        empresa, bruto, tags, catalogo, grupos, regras, loja=loja,
    )


def _gravar_tags_clientes(
    empresa: str,
    tags: dict[str, list[str]],
    loja: Optional[str] = None,
) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _catalogo_tags_da_empresa(empresa, loja, bruto)
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags_norm = _normalizar_mapa_tags(tags, ids_catalogo)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(catalogo, tags_norm, bruto_atual=bruto),
        loja=loja,
    )


def _mesclar_catalogo_centralizado(
    central: list[dict], base: list[dict], novo: list[dict],
) -> list[dict]:
    """3-way merge do catálogo centralizado.

    `base` é o catálogo como a sessão o carregou; `novo` é o estado editado
    localmente (criação/edição/remoção); `central` é o estado vigente no
    arquivo no momento do salvar, que pode já ter mudado por outra sessão.
    Sem isso, salvar sempre sobrescrevia `central` inteiro pelo array em
    memória da sessão — uma tag criada por outra aba entre o load e o save
    desta sumia (era exatamente o caso: duas sessões salvando em sequência
    apagaram `balcao`/`interno` uma da outra).
    """
    ids_base = {item["id"]: item for item in base}
    ids_novo = {item["id"]: item for item in novo}
    removidos = set(ids_base) - set(ids_novo)

    resultado: list[dict] = []
    vistos: set[str] = set()
    for item in central:
        tag_id = item.get("id")
        if tag_id in removidos:
            continue
        resultado.append(ids_novo.get(tag_id, item))
        vistos.add(tag_id)
    for tag_id, item in ids_novo.items():
        if tag_id not in vistos:
            resultado.append(item)
    return resultado


def _gravar_catalogo_tags(
    empresa: str,
    catalogo_bruto,
    loja: Optional[str] = None,
    catalogo_base_bruto=None,
) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    novo = _normalizar_catalogo_tags(catalogo_bruto)

    if catalogo_base_bruto is not None:
        central_atual = _ler_catalogo_centralizado()
        base = _normalizar_catalogo_tags(catalogo_base_bruto)
        catalogo = _garantir_tag_alerta(
            _mesclar_catalogo_centralizado(central_atual, base, novo)
        )
    else:
        # Compat: cliente antigo que não manda o snapshot de base — mantém o
        # comportamento anterior (sobrescreve), único caminho possível sem saber
        # o que a sessão realmente editou.
        catalogo = novo

    # Salva no banco centralizado (afeta todas as empresas simultaneamente)
    _gravar_catalogo_centralizado(catalogo)

    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(catalogo, tags, bruto_atual=bruto),
        loja=loja,
    )


def _gravar_grupos_manuais(empresa: str, grupos_bruto, loja: Optional[str] = None) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _catalogo_tags_da_empresa(empresa, loja, bruto)
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    grupos = _normalizar_grupos_manuais(grupos_bruto)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(catalogo, tags, grupos=grupos, bruto_atual=bruto),
        loja=loja,
    )


def _gravar_regras_alerta(empresa: str, regras_brutas, loja: Optional[str] = None) -> dict:
    bruto = _slice_tags_do_escopo(empresa, loja)
    catalogo = _catalogo_tags_da_empresa(empresa, loja, bruto)
    ids_catalogo = _ids_do_catalogo(catalogo)
    tags = _normalizar_mapa_tags(bruto.get("tags") if bruto else {}, ids_catalogo)
    regras = normalizar_regras_alerta(regras_brutas, ids_catalogo)
    return _gravar_arquivo_tags_clientes(
        empresa,
        _payload_tags_completo(
            catalogo, tags, regras_alerta=regras, bruto_atual=bruto,
        ),
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

# Resultado compacto da tela Estoque. Chave inclui assinatura dos dois arquivos,
# então uma base nova invalida o cache sem gravar nada na pasta fonte.
_CACHE_ESTOQUE_MAX = 8
_cache_estoque_cobertura: OrderedDict[tuple, dict] = OrderedDict()
_cache_estoque_cobertura_lock = threading.Lock()

# DataFrame de despesas (CONTROLADORIA.csv) por empresa, cacheado por mtime do
# arquivo. Sem cache do resultado calculado: o groupby é leve (arquivo bem
# menor que MOVIMENTO_ATUAL), não justifica o segundo nível do Estoque.
_CACHE_DESPESAS_MAX = 3
_cache_despesas_df: OrderedDict[str, dict] = OrderedDict()

_CACHE_PRECIFICACAO_MAX = 3
_cache_precificacao_df: OrderedDict[str, dict] = OrderedDict()

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


def _caminho_referencia_fonte(caminho_movimento: Path, caminho_produto: Path) -> Path:
    """Arquivo com a mtime mais recente entre MOVIMENTO_ATUAL e PRODUTO.

    A fonte por empresa hoje é dois arquivos, não um único — este é o
    substituto de "o mtime do arquivo fonte" usado em cache/frescor.
    """
    caminho_movimento = Path(caminho_movimento)
    caminho_produto = Path(caminho_produto)
    if os.path.getmtime(caminho_produto) > os.path.getmtime(caminho_movimento):
        return caminho_produto
    return caminho_movimento


def _chave_disco_tela(pasta_trabalho: str, chave: tuple) -> tuple:
    """Chave do cache em disco: a da RAM + corte D-1 + regra de nomes de cliente.

    A regra de nomes muda a base sem mudar a fonte; o corte muda à meia-noite.
    Os dois já invalidam a base em RAM, então precisam invalidar o disco também.
    """
    return (chave, af.data_corte_padrao(), harmonizar_clientes.mtime_regra(pasta_trabalho))


def _tela_do_disco(empresa: str, tela: str, chave: tuple) -> Optional[dict]:
    """Resultado da tela gravado pelo lote da manhã (ou por outra máquina)."""
    try:
        _pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    except HTTPException:
        return None
    return cache_telas.ler(Path(pasta_trabalho), tela, _chave_disco_tela(pasta_trabalho, chave))


def _tela_para_disco(empresa: str, tela: str, chave: tuple, resultado: dict) -> None:
    try:
        _pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
        _assert_escrita_fora_da_fonte(pasta_trabalho)
    except HTTPException:
        return
    cache_telas.gravar(Path(pasta_trabalho), tela, _chave_disco_tela(pasta_trabalho, chave), resultado)


def _guardar_lru(cache: OrderedDict, trava, chave, valor, maximo: int) -> None:
    with trava:
        cache[chave] = valor
        cache.move_to_end(chave)
        while len(cache) > maximo:
            cache.popitem(last=False)


def _data_ultimo_movimento_bi(pasta_fonte: str) -> Optional[date]:
    """Maior DATA_MOVIMENTO da fonte — o "Último movimento" da barra lateral.

    Sai das estatísticas do parquet (`consulta_parquet.ultimo_movimento`), sem
    ler as linhas. Até a fonte virar parquet era a data de modificação do
    arquivo, que diz quando o OneDrive sincronizou, não o último dia com venda;
    ela segue como reserva se a consulta falhar.
    """
    try:
        caminho_movimento, caminho_produto, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
        try:
            ultimo = consulta_parquet.ultimo_movimento(caminho_movimento)
            if ultimo is not None:
                # A base vai até D-1: dia de hoje que já esteja no arquivo não conta.
                return min(ultimo, af.data_corte_padrao())
        except Exception as exc:
            logger.warning("Falha ao consultar último movimento em %s: %s", pasta_fonte, exc)
        caminho_referencia = _caminho_referencia_fonte(caminho_movimento, caminho_produto)
        return date.fromtimestamp(os.path.getmtime(caminho_referencia))
    except ErroNormalizacao as exc:
        logger.warning("Dados indisponíveis para data de atualização em %s: %s", pasta_fonte, exc)
        return None
    except Exception as exc:
        logger.warning("Falha ao ler data de atualização em %s: %s", pasta_fonte, exc)
        return None


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
    há mais Base.csv intermediário) e o do clientes_harm.json, que muda nomes de
    cliente sem a fonte mudar. Prefere o .gz (pré-comprimido) para evitar gzip
    on-the-fly no hot path.
    """
    caminho_gz = caminho_summary_dashboard_gz(pasta_trabalho)
    caminho_json = caminho_summary_dashboard(pasta_trabalho)

    if summary_dashboard_atualizado(
        pasta_trabalho,
        caminho_atacado,
        mtime_minimo=harmonizar_clientes.mtime_regra(pasta_trabalho),
        data_corte=af.data_corte_padrao(),
    ):
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
            data_corte=af.data_corte_padrao(),
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
    loja: Optional[str] = None,
    grupos_clientes: Optional[set[str]] = None,
) -> Response:
    """Serve summary pré-serializado (RAM/disco); header com data da fonte."""
    mtime_csv = os.path.getmtime(caminho_atacado)
    body = _corpo_summary_cacheado(empresa, caminho_summary, mtime_csv)
    headers: dict[str, str] = {}
    data_ultimo = _data_ultimo_movimento_bi(pasta_fonte)
    if data_ultimo is not None:
        headers["X-Ultimo-Movimento"] = data_ultimo.strftime("%d/%m/%Y")
    gzipped = caminho_summary.name.endswith(".json.gz")
    if aplicar_cortes_relatorios():
        bruto = gzip.decompress(body) if gzipped else body
        summary = json.loads(bruto)
        cortes = _cortes_relatorios_do_escopo(empresa, loja)
        cortes["grupos_clientes"] = grupos_clientes
        cortes["clientes_balcao_extra"] = _clientes_balcao_extra(empresa, loja=loja)
        filtrado = aplicar_cortes_no_summary(summary, cortes)
        return Response(
            content=json.dumps(filtrado, ensure_ascii=False).encode("utf-8"),
            media_type="application/json",
            headers=headers,
        )
    if gzipped:
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
        caminho_movimento, caminho_produto, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    caminho_referencia = _caminho_referencia_fonte(caminho_movimento, caminho_produto)

    # A trava também cobre invalidação; evita apagar arquivo enquanto outra
    # request ainda o lê. É RLock porque a função garantir reutiliza a mesma trava.
    with _trava_summary_empresa(empresa):
        _cache_summary_dashboard.pop(empresa, None)
        _cache_base_empresa.pop(empresa, None)
        invalidar_summary_dashboard(pasta_trabalho)

        caminho_summary = _garantir_summary_dashboard_arquivo(
            empresa, pasta_fonte, pasta_trabalho, str(caminho_referencia),
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
    """Lê MOVIMENTO_ATUAL + PRODUTO direto da fonte (sem arquivo intermediário).

    Cache LRU em RAM chaveado no mtime mais recente dos dois CSVs na fonte e no
    da regra de harmonização de clientes (que reescreve nomes antes de o DF
    entrar no cache).
    """
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_movimento, caminho_produto, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # O corte D-1 entra na chave: virou o dia, a base em RAM já não serve,
    # mesmo sem a fonte mudar.
    data_corte = af.data_corte_padrao()
    mtime = (
        os.path.getmtime(_caminho_referencia_fonte(caminho_movimento, caminho_produto)),
        harmonizar_clientes.mtime_regra(pasta_trabalho),
        data_corte,
    )
    em_cache = _cache_base_empresa.get(empresa)
    if em_cache and em_cache["mtime"] == mtime:
        _lru_touch(_cache_base_empresa, empresa)
        return em_cache["df"], em_cache["linhas_vazias"]

    try:
        # Leitura, join, corte D-1 e limpeza numa consulta DuckDB (`base_duckdb`);
        # esquema fora do padrão cai no caminho pandas de antes.
        df, linhas_vazias = base_duckdb.carregar_base_empresa(caminho_movimento, caminho_produto, data_corte)
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        logger.error("Falha inesperada ao carregar dados de %s:\n%s", empresa, traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"Falha inesperada ao carregar a base: {exc}")

    df = _normalizar_coluna_loja_inplace(df)
    # Nomes de cliente que só diferem pelo sufixo de origem viram um cliente só
    # (regra opcional por empresa, em clientes_harm.json na pasta de trabalho).
    # Aqui, antes do cache: vale para Dashboard, Analisador, Explorar e exports.
    df = harmonizar_clientes.aplicar_em_cliente(
        df, harmonizar_clientes.carregar_regra(pasta_trabalho),
    )
    df = _aplicar_vendedores_demo_se_preciso(df, empresa)
    # Master DF no cache. Callers mutáveis recebem cópia por padrão; as rotas
    # explicitamente somente-leitura podem compartilhar este objeto.
    _lru_set(
        _cache_base_empresa,
        empresa,
        {"mtime": mtime, "df": df, "linhas_vazias": linhas_vazias},
        max_size=_CACHE_BASE_EMPRESA_MAX,
    )
    return df, linhas_vazias


PREFIXO_ESCOPO_MULTILOJAS = "@lojas:"


def _normalizar_lojas(loja: Optional[str]) -> list[str]:
    """Converte o parâmetro legado `loja` em lista ordenada e sem duplicatas.

    Uma loja continua sendo transportada pelo próprio nome. Duas ou mais usam
    JSON prefixado, evitando colisões com nomes que contenham vírgula.
    """
    if loja is None:
        return []
    bruto = str(loja).strip()
    if not bruto:
        return []
    if not bruto.startswith(PREFIXO_ESCOPO_MULTILOJAS):
        return [bruto]
    try:
        payload = json.loads(bruto[len(PREFIXO_ESCOPO_MULTILOJAS):])
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail="Seleção de lojas inválida.") from exc
    if not isinstance(payload, list):
        raise HTTPException(status_code=400, detail="Seleção de lojas inválida.")
    nomes = {str(nome).strip() for nome in payload if str(nome).strip()}
    return sorted(nomes, key=str.casefold)


def _normalizar_loja(loja: Optional[str]) -> Optional[str]:
    """Devolve chave canônica do escopo para cache, configuração e tags."""
    nomes = _normalizar_lojas(loja)
    if not nomes:
        return None
    if len(nomes) == 1:
        return nomes[0]
    return PREFIXO_ESCOPO_MULTILOJAS + json.dumps(
        nomes, ensure_ascii=False, separators=(",", ":"),
    )


def _eh_dados_mockados(empresa: str) -> bool:
    """Empresa de demonstração: pasta `Dados Mockados` na fonte."""
    return (empresa or "").strip().casefold() == "dados mockados"


def _aplicar_vendedores_demo_se_preciso(df: pd.DataFrame, empresa: str) -> pd.DataFrame:
    """Preenche vendedores fictícios só na mockada, e só se a fonte ainda não tiver o campo.

    Não grava na pasta fonte. A atribuição é estável por cliente (hash), para o
    ranking não mudar a cada reload enquanto a coluna real não chegar.
    """
    if df is None or df.empty or not _eh_dados_mockados(empresa):
        return df
    if coluna_vendedor_preenchida(df):
        return df
    return preencher_vendedores_demo(df)


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
    """Filtra uma ou mais lojas. Escopo vazio/None = todas.

    Sempre devolve cópia quando filtra, para não expor view do DF em cache.
    """
    nomes = _normalizar_lojas(loja)
    if not nomes or df is None or df.empty or "Loja" not in df.columns:
        return df
    return df.loc[df["Loja"].isin(nomes)].copy()


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
    nomes = _normalizar_lojas(loja)
    if nomes:
        if "Loja" not in df.columns:
            raise HTTPException(status_code=400, detail="Base não possui coluna Loja para aplicar o filtro.")
        existentes = set(df["Loja"].unique().tolist())
        faltantes = [nome for nome in nomes if nome not in existentes]
        if faltantes:
            raise HTTPException(
                status_code=400,
                detail=f"Loja(s) não encontrada(s) na base: {', '.join(faltantes)}.",
            )
        filtrado = df.loc[df["Loja"].isin(nomes)]
        return (filtrado.copy() if copiar else filtrado), linhas_vazias
    # Sem filtro de loja: cópia defensiva para callers nunca mutarem o DF em cache.
    return (df.copy() if copiar else df), linhas_vazias


def aplicar_cortes_relatorios() -> bool:
    return db.obter_config_app(CHAVE_APLICAR_CORTES_RELATORIOS, "0") == "1"


def _campo_config(config: Optional[dict], *nomes, padrao=None):
    if not isinstance(config, dict):
        return padrao
    for nome in nomes:
        if nome in config and config[nome] is not None:
            return config[nome]
    return padrao


def _lista_config(config: Optional[dict], *nomes) -> list[str]:
    valor = _campo_config(config, *nomes, padrao=[])
    if not isinstance(valor, list):
        return []
    return [str(item).strip() for item in valor if str(item).strip()]


def _cortes_relatorios_do_escopo(empresa: str, loja: Optional[str] = None) -> dict:
    config = _ler_config_escopo(empresa, loja) or {}
    corte = _campo_config(config, "corte_produtos", "corteProdutos", padrao=80.0)
    try:
        corte_num = float(corte)
    except (TypeError, ValueError):
        corte_num = 80.0
    cortes_clientes = _campo_config(config, "cortes_clientes", "cortesClientes", padrao=None)
    if not (isinstance(cortes_clientes, list) and len(cortes_clientes) == 3):
        cortes_clientes = [30.0, 50.0, 60.0]
    return {
        "clientes_excluidos": _lista_config(config, "clientes_excluidos", "clientesExcluidos"),
        "produtos_excluidos": _lista_config(config, "produtos_excluidos", "produtosExcluidos"),
        "corte_produtos": corte_num if corte_num == corte_num else 80.0,
        "desconsiderar_demais_produtos": bool(
            _campo_config(config, "desconsiderar_demais_produtos", "desconsiderarDemaisProdutos", padrao=False)
        ),
        "desconsiderar_nao_harmonizados": bool(
            _campo_config(config, "desconsiderar_nao_harmonizados", "desconsiderarNaoHarmonizados", padrao=False)
        ),
        "cortes_clientes": [float(c) for c in cortes_clientes],
        "desconsiderar_balcao": bool(
            _campo_config(config, "desconsiderar_balcao", "desconsiderarBalcao", padrao=False)
        ),
    }


#: Tokens de faixa aceitos pelo filtro "grupos de clientes" do topo — "1"/"2"/"3"
#: (Grupo N, na mesma ordem dos cortes salvos), "X" (Demais), "B" (Balcão).
def _token_da_faixa(faixa: str) -> str:
    if faixa == af.NOME_FAIXA_BALCAO:
        return "B"
    m = re.match(r"^Grupo (\d+)$", faixa)
    if m:
        return m.group(1)
    return "X"


def _parse_grupos_clientes(valor: Optional[str]) -> Optional[set[str]]:
    """Query string "1,2,B" -> {"1","2","B"}; vazio/None = sem filtro (todos)."""
    if not valor:
        return None
    tokens = {t.strip().upper() for t in valor.split(",") if t.strip()}
    return tokens or None


def _filtrar_por_grupos_clientes(
    df: pd.DataFrame, cortes: dict, grupos_clientes: Optional[set[str]],
) -> pd.DataFrame:
    """Mantém só os clientes cuja faixa (classificação rápida agregada, mesmos
    cortes salvos em Cortes) está em `grupos_clientes`. None/vazio = sem filtro."""
    if not grupos_clientes or "Cliente" not in df.columns or df.empty:
        return df
    classificado = af.classificar_clientes_agregado(
        df, [], cortes["cortes_clientes"], desconsiderar_balcao=cortes["desconsiderar_balcao"],
    )
    mantidos = {
        str(nome) for nome, faixa in zip(classificado["Cliente"], classificado["Faixa"])
        if _token_da_faixa(str(faixa)) in grupos_clientes
    }
    return df.loc[df["Cliente"].astype(str).isin(mantidos)]


def _assinatura_cortes_escopo(
    empresa: str, loja: Optional[str] = None, grupos_clientes: Optional[set[str]] = None,
) -> tuple:
    if not aplicar_cortes_relatorios():
        return ("0",)
    cortes = _cortes_relatorios_do_escopo(empresa, loja)
    return (
        "1",
        tuple(sorted(cortes["clientes_excluidos"])),
        tuple(sorted(cortes["produtos_excluidos"])),
        round(float(cortes["corte_produtos"]), 4),
        bool(cortes["desconsiderar_demais_produtos"]),
        bool(cortes["desconsiderar_nao_harmonizados"]),
        bool(cortes["desconsiderar_balcao"]),
        tuple(sorted(grupos_clientes)) if grupos_clientes else (),
    )


def _carregar_base_telas(
    empresa: Optional[str] = None,
    loja: Optional[str] = None,
    *,
    copiar: bool = True,
    grupos_clientes: Optional[set[str]] = None,
) -> tuple[pd.DataFrame, int]:
    """Base das telas que não são o Relatórios. Aplica config.json se a flag estiver ligada."""
    if not aplicar_cortes_relatorios() or not (empresa and str(empresa).strip()):
        return _carregar_base(empresa, loja=loja, copiar=copiar)
    empresa_norm = empresa.strip()
    cortes = _cortes_relatorios_do_escopo(empresa_norm, loja)
    df = _carregar_df_filtrado(
        cortes["produtos_excluidos"],
        empresa_norm,
        loja=loja,
        corte_produtos=float(cortes["corte_produtos"]),
        desconsiderar_demais_produtos=cortes["desconsiderar_demais_produtos"],
        desconsiderar_nao_harmonizados=cortes["desconsiderar_nao_harmonizados"],
    )
    excluidos = cortes["clientes_excluidos"]
    if excluidos and "Cliente" in df.columns:
        df = df.loc[~df["Cliente"].astype(str).isin(excluidos)].copy()
    elif copiar:
        df = df.copy()
    if cortes["desconsiderar_balcao"] and "Cliente" in df.columns:
        mascara_balcao = af.mascara_clientes_balcao(
            df["Cliente"].astype(str), _clientes_balcao_extra(empresa_norm, loja),
        )
        if bool(mascara_balcao.any()):
            df = df.loc[~mascara_balcao].copy()
    df = _filtrar_por_grupos_clientes(df, cortes, grupos_clientes)
    return df, 0


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
    lojas_selecionadas = _normalizar_lojas(loja_norm)
    faltantes = [nome for nome in lojas_selecionadas if nome not in lojas]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Loja(s) não encontrada(s) na base: {', '.join(faltantes)}.",
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
        "lojas_selecionadas": lojas_selecionadas,
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


def _texto_ou_none(valor) -> Optional[str]:
    """NaN vindo do concat é truthy — daí a checagem antes do str()."""
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    texto = str(valor).strip()
    return texto or None


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
    # Motivo pelo qual o produto fica fora dos relatórios sem estar desmarcado
    # à mão: "demais" (abaixo do corte) ou "nao_harmonizado". Vazio = dentro,
    # ou fora por exclusão manual — que o frontend já conhece pela checkbox.
    if "Fora_Por_Regra" in classificado.columns:
        frame["Fora_Por_Regra"] = classificado["Fora_Por_Regra"]
    else:
        frame["Fora_Por_Regra"] = None
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
            "fora_por_regra": _texto_ou_none(regra),
        }
        for produto, rec, grupo, pct_rec, pct_acum, regra in zip(
            frame["descricao"].tolist(),
            receita,
            frame["Faixa"].tolist(),
            frame["Freq_Simples"].tolist(),
            frame["Freq_Acumulado"].tolist(),
            frame["Fora_Por_Regra"].tolist(),
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
    desconsiderar_demais_produtos: bool = False
    desconsiderar_nao_harmonizados: bool = False


def _mascara_produtos_excluidos(df: pd.DataFrame, produtos_excluidos) -> pd.Series:
    excluidos = {
        str(produto).strip()
        for produto in (produtos_excluidos or [])
        if str(produto).strip()
    }
    if not excluidos:
        return pd.Series(False, index=df.index)
    return df["descricao"].astype(str).isin(excluidos)


def _curva_produtos(
    df: pd.DataFrame,
    produtos_excluidos,
    corte: float,
    desconsiderar_nao_harmonizados: bool,
) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Curva ABC dos produtos que sobram das exclusões que vêm ANTES dela.

    Ordem importa: exclusão manual e "não harmonizado" saem do denominador
    (o balde "NÃO HARMONIZADO" costuma ser o maior item da base e distorceria
    toda a curva). Já "desconsiderar os demais" é consequência da curva, não
    entrada dela — por isso não aparece aqui.

    Devolve (classificado, mascara_manual, mascara_nao_harmonizados).
    """
    mascara_manual = _mascara_produtos_excluidos(df, produtos_excluidos)
    if desconsiderar_nao_harmonizados:
        mascara_nao_harm = af.mascara_produtos_nao_harmonizados(df["descricao"])
    else:
        mascara_nao_harm = pd.Series(False, index=df.index)
    base_curva = df.loc[~mascara_manual & ~mascara_nao_harm]
    return (
        af.classificar_produtos_agregado(base_curva, corte),
        mascara_manual,
        mascara_nao_harm,
    )


def _descricoes_produtos_excluidos(df: pd.DataFrame, cortes: dict) -> set[str]:
    """Descrições de produto que os cortes do Relatórios tiram do relatório
    (manual + "não harmonizados" + "Demais" da curva, quando ligados) — mesma
    régua de `_carregar_df_filtrado`, mas devolvendo o conjunto de descrições
    em vez de um DataFrame filtrado. Usado para recortar `estoque`, que vem
    inteiro do PRODUTO.csv e não tem noção de linha excluída do movimento."""
    produtos_excluidos = cortes.get("produtos_excluidos") or []
    excluidos = {str(p).strip() for p in produtos_excluidos if str(p).strip()}
    desconsiderar_demais = bool(cortes.get("desconsiderar_demais_produtos"))
    desconsiderar_nao_harm = bool(cortes.get("desconsiderar_nao_harmonizados"))
    if not desconsiderar_demais and not desconsiderar_nao_harm:
        return excluidos
    classificado, _mascara_manual, mascara_nao_harm = _curva_produtos(
        df, produtos_excluidos, float(cortes.get("corte_produtos") or 80.0), desconsiderar_nao_harm,
    )
    fora = excluidos | set(df.loc[mascara_nao_harm, "descricao"].astype(str))
    if desconsiderar_demais:
        fora |= set(classificado.loc[classificado["Faixa"] == "Demais", "descricao"].astype(str))
    return fora


@app.post("/api/produtos/previa")
def previa_produtos(parametros: ParametrosProdutos, usuario: str = Depends(exigir_login)):
    # Classificação usa groupby e devolve outro frame; não altera a base cacheada.
    df, _ = _carregar_base(parametros.empresa, loja=parametros.loja, copiar=False)
    corte = float(parametros.corte_produtos)
    classificado, mascara_manual, mascara_nao_harm = _curva_produtos(
        df,
        parametros.produtos_excluidos,
        corte,
        parametros.desconsiderar_nao_harmonizados,
    )
    contagens = classificado["Faixa"].value_counts()

    # "Desconsiderar os demais" é regra, não exclusão gravada: o produto
    # continua na curva, com faixa e percentuais reais, só marcado como fora.
    classificado = classificado.copy()
    if parametros.desconsiderar_demais_produtos:
        classificado["Fora_Por_Regra"] = pd.Series(
            "demais", index=classificado.index,
        ).where(classificado["Faixa"] == "Demais", other=None)
    else:
        classificado["Fora_Por_Regra"] = None
    fora_por_regra = set(
        classificado.loc[classificado["Fora_Por_Regra"].notna(), "descricao"].astype(str)
    )

    # Mantém fora da curva visível para permitir reativação, mas sem atribuir
    # uma faixa incorreta. Receita continua informativa; percentuais ficam
    # vazios porque esses produtos não participam do denominador.
    if bool((mascara_manual | mascara_nao_harm).any()):
        fora = (
            df.loc[mascara_manual | mascara_nao_harm]
            .groupby("descricao", as_index=False)["Receita"]
            .sum()
        )
        fora["Faixa"] = ""
        fora["Freq_Simples"] = None
        fora["Freq_Acumulado"] = None
        # Quem está desmarcado à mão fica sem regra: a checkbox já explica.
        nomes_nao_harm = set(df.loc[mascara_nao_harm, "descricao"].astype(str))
        nomes_manuais = set(df.loc[mascara_manual, "descricao"].astype(str))
        fora["Fora_Por_Regra"] = [
            "nao_harmonizado"
            if nome in nomes_nao_harm and nome not in nomes_manuais
            else None
            for nome in fora["descricao"].astype(str)
        ]
        fora_por_regra |= nomes_nao_harm - nomes_manuais
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
        # Lista completa (sem o teto da prévia) do que as regras tiram. O
        # frontend usa para limpar de `produtos_excluidos` os nomes que as
        # versões antigas materializavam ali.
        "produtos_fora_por_regra": sorted(fora_por_regra),
    }


class ParametrosSugerirCorteProdutos(ParametrosProdutos):
    max_itens_por_grupo: int = 20


@app.post("/api/produtos/sugerir-corte")
def sugerir_corte_produtos(
    parametros: ParametrosSugerirCorteProdutos, usuario: str = Depends(exigir_login),
):
    """Sugere o corte do alto giro para caber em max_itens_por_grupo produtos.

    Espelha /api/grupos/sugerir-cortes: é ação de tela, nunca embutida na
    prévia — o percentual devolvido vai para o campo, então o número que o
    usuário lê é o número que classifica.
    """
    df, _ = _carregar_base(parametros.empresa, loja=parametros.loja, copiar=False)
    mascara_manual = _mascara_produtos_excluidos(df, parametros.produtos_excluidos)
    if parametros.desconsiderar_nao_harmonizados:
        mascara_nao_harm = af.mascara_produtos_nao_harmonizados(df["descricao"])
    else:
        mascara_nao_harm = pd.Series(False, index=df.index)
    corte, _ = af.sugerir_corte_produtos(
        df.loc[~mascara_manual & ~mascara_nao_harm],
        parametros.corte_produtos,
        max_por_grupo=parametros.max_itens_por_grupo,
    )
    return previa_produtos(
        ParametrosProdutos(
            produtos_excluidos=parametros.produtos_excluidos,
            corte_produtos=corte,
            empresa=parametros.empresa,
            loja=parametros.loja,
            desconsiderar_demais_produtos=parametros.desconsiderar_demais_produtos,
            desconsiderar_nao_harmonizados=parametros.desconsiderar_nao_harmonizados,
        ),
        usuario,
    )


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


@app.get("/api/config/caminho-atualizacoes")
def obter_caminho_atualizacoes(usuario: str = Depends(exigir_login)):
    return {"caminho": _resolver_caminho_atualizacoes()}


@app.post("/api/config/caminho-atualizacoes")
def definir_caminho_atualizacoes(corpo: CaminhoPasta, usuario: str = Depends(exigir_login)):
    caminho = corpo.caminho.strip()
    # Vazio limpa a configuração: é como se desliga a verificação de atualização.
    if caminho and not os.path.isdir(caminho):
        raise HTTPException(
            status_code=400,
            detail="A pasta do canal de atualização deve existir e estar acessível.",
        )
    db.definir_config_app(CHAVE_CAMINHO_ATUALIZACOES, caminho)
    atualizacoes.invalidar_cache()
    return {"caminho": caminho}


@app.get("/api/atualizacoes/status")
def obter_status_atualizacao(forcar: bool = False, usuario: str = Depends(exigir_login)):
    """Consulta o canal sob demanda.

    Sob demanda em vez de periódico porque o canal é uma pasta de rede — checar
    em intervalo fixo geraria acesso ao OneDrive sem ninguém pedindo.

    Usa `exigir_login` como as demais rotas de /api/config, o que hoje só
    identifica o usuário no log: `auth.LOGIN_DESATIVADO` deixa passar quem não
    tem token. Vale registrar para o T5, porque aplicar uma atualização é
    destrutivo e não deveria depender só de o servidor escutar em 127.0.0.1.
    """
    canal = _resolver_caminho_atualizacoes()
    return atualizacoes.consultar_canal_cacheado(canal, forcar=forcar).como_dicionario()


#: Cabeçalhos que um proxy reverso acrescenta ao repassar a requisição. A
#: presença de qualquer um deles denuncia que o pedido não nasceu nesta máquina,
#: mesmo chegando com IP de loopback.
#:
#: `x-forwarded-for` está na lista por completude, mas na prática o pedido nem
#: chega aqui com ele: o `uvicorn[standard]` habilita o ProxyHeadersMiddleware por
#: padrão, que confia nesse cabeçalho vindo de loopback e substitui
#: `request.client.host` pelo IP declarado — então a checagem de IP abaixo já
#: rejeita. Os outros três o middleware ignora, e é para eles que esta lista serve.
CABECALHOS_DE_PROXY = ("x-forwarded-for", "x-forwarded-host", "x-real-ip", "forwarded")


def _exigir_origem_local(request: Request) -> None:
    """Recusa a requisição que não nasceu nesta máquina.

    Aplicar uma atualização troca os arquivos do disco onde este processo roda e
    reinicia o serviço — é uma ação de máquina local, não de rede. O uvicorn
    escutar em 127.0.0.1 não basta sozinho como fronteira: qualquer reverse
    proxy que um dia reexponha `/api` numa interface de rede tornaria a API
    alcançável por qualquer PC — e o login está desativado (ver
    auth.LOGIN_DESATIVADO). Sem esta checagem, um curl de qualquer máquina
    derrubaria e substituiria a instalação no meio do dia.

    Preferido a exigir token porque não depende de trocar a senha padrão
    (admin/admin123 vai embutida no pacote) nem de um fluxo de login que a
    interface hoje não tem. Se o login voltar, os dois somam.
    """
    # Não é o peer TCP puro: o ProxyHeadersMiddleware do uvicorn já pode ter
    # substituído isto pelo IP de um X-Forwarded-For confiável. Para o propósito
    # aqui isso ajuda — um pedido repassado por um reverse proxy chega com o IP
    # real do PC da rede, e é exatamente o que se quer rejeitar.
    cliente = request.client.host if request.client else None
    if cliente not in ("127.0.0.1", "::1"):
        raise HTTPException(
            status_code=403,
            detail="A atualização só pode ser aplicada na própria máquina do 2D Prisma.",
        )
    for cabecalho in CABECALHOS_DE_PROXY:
        if cabecalho in request.headers:
            raise HTTPException(
                status_code=403,
                detail=(
                    "A atualização só pode ser aplicada na própria máquina do "
                    "2D Prisma, sem passar por proxy."
                ),
            )


@app.get("/api/config/dados-no-disco")
def obter_dados_no_disco(usuario: str = Depends(exigir_login)):
    """Quanto das pastas fonte e trabalho já está baixado nesta máquina."""
    return {
        "fonte": dados_no_disco.estado(_resolver_caminho_fonte()),
        "trabalho": dados_no_disco.estado(_resolver_caminho_trabalho()),
    }


class DadosNoDiscoBody(BaseModel):
    #: True = "sempre manter nesta máquina"; False = deixar o OneDrive liberar espaço.
    fixar: bool


@app.post("/api/config/dados-no-disco")
def definir_dados_no_disco(
    corpo: DadosNoDiscoBody,
    request: Request,
    usuario: str = Depends(exigir_login),
):
    """Marca fonte e trabalho como "sempre manter nesta máquina", ou desmarca.

    Gate de origem local, como /aplicar: isto dispara download de gigabytes no disco
    de quem hospeda o servidor, e não deve ser acionável pela rede.
    """
    _exigir_origem_local(request)
    try:
        return {
            "fonte": dados_no_disco.aplicar(_resolver_caminho_fonte(), corpo.fixar),
            "trabalho": dados_no_disco.aplicar(_resolver_caminho_trabalho(), corpo.fixar),
        }
    except dados_no_disco.ErroDadosNoDisco as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/api/config/inicio-automatico")
def obter_inicio_automatico(usuario: str = Depends(exigir_login)):
    return inicio_automatico.estado()


class InicioAutomaticoBody(BaseModel):
    logon: bool
    #: None ou "" remove o agendamento; "HH:MM" cria/atualiza.
    horario: Optional[str] = None


@app.post("/api/config/inicio-automatico")
def definir_inicio_automatico(
    corpo: InicioAutomaticoBody,
    request: Request,
    usuario: str = Depends(exigir_login),
):
    """Liga/desliga o início com o Windows e o agendamento diário.

    Com o gate de origem local, como /aplicar: isto altera o que roda no logon
    desta máquina, ação local que não deveria ser acionável pela rede.
    """
    _exigir_origem_local(request)

    if not inicio_automatico.disponivel():
        raise HTTPException(
            status_code=400,
            detail="O início automático só existe na versão instalada (.exe).",
        )
    try:
        inicio_automatico.definir_logon(corpo.logon)
        horario = (corpo.horario or "").strip() or None
        inicio_automatico.definir_horario(
            inicio_automatico.validar_horario(horario) if horario else None
        )
    except inicio_automatico.ErroInicioAutomatico as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except OSError as exc:
        raise HTTPException(
            status_code=500, detail=f"Falha ao gravar a configuração de início: {exc}"
        )
    return inicio_automatico.estado()


def regeneracao_permitida() -> bool:
    return db.obter_config_app(CHAVE_REGENERACAO_PERMITIDA, "0") == "1"


def _exigir_regeneracao_permitida() -> None:
    if not regeneracao_permitida():
        raise HTTPException(
            status_code=409,
            detail=(
                "Esta máquina não regenera bases. A pré-geração é feita pelo lote "
                "noturno na máquina servidora — duas máquinas escrevendo a mesma "
                "empresa na pasta compartilhada criam cópia de conflito no OneDrive. "
                "Se esta é a máquina do lote, habilite em Configurações."
            ),
        )


@app.get("/api/config/regeneracao")
def obter_regeneracao(usuario: str = Depends(exigir_login)):
    return {"permitida": regeneracao_permitida()}


class RegeneracaoBody(BaseModel):
    permitida: bool


@app.post("/api/config/regeneracao")
def definir_regeneracao(
    corpo: RegeneracaoBody,
    request: Request,
    usuario: str = Depends(exigir_login),
):
    """Liga/desliga a regeneração nesta instalação.

    Com gate de origem local, como as outras rotas que mudam o comportamento desta
    máquina: quem está na rede não deve poder habilitar escrita na pasta
    compartilhada a partir de outro computador.
    """
    _exigir_origem_local(request)
    db.definir_config_app(CHAVE_REGENERACAO_PERMITIDA, "1" if corpo.permitida else "0")
    return {"permitida": regeneracao_permitida()}


class CortesRelatoriosBody(BaseModel):
    ativo: bool


@app.get("/api/config/aplicar-cortes-relatorios")
def obter_aplicar_cortes_relatorios(usuario: str = Depends(exigir_login)):
    return {"ativo": aplicar_cortes_relatorios()}


@app.post("/api/config/aplicar-cortes-relatorios")
def definir_aplicar_cortes_relatorios(
    corpo: CortesRelatoriosBody,
    usuario: str = Depends(exigir_login),
):
    db.definir_config_app(CHAVE_APLICAR_CORTES_RELATORIOS, "1" if corpo.ativo else "0")
    return {"ativo": aplicar_cortes_relatorios()}


def _caminho_atualizador() -> Optional[str]:
    """Executável (ou script) que faz a troca dos arquivos.

    Precisa ser um processo separado: no Windows um executável em uso não pode
    sobrescrever a si mesmo.
    """
    if getattr(sys, "frozen", False):
        caminho = os.path.join(pasta_base_execucao(), "atualizador.exe")
        return caminho if os.path.isfile(caminho) else None
    caminho = os.path.join(RAIZ_PROJETO, "atualizador", "atualizador.py")
    return caminho if os.path.isfile(caminho) else None


@app.post("/api/atualizacoes/aplicar")
def aplicar_atualizacao(request: Request, usuario: str = Depends(exigir_login)):
    """Valida o pacote, entrega a troca ao atualizador e encerra este processo."""
    _exigir_origem_local(request)

    if not getattr(sys, "frozen", False):
        # Rodando do fonte não há o que substituir: aplicar aqui sobrescreveria a
        # árvore de desenvolvimento com um build empacotado.
        raise HTTPException(
            status_code=400,
            detail="A atualização automática só funciona na versão empacotada (.exe).",
        )

    # Sem cache: o pacote pode ter terminado de sincronizar (ou sumido) depois da
    # última consulta, e aqui a decisão substitui a instalação.
    status = atualizacoes.consultar_canal(_resolver_caminho_atualizacoes())
    if not status.atualizavel:
        raise HTTPException(status_code=400, detail=status.motivo)

    atualizador = _caminho_atualizador()
    if not atualizador:
        raise HTTPException(
            status_code=500,
            detail="atualizador.exe não foi encontrado ao lado do 2D Prisma.",
        )

    pasta_temporaria = tempfile.mkdtemp(prefix="prisma-update-")
    pacote, erro = atualizacoes.preparar_pacote(status, pasta_temporaria)
    if erro:
        shutil.rmtree(pasta_temporaria, ignore_errors=True)
        raise HTTPException(status_code=400, detail=erro)

    instalacao = pasta_base_execucao()

    # O atualizador precisa rodar de FORA da pasta que vai substituir. Rodando de
    # dentro, o Windows mantém handle aberto no próprio binário em execução e na
    # pasta de trabalho do processo, e o rename da instalação falha com
    # WinError 32 ("o arquivo já está sendo usado por outro processo"). Copiar
    # para o temporário e apontar a cwd para lá solta os dois handles.
    try:
        atualizador_local = shutil.copy2(atualizador, pasta_temporaria)
    except OSError as exc:
        shutil.rmtree(pasta_temporaria, ignore_errors=True)
        raise HTTPException(
            status_code=500, detail=f"Não foi possível preparar o atualizador: {exc}"
        )

    comando = [
        atualizador_local,
        "--pid", str(os.getpid()),
        "--zip", pacote,
        "--destino", instalacao,
        "--versao", status.versao_disponivel or "",
        "--versao-anterior", versao.VERSAO,
    ]

    logger.info("Aplicando atualização para %s: %s", status.versao_disponivel, comando)
    try:
        subprocess.Popen(
            comando,
            cwd=pasta_temporaria,
            close_fds=True,
            # Os três explícitos porque o app fecha o próprio console depois do boot
            # (ver servidor._fechar_console): a partir dali os handles padrão estão
            # inválidos, e herdá-los faz o Popen falhar com WinError 50 — a
            # atualização deixaria de funcionar justamente no modo normal de uso.
            # O atualizador reconecta a saída ao console novo que recebe.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            # Atualizador roda em background e registra tudo em
            # Prisma-atualizacao.log. CREATE_NO_WINDOW evita deixar CMD aberto;
            # não usar esta flag ao religar o Prisma, que possui bootloader de
            # console e cria/fecha sua própria janela durante o boot.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        shutil.rmtree(pasta_temporaria, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Não foi possível iniciar o atualizador: {exc}")

    return Response(
        content=json.dumps(
            {
                "ok": True,
                "versao": status.versao_disponivel,
                "mensagem": (
                    "Atualização iniciada. O 2D Prisma vai fechar e reabrir sozinho "
                    "em alguns instantes."
                ),
            }
        ),
        media_type="application/json",
        # Encerrar só depois da resposta ir embora, senão o navegador mostra erro
        # de conexão em vez da mensagem. O atualizador está esperando este PID
        # morrer para começar.
        background=BackgroundTask(_encerrar_para_atualizar),
    )


def _encerrar_para_atualizar() -> None:
    time.sleep(1.0)
    logger.info("Encerrando para a atualização assumir.")
    # os._exit em vez de sys.exit: já estamos numa task de background, e uma
    # exceção de saída aqui seria capturada pelo servidor em vez de encerrá-lo.
    os._exit(0)


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


def _assinatura_arquivo(caminho: Path) -> tuple[int, int]:
    """Assinatura barata para invalidar cache quando OneDrive troca arquivo."""
    stat = caminho.stat()
    return stat.st_mtime_ns, stat.st_size


def _assinatura_arquivo_opcional(caminho) -> tuple[int, int]:
    """Como `_assinatura_arquivo`, mas para arquivo que pode não existir ainda
    (tags/catálogo criados só no primeiro salvamento)."""
    try:
        stat = os.stat(caminho)
    except OSError:
        return (0, 0)
    return stat.st_mtime_ns, stat.st_size


def _caminho_produto_empresa(empresa: str) -> tuple[Path, Path]:
    """Caminhos de MOVIMENTO_ATUAL e PRODUTO — fonte do estoque hoje é o PRODUTO."""
    pasta_fonte, _pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_movimento, caminho_produto, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return caminho_movimento, caminho_produto


def _ler_estoque_vendas(
    empresa: str,
    caminho_produto: Path,
    loja_norm: Optional[str],
    grupos_clientes: Optional[set[str]] = None,
) -> tuple[pd.DataFrame, pd.DataFrame, list[str]]:
    """Estoque (QUANTIDADE_ESTOQUE do PRODUTO) e vendas (base já carregada),
    recortadas pela loja. Devolve também as lojas da base — a lista sai antes
    do recorte, senão o seletor sumiria assim que uma loja fosse escolhida.
    """
    df_completo, _linhas_vazias = _carregar_base_empresa(empresa)
    try:
        estoque, vendas = af.montar_estoque_e_vendas(df_completo, caminho_produto)
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    lojas = sorted(
        nome for nome in estoque.get("Loja", pd.Series(dtype=str)).fillna("").astype(str).str.strip().unique()
        if nome
    )
    estoque = _filtrar_loja_coluna(estoque, loja_norm, "Loja", caminho_produto.name)
    if aplicar_cortes_relatorios():
        df_telas, _linhas = _carregar_base_telas(
            empresa, loja=loja_norm, copiar=False, grupos_clientes=grupos_clientes,
        )
        try:
            _, vendas = af.montar_estoque_e_vendas(df_telas, caminho_produto)
        except af.ErroCarregamentoCSV as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        # `montar_estoque_e_vendas` monta `estoque` inteiro a partir do
        # PRODUTO.csv — passar o `df` já cortado não tira produto nenhum dele
        # sozinho (diferente de `vendas`, agregada do `df`). Sem isto, excluir
        # um produto nos Cortes some das vendas/CMV mas ele continua aparecendo
        # em "Dinheiro dormindo"/"Capital por situação" do Estoque.
        cortes = _cortes_relatorios_do_escopo(empresa, loja_norm)
        df_loja, _ = _carregar_base(empresa, loja=loja_norm, copiar=False)
        fora_desc = _descricoes_produtos_excluidos(df_loja, cortes)
        if fora_desc:
            estoque = estoque.loc[~estoque["descricao"].astype(str).isin(fora_desc)]
    else:
        vendas = _filtrar_loja_coluna(vendas, loja_norm, "Nome_Loja", caminho_produto.name)
    return estoque, vendas, lojas


@app.get("/api/estoque/cobertura/{empresa}")
def obter_cobertura_estoque(
    empresa: str,
    loja: Optional[str] = None,
    meses: int = 6,
    limite: int = 800,
    usar_mes_fechado: bool = True,
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Mapa de estoque atual × velocidade média de venda por produto.

    Estoque vem do QUANTIDADE_ESTOQUE do PRODUTO.csv; vendas, da base já
    carregada (MOVIMENTO_ATUAL). O frontend recebe pontos já calculados e
    nunca conhece caminhos locais.
    """
    if meses < 1 or meses > 24:
        raise HTTPException(status_code=400, detail="meses deve ficar entre 1 e 24.")
    if limite < 1 or limite > 2000:
        raise HTTPException(status_code=400, detail="limite deve ficar entre 1 e 2000.")

    empresa = _validar_nome_empresa(empresa)
    caminho_movimento, caminho_produto = _caminho_produto_empresa(empresa)

    loja_norm = _normalizar_loja(loja)
    grupos_norm = _parse_grupos_clientes(grupos_clientes)
    try:
        assinatura = (_assinatura_arquivo(caminho_produto), _assinatura_arquivo(caminho_movimento))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler arquivos de estoque: {exc}") from exc
    chave_cache = (
        empresa, loja_norm or "", meses, limite, usar_mes_fechado, assinatura, date.today(),
        _assinatura_cortes_escopo(empresa, loja_norm, grupos_norm),
    )
    with _cache_estoque_cobertura_lock:
        cacheado = _cache_estoque_cobertura.get(chave_cache)
        if cacheado is not None:
            _cache_estoque_cobertura.move_to_end(chave_cache)
            return cacheado
    em_disco = _tela_do_disco(empresa, "estoque", chave_cache)
    if em_disco is not None:
        _guardar_lru(_cache_estoque_cobertura, _cache_estoque_cobertura_lock, chave_cache, em_disco,
                     _CACHE_ESTOQUE_MAX)
        return em_disco

    estoque, vendas, lojas = _ler_estoque_vendas(empresa, caminho_produto, loja_norm, grupos_norm)

    resultado = montar_cobertura_estoque(
        estoque, vendas, meses=meses, limite=limite, usar_mes_fechado=usar_mes_fechado,
    )
    resultado.update({
        "disponivel": True,
        "mensagem": None,
        "empresa": empresa,
        "loja": loja_norm,
        "lojas": lojas,
        "itens_exibidos": len(resultado["itens"]),
        "limitado": resultado["resumo"]["produtos"] > len(resultado["itens"]),
    })
    with _cache_estoque_cobertura_lock:
        _cache_estoque_cobertura[chave_cache] = resultado
        _cache_estoque_cobertura.move_to_end(chave_cache)
        while len(_cache_estoque_cobertura) > _CACHE_ESTOQUE_MAX:
            _cache_estoque_cobertura.popitem(last=False)
    _tela_para_disco(empresa, "estoque", chave_cache, resultado)
    return resultado


@app.get("/api/estoque/resumo/{empresa}")
def obter_resumo_estoque(
    empresa: str,
    loja: Optional[str] = None,
    meses: int = 6,
    usar_mes_fechado: bool = True,
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Agregados da visão geral de estoque, calculados sobre a base inteira.

    Rota separada da de cobertura porque o recorte é outro: lá vão até 2.000
    produtos para o mapa, aqui vão poucos KB de totais e pontas. Mesma leitura
    de arquivos, mesmo cache e a mesma régua de situação.
    """
    if meses < 1 or meses > 24:
        raise HTTPException(status_code=400, detail="meses deve ficar entre 1 e 24.")

    empresa = _validar_nome_empresa(empresa)
    caminho_movimento, caminho_produto = _caminho_produto_empresa(empresa)

    loja_norm = _normalizar_loja(loja)
    grupos_norm = _parse_grupos_clientes(grupos_clientes)
    try:
        assinatura = (_assinatura_arquivo(caminho_produto), _assinatura_arquivo(caminho_movimento))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler arquivos de estoque: {exc}") from exc
    chave_cache = (
        "resumo", empresa, loja_norm or "", meses, usar_mes_fechado, assinatura, date.today(),
        _assinatura_cortes_escopo(empresa, loja_norm, grupos_norm),
    )
    with _cache_estoque_cobertura_lock:
        cacheado = _cache_estoque_cobertura.get(chave_cache)
        if cacheado is not None:
            _cache_estoque_cobertura.move_to_end(chave_cache)
            return cacheado
    em_disco = _tela_do_disco(empresa, "estoque", chave_cache)
    if em_disco is not None:
        _guardar_lru(_cache_estoque_cobertura, _cache_estoque_cobertura_lock, chave_cache, em_disco,
                     _CACHE_ESTOQUE_MAX)
        return em_disco

    estoque, vendas, lojas = _ler_estoque_vendas(empresa, caminho_produto, loja_norm, grupos_norm)

    resultado = montar_resumo_estoque(estoque, vendas, meses=meses, usar_mes_fechado=usar_mes_fechado)
    resultado.update({
        "disponivel": True,
        "mensagem": None,
        "empresa": empresa,
        "loja": loja_norm,
        "lojas": lojas,
    })
    with _cache_estoque_cobertura_lock:
        _cache_estoque_cobertura[chave_cache] = resultado
        _cache_estoque_cobertura.move_to_end(chave_cache)
        while len(_cache_estoque_cobertura) > _CACHE_ESTOQUE_MAX:
            _cache_estoque_cobertura.popitem(last=False)
    _tela_para_disco(empresa, "estoque", chave_cache, resultado)
    return resultado


@app.get("/api/vendedores/{empresa}")
def listar_vendedores(
    empresa: str,
    loja: Optional[str] = None,
    modo_periodo: str = "fechados",
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Ranking do último mês contra a média dos 6 anteriores."""
    empresa = _validar_nome_empresa(empresa)
    loja_norm = _normalizar_loja(loja)
    grupos_norm = _parse_grupos_clientes(grupos_clientes)
    caminho_movimento, caminho_produto = _caminho_produto_empresa(empresa)
    try:
        assinatura = (_assinatura_arquivo(caminho_movimento), _assinatura_arquivo(caminho_produto))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler a base: {exc}") from exc
    chave = (
        empresa, loja_norm or "", modo_periodo, assinatura, date.today(),
        _assinatura_cortes_escopo(empresa, loja_norm, grupos_norm),
    )
    em_disco = _tela_do_disco(empresa, "vendedores", chave)
    if em_disco is not None:
        return em_disco
    df, _linhas_vazias = _carregar_base_telas(empresa, loja=loja, grupos_clientes=grupos_norm)
    resultado = montar_ranking_vendedores(df, modo_periodo=modo_periodo)
    resultado["empresa"] = empresa
    resultado["loja"] = _chave_escopo_loja(loja) or None
    _tela_para_disco(empresa, "vendedores", chave, resultado)
    return resultado


def _caminho_controladoria_empresa(empresa: str) -> Path:
    pasta_fonte, _pasta_trabalho = _pastas_empresa(empresa)
    caminho = resolver_caminho_controladoria(Path(pasta_fonte))
    if caminho is None:
        raise HTTPException(
            status_code=404,
            detail=f"Empresa '{empresa}' não tem arquivo de despesas ({empresa}_CONTROLADORIA).",
        )
    return caminho


def _carregar_despesas_df(empresa: str) -> pd.DataFrame:
    """DataFrame de despesas da empresa, cacheado em memória por mtime do CSV."""
    caminho = _caminho_controladoria_empresa(empresa)
    try:
        assinatura = _assinatura_arquivo(caminho)
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Não foi possível ler o arquivo de despesas: {exc}"
        ) from exc

    cacheado = _cache_despesas_df.get(empresa)
    if cacheado is not None and cacheado["assinatura"] == assinatura:
        _cache_despesas_df.move_to_end(empresa)
        return cacheado["df"]

    df = af.carregar_csv_despesas(caminho)
    _cache_despesas_df[empresa] = {"assinatura": assinatura, "df": df}
    _cache_despesas_df.move_to_end(empresa)
    while len(_cache_despesas_df) > _CACHE_DESPESAS_MAX:
        _cache_despesas_df.popitem(last=False)
    return df


@app.get("/api/despesas/{empresa}")
def obter_resumo_despesas(
    empresa: str,
    loja: Optional[str] = None,
    meses: int = 12,
    usar_mes_fechado: bool = True,
    usuario: str = Depends(exigir_login),
):
    """Total, série mês a mês e rankings de categoria/loja das despesas (Controladoria).

    A curva ABC de categorias sai do `cortes_clientes` do `config.json` do
    escopo, os mesmos cortes do Analisador — Despesas precisa classificar a
    categoria na mesma faixa que Clientes/Produtos.
    """
    if meses < 1 or meses > 36:
        raise HTTPException(status_code=400, detail="meses deve ficar entre 1 e 36.")

    empresa = _validar_nome_empresa(empresa)
    df = _carregar_despesas_df(empresa)
    config = _ler_config_escopo(empresa, loja) or {}

    lojas = sorted(
        nome for nome in df.get("Loja", pd.Series(dtype=str)).fillna("").astype(str).str.strip().unique()
        if nome
    )
    loja_norm = _normalizar_loja(loja)
    df_filtrado = _filtrar_loja_coluna(df, loja, "Loja", "CONTROLADORIA")

    resultado = montar_resumo_despesas(
        df_filtrado,
        meses=meses,
        usar_mes_fechado=usar_mes_fechado,
        cortes=config.get("cortes_clientes"),
    )
    resultado.update({"empresa": empresa, "loja": loja_norm, "lojas": lojas})
    return resultado


@app.get("/api/despesas/{empresa}/detalhe")
def obter_detalhe_despesas(
    empresa: str,
    loja: Optional[str] = None,
    periodo: Optional[str] = None,
    categoria: Optional[str] = None,
    limite: int = 500,
    usuario: str = Depends(exigir_login),
):
    """Lançamentos individuais de despesas, para a tabela de detalhe."""
    empresa = _validar_nome_empresa(empresa)
    df = _carregar_despesas_df(empresa)
    df_filtrado = _filtrar_loja_coluna(df, loja, "Loja", "CONTROLADORIA")

    resultado = montar_detalhe_despesas(
        df_filtrado, periodo=periodo, categoria=categoria, limite=limite,
    )
    resultado.update({"empresa": empresa, "loja": _normalizar_loja(loja)})
    return resultado


def _caminho_precificacao_empresa(empresa: str) -> Path:
    _pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    # O dump vive só no trabalho: é onde `precificacao_do_postgres.py` o grava.
    caminho = resolver_caminho_precificacao(Path(pasta_trabalho))
    if caminho is None:
        raise HTTPException(
            status_code=404,
            # A frase "ainda não tem precificação" é o que o frontend reconhece
            # (utils/semPrecificacao.ts) para mostrar aviso em vez de erro.
            detail=f"A empresa '{empresa}' ainda não tem precificação registrada.",
        )
    return caminho


def _carregar_precificacao_df(empresa: str) -> pd.DataFrame:
    """Dump de precificação da empresa, cacheado em memória por mtime do arquivo."""
    caminho = _caminho_precificacao_empresa(empresa)
    try:
        assinatura = _assinatura_arquivo(caminho)
    except OSError as exc:
        raise HTTPException(
            status_code=400, detail=f"Não foi possível ler o arquivo de precificação: {exc}"
        ) from exc

    cacheado = _cache_precificacao_df.get(empresa)
    if cacheado is not None and cacheado["assinatura"] == assinatura:
        _cache_precificacao_df.move_to_end(empresa)
        return cacheado["df"]

    try:
        df = af.carregar_csv_precificacao(caminho)
    except af.ErroCarregamentoCSV as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _cache_precificacao_df[empresa] = {"assinatura": assinatura, "df": df}
    _cache_precificacao_df.move_to_end(empresa)
    while len(_cache_precificacao_df) > _CACHE_PRECIFICACAO_MAX:
        _cache_precificacao_df.popitem(last=False)
    return df


# Pós-precificação: montar_pos_precificacao custa ~3,3s na IBAD (custo
# espalhado por várias janelas, sem um ponto único pra vetorizar), e igual ao
# diagnóstico o cálculo é determinístico pros mesmos arquivos — cacheado pela
# assinatura do dump + da base de movimento (o que muda o resultado).
_CACHE_POS_PRECIFICACAO_MAX = 8
_cache_pos_precificacao: OrderedDict[tuple, dict] = OrderedDict()
_cache_pos_precificacao_lock = threading.Lock()


def _fonte_movimento_pos_precificacao(empresa: str, loja: Optional[str]) -> tuple[str, Optional[tuple]]:
    """Decide a fonte de movimento sem carregar nada (só `stat()` dos parquets):
    `margem_price` quando a empresa tem CNPJ mapeado (`precificacao_cnpj.json`)
    e parquet gerado, e nenhuma loja está selecionada — o parquet já soma
    todas as lojas da empresa por CNPJ (ver `margem_price.py`), então filtrar
    por 1 loja específica ainda cai no CSV, que já sabe fazer esse recorte.
    """
    if loja:
        return "csv", None
    pasta_margem = caminhos_padrao.margem_price()
    if pasta_margem is None:
        return "csv", None
    # Raiz da pasta de trabalho (onde `precificacao_cnpj.json` fica) — não a
    # subpasta da empresa que `_pastas_empresa` devolve.
    pasta_trabalho = Path(_exigir_caminho_trabalho())
    assinatura_mgp = mgp.assinatura(empresa, pasta_trabalho, pasta_margem)
    if assinatura_mgp is None:
        return "csv", None
    return "margem_price", assinatura_mgp


def _carregar_movimento_pos_precificacao(empresa: str, loja: Optional[str], fonte: str) -> pd.DataFrame:
    if fonte == "margem_price":
        pasta_margem = caminhos_padrao.margem_price()
        pasta_trabalho = Path(_exigir_caminho_trabalho())
        bruto = mgp.carregar_bruto(empresa, pasta_trabalho, pasta_margem)
        return mgp.para_movimento_precificacao(bruto)
    df, _linhas = _carregar_base(empresa, loja=loja, copiar=False)
    return df


@app.get("/api/precificacao/{empresa}")
def obter_pos_precificacao(
    empresa: str,
    loja: Optional[str] = None,
    rodada: Optional[str] = None,
    apenas_precificados: bool = False,
    usuario: str = Depends(exigir_login),
):
    """Uma rodada de precificação e como a loja vendeu antes e depois da data.

    O dump não tem loja; o recorte de loja vale só no movimento (desempenho).
    Cortes de Relatórios não entram. `apenas_precificados` restringe o
    movimento aos pares do dump; sem ele vem o catálogo inteiro, com o que
    ficou fora da rodada marcado como `nao_precificado`.

    `rodada` é o dia (`YYYY-MM-DD`) de `data_exportacao`; sem ela, a mais
    recente do arquivo — o que preserva o comportamento de quando o dump tinha
    uma rodada só. O arquivo gerado a partir do Postgres traz as N últimas, e
    `rodadas` na resposta lista as disponíveis com tamanho, porque rodada vai de
    3 a ~15 mil linhas e uma minúscula precisa ser reconhecível como escolha.

    O movimento em si prefere `margem_price` (ver `_fonte_movimento_pos_precificacao`),
    com fallback automático para o CSV por empresa quando a empresa ainda não
    tem CNPJ mapeado ou parquet gerado.
    """
    empresa = _validar_nome_empresa(empresa)
    loja_norm = _normalizar_loja(loja)
    caminho_dump = _caminho_precificacao_empresa(empresa)

    fonte_movimento, assinatura_mgp = _fonte_movimento_pos_precificacao(empresa, loja)
    try:
        if fonte_movimento == "margem_price":
            assinatura_movimento = ("margem_price", assinatura_mgp)
        else:
            caminho_movimento, caminho_produto = _caminho_produto_empresa(empresa)
            assinatura_movimento = (
                "csv", _assinatura_arquivo(caminho_movimento), _assinatura_arquivo(caminho_produto),
            )
        assinatura = (_assinatura_arquivo(caminho_dump), assinatura_movimento)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler a base: {exc}") from exc

    chave = (empresa, loja_norm or "", rodada or "", apenas_precificados, assinatura, af.data_corte_padrao())
    with _cache_pos_precificacao_lock:
        cacheado = _cache_pos_precificacao.get(chave)
        if cacheado is not None:
            _cache_pos_precificacao.move_to_end(chave)
            return cacheado
    em_disco = _tela_do_disco(empresa, "pos-precificacao", chave)
    if em_disco is not None:
        _guardar_lru(_cache_pos_precificacao, _cache_pos_precificacao_lock, chave, em_disco,
                     _CACHE_POS_PRECIFICACAO_MAX)
        return em_disco

    dump = _carregar_precificacao_df(empresa)
    rodadas = listar_rodadas_dump(dump)
    dump_rodada = filtrar_rodada(dump, rodada)
    df = _carregar_movimento_pos_precificacao(empresa, loja, fonte_movimento)
    resultado = montar_pos_precificacao(dump_rodada, df, apenas_precificados=apenas_precificados)
    resultado.update({
        "empresa": empresa,
        "loja": _chave_escopo_loja(loja) or None,
        "rodadas": rodadas,
        "rodada": rodadas[0]["dia"] if rodada is None and rodadas else rodada,
        "fonte_movimento": fonte_movimento,
    })

    with _cache_pos_precificacao_lock:
        _cache_pos_precificacao[chave] = resultado
        _cache_pos_precificacao.move_to_end(chave)
        while len(_cache_pos_precificacao) > _CACHE_POS_PRECIFICACAO_MAX:
            _cache_pos_precificacao.popitem(last=False)
    _tela_para_disco(empresa, "pos-precificacao", chave, resultado)
    return resultado


# Tela Precificação, aba Pós-precificação: histórico por SKU. Eventos + janelas
# de efeito custam ~0,5 s e não dependem de filtro — cacheados por assinatura do
# dump e dos parquets; os filtros só recortam.
_CACHE_HIST_PREC_MAX = 2
_cache_hist_prec: OrderedDict[tuple, tuple[pd.DataFrame, pd.DataFrame]] = OrderedDict()
_cache_hist_prec_lock = threading.Lock()


def _base_historico_precificacao(empresa: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    fonte, assinatura_mgp = _fonte_movimento_pos_precificacao(empresa, None)
    if fonte != "margem_price":
        raise HTTPException(
            status_code=400,
            detail=(
                f"O histórico por SKU precisa do parquet do PRICE (margem_price) para '{empresa}': "
                "mapeie o CNPJ em precificacao_cnpj.json e gere o parquet."
            ),
        )
    try:
        chave = (empresa, _assinatura_arquivo(_caminho_precificacao_empresa(empresa)), assinatura_mgp)
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler o dump: {exc}") from exc
    with _cache_hist_prec_lock:
        cacheado = _cache_hist_prec.get(chave)
        if cacheado is not None:
            _cache_hist_prec.move_to_end(chave)
            return cacheado
    dump = _carregar_precificacao_df(empresa)
    movimento = _carregar_movimento_pos_precificacao(empresa, None, "margem_price")
    try:
        eventos = hist_prec.calcular_efeitos(
            hist_prec.preparar_eventos(dump), hist_prec.preparar_diario(movimento),
        )
        serie = hist_prec.preparar_serie(movimento)
    except hist_prec.ErroHistoricoPrecificacao as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    with _cache_hist_prec_lock:
        _cache_hist_prec[chave] = (eventos, serie)
        _cache_hist_prec.move_to_end(chave)
        while len(_cache_hist_prec) > _CACHE_HIST_PREC_MAX:
            _cache_hist_prec.popitem(last=False)
    return eventos, serie


def _lista_parametro(valor: Optional[str]) -> Optional[list[str]]:
    itens = [item.strip() for item in (valor or "").split(",") if item.strip()]
    return itens or None


def _validar_filtros_historico(periodo: int, nivel: Optional[str] = None) -> None:
    if periodo not in hist_prec.PERIODOS_DIAS:
        raise HTTPException(status_code=400, detail=f"Período inválido: {periodo}.")
    if nivel is not None and nivel not in (*hist_prec.NIVEIS, "rodada"):
        raise HTTPException(status_code=400, detail=f"Nível inválido: {nivel}.")


@app.get("/api/precificacao/{empresa}/historico")
def obter_historico_precificacao(
    empresa: str,
    periodo: int = 180,
    rodadas: Optional[str] = None,
    faixas: Optional[str] = None,
    nivel: str = "familia",
    todos: bool = False,
    busca: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Histórico de precificações por SKU num período, sem prender a uma rodada.

    `rodadas` e `faixas` vêm separados por vírgula (dias `YYYY-MM-DD`, letras da
    faixa). `nivel` agrupa a tabela: familia, fabricante, par, sku ou rodada.
    `todos` só troca a série do gráfico para a loja inteira.
    """
    empresa = _validar_nome_empresa(empresa)
    _validar_filtros_historico(periodo, nivel)
    eventos, serie = _base_historico_precificacao(empresa)
    resultado = hist_prec.montar_historico(
        eventos, serie, periodo_dias=periodo, rodadas=_lista_parametro(rodadas),
        faixas=_lista_parametro(faixas), nivel=nivel, todos=todos, busca=busca,
    )
    resultado["empresa"] = empresa
    return resultado


@app.get("/api/precificacao/{empresa}/historico/item")
def obter_item_historico_precificacao(
    empresa: str,
    nivel: str,
    nome: str,
    periodo: int = 180,
    rodadas: Optional[str] = None,
    faixas: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Painel do item: histórico de precificações, série e SKUs que mais pesam."""
    empresa = _validar_nome_empresa(empresa)
    _validar_filtros_historico(periodo)
    if nivel not in hist_prec.NIVEIS:
        raise HTTPException(status_code=400, detail=f"Nível inválido: {nivel}.")
    eventos, serie = _base_historico_precificacao(empresa)
    return hist_prec.montar_item(
        eventos, serie, nivel=nivel, nome=nome, periodo_dias=periodo,
        rodadas=_lista_parametro(rodadas), faixas=_lista_parametro(faixas),
    )


# Tela Precificação (a precificar). O dump é opcional aqui: sem ele não há alvo,
# e a referência de cada SKU passa a ser a margem da janela base.
_CACHE_A_PRECIFICAR_MAX = 3
_cache_a_precificar: OrderedDict[tuple, tuple[pd.DataFrame, pd.DataFrame, dict]] = OrderedDict()
_cache_a_precificar_lock = threading.Lock()


def _base_a_precificar(empresa: str) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    fonte, assinatura_mgp = _fonte_movimento_pos_precificacao(empresa, None)
    if fonte != "margem_price":
        raise HTTPException(
            status_code=404,
            detail=f"A empresa '{empresa}' ainda não tem movimento do PRICE (margem por transação).",
        )
    try:
        caminho_dump = _caminho_precificacao_empresa(empresa)
        assinatura_dump = _assinatura_arquivo(caminho_dump)
    except (HTTPException, OSError):
        caminho_dump, assinatura_dump = None, None
    data_corte = af.data_corte_padrao()
    chave = (empresa, assinatura_mgp, assinatura_dump, data_corte)
    with _cache_a_precificar_lock:
        cacheado = _cache_a_precificar.get(chave)
        if cacheado is not None:
            _cache_a_precificar.move_to_end(chave)
            return cacheado
    dump = _carregar_precificacao_df(empresa) if caminho_dump is not None else None
    pasta_trabalho = Path(_exigir_caminho_trabalho())
    try:
        bruto = mgp.carregar_bruto(empresa, pasta_trabalho, caminhos_padrao.margem_price())
        mov = a_precificar.preparar_movimento(bruto, data_corte)
        skus, contexto = a_precificar.calcular_skus(mov, a_precificar.alvos_vigentes(dump))
    except (mgp.ErroMargemPrice, a_precificar.ErroAPrecificar) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resultado = (mov, skus, contexto)
    with _cache_a_precificar_lock:
        _cache_a_precificar[chave] = resultado
        _cache_a_precificar.move_to_end(chave)
        while len(_cache_a_precificar) > _CACHE_A_PRECIFICAR_MAX:
            _cache_a_precificar.popitem(last=False)
    return resultado


@app.get("/api/precificacao/{empresa}/a-precificar")
def obter_a_precificar(empresa: str, usuario: str = Depends(exigir_login)):
    """SKUs que precisam de preço novo, com as provas e o lucro perdido por dia
    (regras em `a_precificar.py`). Todas as lojas: o movimento é o do PRICE."""
    empresa = _validar_nome_empresa(empresa)
    _mov, skus, contexto = _base_a_precificar(empresa)
    resultado = a_precificar.montar_a_precificar(skus, contexto)
    resultado["empresa"] = empresa
    return resultado


@app.get("/api/precificacao/{empresa}/a-precificar/par")
def obter_par_a_precificar(
    empresa: str, descricao: str, fabricante: str, usuario: str = Depends(exigir_login),
):
    """Painel do item: margem por semana da descrição × fabricante e os SKUs sinalizados."""
    empresa = _validar_nome_empresa(empresa)
    mov, skus, _contexto = _base_a_precificar(empresa)
    return a_precificar.detalhe_par(mov, skus, descricao, fabricante)


_CACHE_MARGEM_PRICE_MAX = 16
_cache_margem_price: OrderedDict[tuple, dict] = OrderedDict()
_cache_margem_price_lock = threading.Lock()


@app.get("/api/dashboard/margem-price/{empresa}")
def obter_margem_price_dashboard(empresa: str):
    """Margem mensal da empresa inteira, vinda do parquet `margem_price`
    (soma `receita`/`cmv` de todas as lojas do CNPJ antes de dividir — ver
    `margem_price.py`; é a fórmula validada contra a tela do PRICE).

    Rota pública (mesmo padrão de `/api/dashboard/*`): o Dashboard não exige
    login. `disponivel=False` quando a empresa não tem CNPJ mapeado em
    `precificacao_cnpj.json` ou nenhum parquet foi gerado ainda — o frontend
    cai de volta para a margem aproximada calculada a partir do summary.
    """
    empresa = _validar_nome_empresa(empresa)
    vazio = {"disponivel": False, "serie_mensal": []}
    pasta_margem = caminhos_padrao.margem_price()
    if pasta_margem is None:
        return vazio
    pasta_trabalho = Path(_exigir_caminho_trabalho())
    assinatura_mgp = mgp.assinatura(empresa, pasta_trabalho, pasta_margem)
    if assinatura_mgp is None:
        return vazio

    chave = (empresa, assinatura_mgp)
    with _cache_margem_price_lock:
        cacheado = _cache_margem_price.get(chave)
        if cacheado is not None:
            _cache_margem_price.move_to_end(chave)
            return cacheado

    try:
        bruto = mgp.carregar_bruto(empresa, pasta_trabalho, pasta_margem)
    except mgp.ErroMargemPrice:
        resultado = vazio
    else:
        resultado = {"disponivel": True, "serie_mensal": mgp.margem_mensal(bruto)}

    with _cache_margem_price_lock:
        _cache_margem_price[chave] = resultado
        _cache_margem_price.move_to_end(chave)
        while len(_cache_margem_price) > _CACHE_MARGEM_PRICE_MAX:
            _cache_margem_price.popitem(last=False)
    return resultado


@app.get("/api/vendedores/{empresa}/ficha")
def obter_ficha_vendedor(
    empresa: str,
    vendedor: str,
    loja: Optional[str] = None,
    modo_periodo: str = "fechados",
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Ficha de um vendedor: clientes, mix e alertas de queda."""
    empresa = _validar_nome_empresa(empresa)
    df, _linhas_vazias = _carregar_base_telas(
        empresa, loja=loja, grupos_clientes=_parse_grupos_clientes(grupos_clientes),
    )
    try:
        resultado = montar_ficha_vendedor(df, vendedor, modo_periodo=modo_periodo)
    except ErroFichaVendedor as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    resultado["empresa"] = empresa
    resultado["loja"] = _chave_escopo_loja(loja) or None
    return resultado


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
    # Snapshot do catálogo no momento em que a sessão carregou a tela — usado
    # para calcular o diff (criação/edição/remoção) e mesclar com o estado
    # vigente no arquivo em vez de sobrescrevê-lo. Opcional para compatibilidade
    # com clientes antigos que ainda não mandam esse campo.
    catalogo_base: Optional[list] = None


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
        catalogo_base_bruto=corpo.catalogo_base if isinstance(corpo.catalogo_base, list) else None,
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


class RegrasAlertasClientesBody(BaseModel):
    regras: list


@app.put("/api/empresas/{nome}/clientes-alertas/regras")
def salvar_regras_alertas_clientes(
    nome: str,
    corpo: RegrasAlertasClientesBody,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Persiste regras por tag somente na pasta de trabalho da empresa."""
    return _gravar_regras_alerta(
        nome,
        corpo.regras if isinstance(corpo.regras, list) else [],
        loja=loja,
    )


@app.get("/api/empresas/{nome}/clientes-alertas")
def obter_alertas_clientes(
    nome: str,
    loja: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Avalia ritmo do mês para clientes das tags com regra ativa."""
    nome = _validar_nome_empresa(nome)
    estado_tags = _ler_tags_clientes(nome, loja=loja)
    df, _linhas_vazias = _carregar_base_telas(nome, loja=loja)
    resultado = avaliar_alertas_clientes(
        df,
        estado_tags.get("tags") or {},
        estado_tags.get("regras_alerta") or [],
    )
    resultado["regras"] = estado_tags.get("regras_alerta") or []
    resultado["loja"] = _chave_escopo_loja(loja) or None
    return resultado


# Visão geral de clientes: montar_painel_clientes custa ~7,75s na IBAD (dois
# antipadrões de pandas corrigidos, mas a função ainda varre a base inteira),
# e é chamada 3x pelo prefetch (um por modo de período). Cacheada como o
# diagnóstico — assinatura dos arquivos de base, cortes/grupos do escopo, e
# dos dois arquivos de tags (por-empresa + catálogo centralizado), já que o
# resultado embute tag e Balcão por cliente.
_CACHE_PAINEL_CLIENTES_MAX = 8
_cache_painel_clientes: OrderedDict[tuple, dict] = OrderedDict()
_cache_painel_clientes_lock = threading.Lock()


@app.get("/api/clientes/{empresa}/painel")
def obter_painel_clientes(
    empresa: str,
    loja: Optional[str] = None,
    modo_periodo: str = "fechados",
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Visão geral da carteira: KPIs, curva ABC, movimento mensal, top e tags.

    Os cortes da curva saem do `config.json` do escopo, os mesmos do Analisador
    — dashboard e relatório precisam classificar o cliente na mesma faixa.
    """
    empresa = _validar_nome_empresa(empresa)
    loja_norm = _normalizar_loja(loja)
    grupos_norm = _parse_grupos_clientes(grupos_clientes)
    caminho_movimento, caminho_produto = _caminho_produto_empresa(empresa)
    try:
        assinatura = (_assinatura_arquivo(caminho_movimento), _assinatura_arquivo(caminho_produto))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler a base: {exc}") from exc

    chave = (
        empresa, loja_norm or "", modo_periodo, assinatura, date.today(),
        _assinatura_cortes_escopo(empresa, loja_norm, grupos_norm),
        _assinatura_arquivo_opcional(_caminho_tags_clientes(empresa)),
        _assinatura_arquivo_opcional(CAMINHO_BANCO_CENTRALIZADO_TAGS),
    )
    with _cache_painel_clientes_lock:
        cacheado = _cache_painel_clientes.get(chave)
        if cacheado is not None:
            _cache_painel_clientes.move_to_end(chave)
            return cacheado
    em_disco = _tela_do_disco(empresa, "clientes-painel", chave)
    if em_disco is not None:
        _guardar_lru(_cache_painel_clientes, _cache_painel_clientes_lock, chave, em_disco,
                     _CACHE_PAINEL_CLIENTES_MAX)
        return em_disco

    estado_tags = _ler_tags_clientes(empresa, loja=loja)
    config = _ler_config_escopo(empresa, loja) or {}
    df, _linhas_vazias = _carregar_base_telas(
        empresa, loja=loja, grupos_clientes=grupos_norm,
    )
    resultado = montar_painel_clientes(
        df,
        tags=estado_tags.get("tags") or {},
        catalogo=estado_tags.get("catalogo") or [],
        cortes=config.get("cortes_clientes"),
        clientes_balcao=estado_tags.get("clientes_balcao") or [],
        modo_periodo=modo_periodo,
    )
    resultado["empresa"] = empresa
    resultado["loja"] = _chave_escopo_loja(loja) or None

    with _cache_painel_clientes_lock:
        _cache_painel_clientes[chave] = resultado
        _cache_painel_clientes.move_to_end(chave)
        while len(_cache_painel_clientes) > _CACHE_PAINEL_CLIENTES_MAX:
            _cache_painel_clientes.popitem(last=False)
    _tela_para_disco(empresa, "clientes-painel", chave, resultado)
    return resultado


@app.get("/api/clientes/{empresa}/potencial-produtos")
def obter_potencial_produtos_cliente(
    empresa: str,
    cliente: str,
    loja: Optional[str] = None,
    modo_periodo: str = "fechados",
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Top produtos do cliente nos meses de maior receita — o detalhe por trás
    do ranking "Maiores potenciais de compra" (mesma janela de `_potencial_compra`).
    """
    empresa = _validar_nome_empresa(empresa)
    df, _linhas_vazias = _carregar_base_telas(
        empresa, loja=loja, grupos_clientes=_parse_grupos_clientes(grupos_clientes),
    )
    resultado = top_produtos_potencial_cliente(df, cliente, modo_periodo=modo_periodo)
    resultado["empresa"] = empresa
    resultado["loja"] = _chave_escopo_loja(loja) or None
    return resultado


@app.get("/api/clientes/{empresa}/causa-migracao")
def obter_causa_migracao_cliente(
    empresa: str,
    cliente: str,
    loja: Optional[str] = None,
    modo_periodo: str = "fechados",
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Eventos de migração de faixa ABC de um cliente (subiu/desceu), com a
    causa provável de cada um — o detalhe por trás do score em "Pior cauda"/
    "Melhores scores".
    """
    empresa = _validar_nome_empresa(empresa)
    config = _ler_config_escopo(empresa, loja) or {}
    df, _linhas_vazias = _carregar_base_telas(
        empresa, loja=loja, grupos_clientes=_parse_grupos_clientes(grupos_clientes),
    )
    resultado = causa_migracao_cliente(
        df, cliente, cortes=config.get("cortes_clientes"), modo_periodo=modo_periodo,
    )
    resultado["empresa"] = empresa
    resultado["loja"] = _chave_escopo_loja(loja) or None
    return resultado


# Painel de diagnóstico: o cálculo custa ~2s na IBAD (o comparativo ano a ano
# domina), então o resultado é cacheado como o da tela Estoque — assinatura dos
# arquivos, escopo e cortes na chave. `date.today()` entra porque "meses
# fechados" muda de referência quando o mês vira.
_CACHE_DIAGNOSTICO_MAX = 8
_cache_diagnostico: OrderedDict[tuple, dict] = OrderedDict()
_cache_diagnostico_lock = threading.Lock()


@app.get("/api/diagnostico/{empresa}")
def obter_painel_diagnostico(
    empresa: str,
    loja: Optional[str] = None,
    modo_periodo: str = "fechados",
    grupos_clientes: Optional[str] = None,
    usuario: str = Depends(exigir_login),
):
    """Diagnóstico da carteira: a tensão do período, a decomposição ano a ano
    e o que puxou o mês para cima e para baixo."""
    empresa = _validar_nome_empresa(empresa)
    loja_norm = _normalizar_loja(loja)
    grupos_norm = _parse_grupos_clientes(grupos_clientes)
    caminho_movimento, caminho_produto = _caminho_produto_empresa(empresa)
    try:
        assinatura = (_assinatura_arquivo(caminho_movimento), _assinatura_arquivo(caminho_produto))
    except OSError as exc:
        raise HTTPException(status_code=400, detail=f"Não foi possível ler a base: {exc}") from exc

    chave = (
        empresa, loja_norm or "", modo_periodo, assinatura, date.today(),
        _assinatura_cortes_escopo(empresa, loja_norm, grupos_norm),
    )
    with _cache_diagnostico_lock:
        cacheado = _cache_diagnostico.get(chave)
        if cacheado is not None:
            _cache_diagnostico.move_to_end(chave)
            return cacheado
    em_disco = _tela_do_disco(empresa, "diagnostico", chave)
    if em_disco is not None:
        _guardar_lru(_cache_diagnostico, _cache_diagnostico_lock, chave, em_disco, _CACHE_DIAGNOSTICO_MAX)
        return em_disco

    config = _ler_config_escopo(empresa, loja) or {}
    df, _linhas_vazias = _carregar_base_telas(empresa, loja=loja, grupos_clientes=grupos_norm)
    # Estoque é best-effort: o bloco margem x giro é o único que depende dele
    # (`_margem_giro` já degrada para "indisponível" sem os DataFrames), e uma
    # falha de leitura do PRODUTO.csv não pode derrubar o resto do painel, que
    # não depende de estoque nenhum.
    try:
        estoque, vendas, _lojas = _ler_estoque_vendas(empresa, caminho_produto, loja_norm, grupos_norm)
    except HTTPException:
        estoque, vendas = None, None
    resultado = montar_painel_diagnostico(
        df, modo_periodo=modo_periodo, cortes=config.get("cortes_clientes"),
        estoque=estoque, vendas=vendas,
    )
    resultado["empresa"] = empresa
    resultado["loja"] = _chave_escopo_loja(loja) or None

    with _cache_diagnostico_lock:
        _cache_diagnostico[chave] = resultado
        _cache_diagnostico.move_to_end(chave)
        while len(_cache_diagnostico) > _CACHE_DIAGNOSTICO_MAX:
            _cache_diagnostico.popitem(last=False)
    _tela_para_disco(empresa, "diagnostico", chave, resultado)
    return resultado


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
    total = len(agregado)
    # Tela dedicada precisa carregar catálogo inteiro para filtro local e edição
    # de tags. Mantém teto explícito para impedir respostas sem limite.
    limite = max(1, min(int(limite or 40), 5000))
    agregado = agregado.head(limite)
    receita = pd.to_numeric(agregado["Receita"], errors="coerce").fillna(0.0)
    return {
        "total": total,
        "limitado": total > limite,
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
        _exigir_regeneracao_permitida()
        return _regenerar_base_empresa(nome)
    _pastas_empresa(nome)  # 404 se a empresa não tiver o XLSX na fonte
    return {"ok": True, "empresa": nome}


@app.post("/api/empresas/{nome}/regenerar-base")
def regenerar_base_empresa(nome: str, usuario: str = Depends(exigir_login)):
    """Limpa caches e força reprocessamento direto da fonte (Analisador)."""
    _exigir_regeneracao_permitida()
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


@app.get("/api/dashboard/aplicar-cortes-relatorios")
def obter_aplicar_cortes_relatorios_dashboard():
    """Público — mesma flag do /api/config, sem exigir login."""
    return {"ativo": aplicar_cortes_relatorios()}


@app.post("/api/dashboard/aplicar-cortes-relatorios")
def definir_aplicar_cortes_relatorios_dashboard(corpo: CortesRelatoriosBody):
    db.definir_config_app(CHAVE_APLICAR_CORTES_RELATORIOS, "1" if corpo.ativo else "0")
    return {"ativo": aplicar_cortes_relatorios()}


@app.get("/api/dashboard/empresas")
def listar_empresas_dashboard():
    return _listar_empresas_fonte()


@app.get("/api/dashboard/empresas/{empresa}/lojas")
def listar_lojas_empresa(empresa: str):
    """Lojas da empresa, para o seletor de escopo da barra lateral.

    Sai do `resumo_monitor.json` (poucos KB) e não da base: o seletor aparece em
    toda tela, inclusive no Dashboard público, e carregar o XLSX inteiro para
    preencher um combobox anularia o ganho do summary pré-gerado. Empresa sem
    summary ainda gerado responde lista vazia — a sidebar simplesmente não mostra
    o seletor, em vez de a tela quebrar.
    """
    empresa = _validar_nome_empresa(empresa)
    pasta_trabalho = os.path.join(_exigir_caminho_trabalho(), empresa)
    try:
        resumo = obter_resumo_monitor(pasta_trabalho)
    except Exception:
        logger.error("Falha ao listar lojas de %s:\n%s", empresa, traceback.format_exc())
        return {"lojas": []}
    return {"lojas": list((resumo or {}).get("lojas") or [])}


# ---------------------------------------------------------------------------
# Monitoramento (visão de todas as empresas)
# ---------------------------------------------------------------------------

@app.get("/api/monitor/empresas")
def monitor_empresas(
    metrica: str = "receita",
    meses: int = 12,
    forcar: bool = False,
    empresa: str | None = None,
    loja: str | None = None,
):
    """Uma linha por empresa com a série da métrica pedida e a variação anual.

    Responde SEMPRE 200 com o que conseguiu montar: uma empresa sem base (ou com
    summary corrompido) entra com `estado` próprio em vez de derrubar a tela toda —
    com 59 empresas, a chance de uma estar em manutenção é alta.

    `empresa` restringe a uma única empresa (resposta com 1 item) — é o que o
    combobox de loja do card usa para recalcular só aquele card ao trocar de
    loja, sem reprocessar as demais. `loja`, sozinho ou junto de `empresa`,
    filtra a série pra aquela loja (ver `montar_card`); loja que não existe na
    fonte cai no card com série vazia em vez de erro.
    """
    if metrica not in METRICAS_VALIDAS:
        raise HTTPException(
            status_code=400,
            detail=f"Métrica inválida. Use uma de: {', '.join(sorted(METRICAS_VALIDAS))}.",
        )
    meses = max(1, min(int(meses or 12), 60))

    trabalho_root = _exigir_caminho_trabalho()
    nomes_empresas = [_validar_nome_empresa(empresa)] if empresa else _listar_empresas_fonte()

    cards: list[dict] = []
    for nome in nomes_empresas:
        pasta_trabalho = os.path.join(trabalho_root, nome)
        try:
            resumo = obter_resumo_monitor(pasta_trabalho, forcar=forcar)
        except Exception:
            logger.error("Falha ao resumir %s para o monitor:\n%s", nome, traceback.format_exc())
            cards.append({
                "empresa": nome,
                "estado": "erro",
                "detalhe": "Não foi possível ler os dados desta empresa.",
            })
            continue

        if resumo is None:
            cards.append({
                "empresa": nome,
                "estado": "sem_base",
                "detalhe": "Base ainda não gerada para esta empresa.",
            })
            continue

        # Empresa sem CMV na fonte não entra nas métricas de lucro — mostrar
        # lucro == receita seria dado errado disfarçado de dado certo. Filtro por
        # loja não passa por aqui: o card lida com isso via `indisponivel_por_loja`.
        if metrica in METRICAS_COM_CMV and not loja and not resumo.get("tem_cmv"):
            continue

        cards.append(montar_card(nome, resumo, metrica=metrica, meses=meses, loja=loja or None))

    # Favoritas vão na mesma resposta: a tela precisa das duas coisas para o
    # primeiro render, e duas requisições atrasariam o destaque das favoritas.
    # Consultas de uma única empresa (recomputar 1 card ao trocar de loja) não
    # precisam da lista inteira de favoritas de novo.
    return {
        "metrica": metrica,
        "meses": meses,
        "empresas": cards,
        "favoritas": [] if empresa else _ler_favoritas(),
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
    _exigir_regeneracao_permitida()
    return _regenerar_base_empresa(empresa)


@app.get("/api/dashboard/summary/{empresa}")
def obter_summary_dashboard(empresa: str, loja: Optional[str] = None, grupos_clientes: Optional[str] = None):
    """Serve summary_dashboard.json(.gz) em disco/RAM. Regenera só se a fonte for mais nova."""
    pasta_fonte, pasta_trabalho = _pastas_empresa(empresa)
    try:
        caminho_movimento, caminho_produto, _estoque, _vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    caminho_referencia = str(_caminho_referencia_fonte(caminho_movimento, caminho_produto))
    caminho_summary = _garantir_summary_dashboard_arquivo(
        empresa, pasta_fonte, pasta_trabalho, caminho_referencia,
    )
    return _resposta_summary_arquivo(
        empresa, caminho_summary, pasta_fonte, caminho_referencia,
        loja=loja, grupos_clientes=_parse_grupos_clientes(grupos_clientes),
    )


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


class PainelClienteBody(BaseModel):
    """Cliente monitorado cujo painel PDF será calculado sob demanda."""

    empresa: str
    cliente: str
    loja: Optional[str] = None
    posicao: Optional[int] = None
    total: Optional[int] = None


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
    df, _ = _carregar_base_telas(empresa, loja=loja)
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
    df, _ = _carregar_base_telas(empresa, loja=parametros.loja)
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
# Painel individual de cliente monitorado
# ---------------------------------------------------------------------------

def _slug_arquivo_cliente(nome: str) -> str:
    """Nome curto e seguro para o Content-Disposition do PDF."""
    texto = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^a-zA-Z0-9]+", "-", texto).strip("-").lower()
    return (texto[:64] or "cliente")


@app.post("/api/relatorios/cliente/painel")
def exportar_painel_cliente(
    corpo: PainelClienteBody,
    usuario: str = Depends(exigir_login),
):
    """Gera na hora o painel PDF de um cliente marcado para monitoramento."""
    inicio = time.perf_counter()
    empresa = _validar_nome_empresa(corpo.empresa)
    cliente = str(corpo.cliente or "").strip()
    if not cliente:
        raise HTTPException(status_code=400, detail="Informe o cliente.")
    if len(cliente) > 300:
        raise HTTPException(status_code=400, detail="Nome de cliente inválido.")

    estado_tags = _ler_tags_clientes(empresa, loja=corpo.loja)
    ids_monitoramento = {
        str(item.get("id") or "").strip().lower()
        for item in (estado_tags.get("catalogo") or [])
        if item.get("ativa") and item.get("entra_na_analise")
        and str(item.get("id") or "").strip().lower() != af.TAG_CLIENTE_BALCAO
    }
    tags_cliente = set((estado_tags.get("tags") or {}).get(cliente, []))
    if not tags_cliente.intersection(ids_monitoramento):
        raise HTTPException(
            status_code=400,
            detail="O painel só pode ser gerado para cliente com tag de monitoramento ativa.",
        )

    df, _ = _carregar_base_telas(empresa, loja=corpo.loja, copiar=False)
    try:
        dados = montar_dados_painel_cliente(df, cliente)
    except ErroPainelCliente as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "Falha ao calcular painel do cliente %s para %s:\n%s",
            cliente, usuario, traceback.format_exc(),
        )
        raise HTTPException(status_code=400, detail=f"Falha ao calcular o painel: {exc}") from exc

    arquivo_temp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    caminho_saida = arquivo_temp.name
    arquivo_temp.close()
    try:
        gerar_painel_cliente_pdf(
            caminho_saida,
            dados,
            empresa=empresa,
            loja=_normalizar_loja(corpo.loja),
            posicao=corpo.posicao,
            total=corpo.total,
        )
    except Exception as exc:
        try:
            os.remove(caminho_saida)
        except OSError:
            pass
        logger.error(
            "Falha ao renderizar painel do cliente %s para %s:\n%s",
            cliente, usuario, traceback.format_exc(),
        )
        raise HTTPException(status_code=500, detail=f"Falha ao gerar o PDF: {exc}") from exc

    logger.info(
        "Painel do cliente %s gerado para %s em %.2fs.",
        cliente, usuario, time.perf_counter() - inicio,
    )
    return FileResponse(
        caminho_saida,
        media_type="application/pdf",
        filename=f"painel-cliente-{_slug_arquivo_cliente(cliente)}.pdf",
        background=BackgroundTask(os.remove, caminho_saida),
    )


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
    # Regras de produto: derivadas no cálculo, não gravadas como lista de nomes.
    desconsiderar_demais_produtos: bool = False
    desconsiderar_nao_harmonizados: bool = False
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
    corte_produtos: float = 80.0,
    desconsiderar_demais_produtos: bool = False,
    desconsiderar_nao_harmonizados: bool = False,
) -> pd.DataFrame:
    # Motor somente lê o DataFrame; compartilha master cacheado. Quando há
    # exclusão, o filtro já materializa DataFrame separado.
    df, _ = _carregar_base(empresa, loja=loja, copiar=False)
    if not desconsiderar_demais_produtos and not desconsiderar_nao_harmonizados:
        # Caminho comum: nada de curva aqui — o motor já monta a dele.
        mascara_manual = _mascara_produtos_excluidos(df, produtos_excluidos)
        return df.loc[~mascara_manual].copy() if bool(mascara_manual.any()) else df
    classificado, mascara_manual, mascara_nao_harm = _curva_produtos(
        df, produtos_excluidos, float(corte_produtos), desconsiderar_nao_harmonizados,
    )
    fora = mascara_manual | mascara_nao_harm
    if desconsiderar_demais_produtos:
        demais = set(
            classificado.loc[classificado["Faixa"] == "Demais", "descricao"].astype(str)
        )
        if demais:
            fora = fora | df["descricao"].astype(str).isin(demais)
    if bool(fora.any()):
        df = df.loc[~fora].copy()
    return df


CHAVES_ALVOS = frozenset({"mais_atacado", "liquidez"})


def _filtrar_loja_coluna(
    df: pd.DataFrame, loja: Optional[str], coluna: str, origem: str,
) -> pd.DataFrame:
    """Filtra `df` por uma ou mais lojas. Escopo vazio = todas.

    Usado nos Alvos, que leem arquivos próprios da fonte (nomes de coluna de loja
    diferentes do schema canônico: `Loja` no estoque, `Nome_Loja` nas vendas).
    """
    nomes = _normalizar_lojas(loja)
    if not nomes:
        return df
    if df is None or df.empty or coluna not in df.columns:
        raise HTTPException(
            status_code=400,
            detail=f"{origem} não tem a coluna '{coluna}' para filtrar por loja.",
        )
    valores = df[coluna].fillna("").astype(str).str.strip()
    existentes = set(valores.unique().tolist())
    faltantes = [nome for nome in nomes if nome not in existentes]
    if faltantes:
        raise HTTPException(
            status_code=400,
            detail=f"Loja(s) não encontrada(s) em {origem}: {', '.join(faltantes)}.",
        )
    return df.loc[valores.isin(nomes)].copy()


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
        _movimento, _produto, caminho_estoque, caminho_vendas = resolver_arquivos_dados(Path(pasta_fonte))
    except ErroNormalizacao as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    analises: dict[str, pd.DataFrame] = {}

    if "mais_atacado" in chaves:
        # Reutiliza a base já validada e normalizada no cache; antes esta análise
        # relia dezenas de MB mesmo após Dashboard/Analisador carregarem a base.
        df, _linhas_vazias = _carregar_base_empresa(empresa)
        df = _filtrar_loja_coluna(df, loja, "Loja", "MOVIMENTO_ATUAL")
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
            corte_produtos=parametros.corte_produtos,
            desconsiderar_demais_produtos=parametros.desconsiderar_demais_produtos,
            desconsiderar_nao_harmonizados=parametros.desconsiderar_nao_harmonizados,
        )
        if df_filtrado.empty:
            raise HTTPException(
                status_code=400,
                detail="Nenhuma linha restante após aplicar as exclusões de produto.",
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


# ---------------------------------------------------------------------------
# Frontend (SPA)
#
# Quando existe um build do dashboard, o próprio backend o serve — é o que
# permite distribuir o Prisma como um executável único, sem depender de servidor
# web externo na máquina do usuário. Em desenvolvimento (sem `npm run build`)
# nada é montado e o Vite continua servindo o front na 5173 com proxy para /api.
#
# Este bloco precisa ficar no FIM do arquivo: a rota curinga abaixo casa com
# qualquer GET, então qualquer rota declarada depois dela nunca seria alcançada.
# ---------------------------------------------------------------------------

PASTA_WEB = os.path.realpath(pasta_web())
INDEX_WEB = os.path.join(PASTA_WEB, "index.html")


def _arquivo_sob(raiz: str, caminho_relativo: str) -> Optional[str]:
    """Caminho absoluto do arquivo dentro de `raiz`, ou None se não existir ou
    escapar dela (ex.: `../../dados_locais/app.db`)."""
    destino = os.path.realpath(os.path.join(raiz, caminho_relativo))
    if destino != raiz and not destino.startswith(raiz + os.sep):
        return None
    return destino if os.path.isfile(destino) else None


if os.path.isfile(INDEX_WEB):
    logger.info("Servindo o frontend a partir de %s", PASTA_WEB)

    @app.get("/{caminho:path}")
    def servir_frontend(caminho: str):
        # Rota /api inexistente é erro de API, não navegação — não devolver HTML.
        if caminho == "api" or caminho.startswith("api/"):
            raise HTTPException(status_code=404, detail="Rota não encontrada.")

        arquivo = _arquivo_sob(PASTA_WEB, caminho) if caminho else None
        if arquivo:
            return FileResponse(arquivo)

        # Pedido de arquivo que não existe precisa dar 404 — devolver o
        # index.html faria o fetch receber HTML com status 200 e quebrar no
        # JSON.parse.
        if os.path.splitext(caminho)[1]:
            raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

        # Qualquer outra rota é rota do BrowserRouter (/analisador, /config,
        # /monitor, /login): devolve o index e o React resolve no cliente.
        return FileResponse(INDEX_WEB, headers={"Cache-Control": "no-store"})
else:
    logger.warning(
        "Build do frontend não encontrado em %s — o backend vai servir apenas /api. "
        "Rode `npm run build` em dashboard/ para servir a interface daqui.",
        PASTA_WEB,
    )
