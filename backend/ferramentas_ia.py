"""Ferramentas que o chat do Assistente pode chamar para consultar a base.

O chat antes só lia um retrato montado antes da pergunta (MDs + resumo). Com as
ferramentas, o modelo busca o que a pergunta pede: a ficha de um cliente, a
compra sugerida de um produto, uma consulta SQL nas vendas.

Como chega aqui: o ``claude -p`` sobe o servidor MCP ``mcp_prisma.py``, que
repassa cada chamada a ``POST /api/ia/ferramentas/executar`` neste app. Quatro
decisões:

- **A empresa não é argumento.** Ela vem do token da conversa
  (``criar_sessao``), emitido pelo backend na hora da pergunta. O modelo não
  consegue pedir dados de outra empresa, nem por engano.
- **Consultas prontas chamam as rotas das telas**, com os parâmetros de tela
  ("todas as lojas", período fechado): o número é o da tela, e sai do cache.
- **SQL só lê, e só tabelas em memória.** ``vendas``, ``estoque`` e ``despesas``
  são registradas numa conexão DuckDB descartável; depois o acesso a arquivos
  é desligado e a configuração travada (sem ``read_parquet``, ``COPY``,
  ``ATTACH``, ``INSTALL``). A fonte continua intocável.
- **Resposta curta.** Listas cortadas e texto limitado: o resultado volta para
  o contexto do modelo, e uma tela de 500 SKUs estouraria a conversa.
"""

from __future__ import annotations

import ast
import json
import logging
import math
import operator
import re
import secrets
import threading
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_LINHAS_SQL = 200
TIMEOUT_SQL_SEGUNDOS = 20
MAX_ITENS_LISTA = 15
MAX_RESULTADO_CARACTERES = 24_000
VALIDADE_SESSAO_SEGUNDOS = 15 * 60


class ErroFerramenta(ValueError):
    """Falha que volta ao modelo como texto — ele pode corrigir e tentar de novo."""


# ---------------------------------------------------------------------------
# Sessões: token da conversa → empresa
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Sessao:
    empresa: str
    expira_em: float


_sessoes: dict[str, Sessao] = {}
_sessoes_lock = threading.Lock()


def criar_sessao(empresa: str) -> str:
    agora = time.monotonic()
    token = secrets.token_urlsafe(24)
    with _sessoes_lock:
        for chave in [k for k, s in _sessoes.items() if s.expira_em < agora]:
            del _sessoes[chave]
        _sessoes[token] = Sessao(empresa, agora + VALIDADE_SESSAO_SEGUNDOS)
    return token


def encerrar_sessao(token: str) -> None:
    with _sessoes_lock:
        _sessoes.pop(token, None)


def empresa_da_sessao(token: str) -> str | None:
    with _sessoes_lock:
        sessao = _sessoes.get(token)
    if sessao is None or sessao.expira_em < time.monotonic():
        return None
    return sessao.empresa


# ---------------------------------------------------------------------------
# Catálogo
# ---------------------------------------------------------------------------

TELAS_RESUMO = {
    "clientes": "Clientes",
    "diagnostico": "Diagnóstico",
    "vendedores": "Vendedores",
    "estoque": "Estoque",
    "compras": "Compras",
    "a_precificar": "A precificar",
    "pos_precificacao": "Pós-precificação",
    "despesas": "Despesas",
}

ESQUEMA_SQL = """Tabelas (DuckDB, só leitura, só esta empresa):
- vendas(data DATE, mes VARCHAR 'AAAA-MM', ano INT, loja, tipo_movimento, cliente, vendedor,
  sku, referencia, produto, fabricante, quantidade DOUBLE, receita DOUBLE, cmv DOUBLE, lucro_bruto DOUBLE)
  Uma linha por item vendido. Já vai só até ontem. produto = descrição harmonizada (família).
  Devolução entra com quantidade/receita negativas.
- estoque(loja, sku, referencia, produto, fabricante, quantidade DOUBLE, custo_medio DOUBLE,
  preco_medio_venda DOUBLE, ultimo_custo DOUBLE, valor_estoque DOUBLE)
  Posição atual por loja e SKU.
- despesas(loja, descricao, categoria, fornecedor, vencimento DATE, ano INT, mes INT, valor DOUBLE,
  compra_de_mercadoria BOOLEAN)  — Controladoria; pode não existir para a empresa.
  compra_de_mercadoria = categoria "Mercadoria Revenda": já está no CMV, exclua ao somar despesas.
Margem % = lucro_bruto / receita * 100. Resultado limitado a 200 linhas."""

FERRAMENTAS: list[dict[str, Any]] = [
    {
        "nome": "consultar_sql",
        "descricao": (
            "Consulta SQL (SELECT/WITH) nas vendas, no estoque e nas despesas desta empresa. "
            "Use para perguntas que as outras ferramentas não cobrem: um cliente num período, "
            "um fabricante numa loja, evolução mensal, rankings sob medida.\n" + ESQUEMA_SQL
        ),
        "parametros": {
            "type": "object",
            "properties": {"sql": {"type": "string", "description": "Uma única consulta SELECT ou WITH."}},
            "required": ["sql"],
        },
    },
    {
        "nome": "buscar_clientes",
        "descricao": "Procura clientes pelo nome (parte do nome serve). Use antes da ficha para achar a grafia exata.",
        "parametros": {
            "type": "object",
            "properties": {"texto": {"type": "string"}},
            "required": ["texto"],
        },
    },
    {
        "nome": "ficha_cliente",
        "descricao": (
            "Ficha de um cliente (nome exato): produtos que comprava no potencial × compra atual, "
            "e a causa de ter mudado de faixa (produtos que caíram)."
        ),
        "parametros": {
            "type": "object",
            "properties": {"cliente": {"type": "string"}},
            "required": ["cliente"],
        },
    },
    {
        "nome": "ficha_vendedor",
        "descricao": "Ficha de um vendedor (nome exato): receita, clientes e produtos, último mês × média.",
        "parametros": {
            "type": "object",
            "properties": {"vendedor": {"type": "string"}},
            "required": ["vendedor"],
        },
    },
    {
        "nome": "compra_produto",
        "descricao": (
            "Compra sugerida de um produto (descrição) de um fabricante, por SKU e loja, "
            "com venda mensal, estoque e estoque alvo — a tela Compras."
        ),
        "parametros": {
            "type": "object",
            "properties": {"descricao": {"type": "string"}, "fabricante": {"type": "string"}},
            "required": ["descricao", "fabricante"],
        },
    },
    {
        "nome": "precificacao_produto",
        "descricao": (
            "Precificação de um produto (descrição), opcionalmente de um fabricante: margem semanal, "
            "SKUs sinalizados, alvo e reajuste — a tela A precificar."
        ),
        "parametros": {
            "type": "object",
            "properties": {"descricao": {"type": "string"}, "fabricante": {"type": "string"}},
            "required": ["descricao"],
        },
    },
    {
        "nome": "historico_precificacao",
        "descricao": "Antes × depois da precificação de uma família (nivel=familia) ou de um SKU (nivel=sku).",
        "parametros": {
            "type": "object",
            "properties": {"nivel": {"type": "string", "enum": ["familia", "sku"]}, "nome": {"type": "string"}},
            "required": ["nivel", "nome"],
        },
    },
    {
        "nome": "detalhe_despesas",
        "descricao": "Lançamentos da Controladoria, filtráveis por mês (AAAA-MM) e categoria.",
        "parametros": {
            "type": "object",
            "properties": {
                "periodo": {"type": "string", "description": "AAAA-MM"},
                "categoria": {"type": "string"},
                "limite": {"type": "integer", "minimum": 1, "maximum": 100},
            },
        },
    },
    {
        "nome": "resumo_tela",
        "descricao": "Resumo de uma tela do Prisma, como o usuário a vê (todas as lojas, período fechado).",
        "parametros": {
            "type": "object",
            "properties": {"tela": {"type": "string", "enum": list(TELAS_RESUMO)}},
            "required": ["tela"],
        },
    },
    {
        "nome": "calcular",
        "descricao": "Calcula uma expressão aritmética (+ - * / ** %, parênteses, round, abs, min, max, sum).",
        "parametros": {
            "type": "object",
            "properties": {"expressao": {"type": "string"}},
            "required": ["expressao"],
        },
    },
]

_POR_NOME = {f["nome"]: f for f in FERRAMENTAS}


def catalogo() -> list[dict]:
    """Formato MCP (``tools/list``)."""
    return [
        {"name": f["nome"], "description": f["descricao"], "inputSchema": f["parametros"]}
        for f in FERRAMENTAS
    ]


def descrever_chamada(nome: str, argumentos: dict | None) -> str:
    """O que o agente está fazendo, em linguagem de quem usa a tela."""
    a = argumentos or {}
    nome = nome.split("__")[-1]  # mcp__prisma__ficha_cliente → ficha_cliente
    if nome == "consultar_sql":
        sql = str(a.get("sql") or "").lower()
        tabelas = [t for t in ("vendas", "estoque", "despesas") if re.search(rf"\b{t}\b", sql)]
        return f"Consultando {' e '.join(tabelas) if tabelas else 'a base'}"
    textos: dict[str, Callable[[], str]] = {
        "buscar_clientes": lambda: f"Procurando clientes com “{a.get('texto', '')}”",
        "ficha_cliente": lambda: f"Abrindo a ficha de {a.get('cliente', 'um cliente')}",
        "ficha_vendedor": lambda: f"Abrindo a ficha do vendedor {a.get('vendedor', '')}".strip(),
        "compra_produto": lambda: f"Vendo a compra sugerida de {a.get('descricao', '')} ({a.get('fabricante', '')})",
        "precificacao_produto": lambda: f"Vendo a precificação de {a.get('descricao', '')}",
        "historico_precificacao": lambda: f"Vendo o antes e depois da precificação de {a.get('nome', '')}",
        "detalhe_despesas": lambda: "Consultando os lançamentos de despesas",
        "resumo_tela": lambda: f"Lendo a tela {TELAS_RESUMO.get(str(a.get('tela')), a.get('tela', ''))}",
        "calcular": lambda: "Fazendo a conta",
    }
    return textos.get(nome, lambda: "Consultando o Prisma")()


# ---------------------------------------------------------------------------
# Resultado enxuto
# ---------------------------------------------------------------------------

_CHAVES_PESADAS = {"serie_diaria", "celulas", "venda_mensal", "faixas_disponiveis", "linha_tempo", "marcadores"}


def _enxugar(valor: Any, max_lista: int = MAX_ITENS_LISTA) -> Any:
    if isinstance(valor, dict):
        return {k: _enxugar(v, max_lista) for k, v in valor.items() if k not in _CHAVES_PESADAS}
    if isinstance(valor, list):
        itens = [_enxugar(v, max_lista) for v in valor[:max_lista]]
        if len(valor) > max_lista:
            itens.append(f"… mais {len(valor) - max_lista} itens não mostrados")
        return itens
    if isinstance(valor, float):
        return round(valor, 4) if math.isfinite(valor) else None
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    return valor


def _serializar(resultado: Any) -> str:
    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(texto) > MAX_RESULTADO_CARACTERES:
        texto = texto[:MAX_RESULTADO_CARACTERES] + " …[resultado cortado: refine a consulta]"
    return texto


# ---------------------------------------------------------------------------
# SQL
# ---------------------------------------------------------------------------

def _limpar_sql(sql: str) -> str:
    sem_comentarios = re.sub(r"--[^\n]*|/\*.*?\*/", " ", sql or "", flags=re.S).strip().rstrip(";").strip()
    if not sem_comentarios:
        raise ErroFerramenta("Consulta vazia.")
    if ";" in sem_comentarios:
        raise ErroFerramenta("Envie uma única consulta, sem ';' no meio.")
    if not re.match(r"(?is)^(select|with)\b", sem_comentarios):
        raise ErroFerramenta("Só consultas SELECT ou WITH são aceitas.")
    return sem_comentarios


def executar_sql(
    sql: str,
    tabelas: dict[str, Any],
    *,
    visoes: dict[str, str] | None = None,
    timeout: float = TIMEOUT_SQL_SEGUNDOS,
) -> dict:
    """Roda a consulta numa conexão em memória só com ``tabelas`` (DataFrames).

    ``visoes`` são criadas antes do bloqueio (nome → SELECT sobre as tabelas),
    para dar nomes de coluna legíveis sem copiar a base.
    """
    import duckdb

    consulta = _limpar_sql(sql)
    conexao = duckdb.connect(":memory:")
    try:
        for nome, df in tabelas.items():
            conexao.register(nome, df)
        for nome, select in (visoes or {}).items():
            conexao.execute(f"create view {nome} as {select}")
        conexao.execute("SET enable_external_access = false")
        conexao.execute("SET lock_configuration = true")

        relogio = threading.Timer(timeout, conexao.interrupt)
        relogio.start()
        try:
            cursor = conexao.execute(f"select * from ({consulta}) limit {MAX_LINHAS_SQL + 1}")
            colunas = [d[0] for d in cursor.description]
            linhas = cursor.fetchall()
        except duckdb.InterruptException as exc:
            raise ErroFerramenta(f"A consulta passou de {timeout:.0f} s. Simplifique ou filtre mais.") from exc
        except duckdb.Error as exc:
            raise ErroFerramenta(f"Erro no SQL: {str(exc).splitlines()[0][:300]}") from exc
        finally:
            relogio.cancel()
    finally:
        conexao.close()

    cortado = len(linhas) > MAX_LINHAS_SQL
    return {
        "colunas": colunas,
        "linhas": [[_enxugar(v) for v in linha] for linha in linhas[:MAX_LINHAS_SQL]],
        "total_linhas": min(len(linhas), MAX_LINHAS_SQL),
        "cortado": cortado,
        **({"aviso": f"Mais de {MAX_LINHAS_SQL} linhas; agregue ou filtre."} if cortado else {}),
    }


# Colunas da base do app → nomes da tabela `vendas`.
_VISAO_VENDAS = """select
    cast("Data_Venda_Diaria" as date) as data,
    cast("Periodo_Mensal" as varchar) as mes,
    cast("Ano" as integer) as ano,
    "Loja" as loja,
    "TIPO_MOVIMENTO" as tipo_movimento,
    "Cliente" as cliente,
    nullif(trim(cast("Vendedor" as varchar)), '') as vendedor,
    cast("Código Interno" as varchar) as sku,
    cast("Código de referêcia" as varchar) as referencia,
    "descricao" as produto,
    "NOME_FABRICANTE" as fabricante,
    cast("QTD" as double) as quantidade,
    cast("Receita" as double) as receita,
    cast("CMV" as double) as cmv,
    cast("Receita" as double) - cast("CMV" as double) as lucro_bruto
from base_vendas"""

_VISAO_ESTOQUE = """select
    "Loja" as loja,
    cast("CODIGO_INTERNO_PRODUTO" as varchar) as sku,
    cast("CODIGO_REFERENCIA_PRODUTO" as varchar) as referencia,
    "descricao" as produto,
    "NOME_FABRICANTE" as fabricante,
    cast("Qtd_estoque" as double) as quantidade,
    cast("Preço_médio_cmv" as double) as custo_medio,
    cast("Preço_médio_de_venda" as double) as preco_medio_venda,
    cast("Último_custo" as double) as ultimo_custo,
    cast("Qtd_estoque" as double) * cast("Preço_médio_cmv" as double) as valor_estoque
from base_estoque"""

_VISAO_DESPESAS = """select
    "ID_LOJA" as loja,
    "DESCRICAO" as descricao,
    "DESCRICAO_HARMONIZADA" as categoria,
    "FORNECEDOR" as fornecedor,
    cast("DATA_VENC" as date) as vencimento,
    cast("ANO" as integer) as ano,
    cast("MES" as integer) as mes,
    cast("VALOR" as double) as valor,
    lower(trim(coalesce("DESCRICAO_HARMONIZADA", ''))) = 'mercadoria revenda' as compra_de_mercadoria
from base_despesas"""


def _tabelas_da_empresa(empresa: str) -> tuple[dict[str, Any], dict[str, str]]:
    import consulta_parquet
    import main

    base, _ = main._carregar_base_empresa(empresa)
    tabelas: dict[str, Any] = {"base_vendas": base}
    visoes = {"vendas": _VISAO_VENDAS}
    fonte = Path(main._resolver_caminho_fonte())
    produto = fonte / empresa / f"{empresa}_PRODUTO.parquet"
    try:
        estoque, _, _ = main._ler_estoque_vendas(empresa, produto, None)
        tabelas["base_estoque"] = estoque
        visoes["estoque"] = _VISAO_ESTOQUE
    except Exception as exc:  # noqa: BLE001 — sem estoque o SQL de vendas ainda vale
        logger.warning("Estoque indisponível para SQL empresa=%s tipo=%s", empresa, type(exc).__name__)
    controladoria = fonte / empresa / f"{empresa}_CONTROLADORIA.parquet"
    if controladoria.is_file():
        tabelas["base_despesas"] = consulta_parquet.consultar("select * from read_parquet(?)", [str(controladoria)])
        visoes["despesas"] = _VISAO_DESPESAS
    return tabelas, visoes


# ---------------------------------------------------------------------------
# Calculadora
# ---------------------------------------------------------------------------

_OPERADORES = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod, ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}
_FUNCOES = {"round": round, "abs": abs, "min": min, "max": max, "sum": sum}


def calcular(expressao: str) -> float:
    """Aritmética sem ``eval``: só números, operadores e as funções acima."""
    def avaliar(no: ast.AST) -> Any:
        if isinstance(no, ast.Expression):
            return avaliar(no.body)
        if isinstance(no, ast.Constant) and isinstance(no.value, (int, float)):
            return no.value
        if isinstance(no, ast.BinOp) and type(no.op) in _OPERADORES:
            direita = avaliar(no.right)
            if isinstance(no.op, ast.Pow) and abs(direita) > 100:
                raise ErroFerramenta("Expoente grande demais.")
            return _OPERADORES[type(no.op)](avaliar(no.left), direita)
        if isinstance(no, ast.UnaryOp) and type(no.op) in _OPERADORES:
            return _OPERADORES[type(no.op)](avaliar(no.operand))
        if isinstance(no, (ast.List, ast.Tuple)):
            return [avaliar(e) for e in no.elts]
        if isinstance(no, ast.Call) and isinstance(no.func, ast.Name) and no.func.id in _FUNCOES and not no.keywords:
            return _FUNCOES[no.func.id](*[avaliar(a) for a in no.args])
        raise ErroFerramenta("Expressão não permitida: use só números, operadores e round/abs/min/max/sum.")

    texto = (expressao or "").replace(",", ".") if re.fullmatch(r"[\d\s.,+\-*/()%]*", expressao or "") else (expressao or "")
    try:
        arvore = ast.parse(texto, mode="eval")
    except SyntaxError as exc:
        raise ErroFerramenta("Expressão inválida.") from exc
    try:
        resultado = avaliar(arvore)
    except ZeroDivisionError as exc:
        raise ErroFerramenta("Divisão por zero.") from exc
    return round(float(resultado), 6)


# ---------------------------------------------------------------------------
# Execução
# ---------------------------------------------------------------------------

def _rota(chamada: Callable[[], Any]) -> Any:
    """Chama uma rota das telas; HTTP 4xx vira mensagem para o modelo."""
    from fastapi import HTTPException

    try:
        return chamada()
    except HTTPException as exc:
        raise ErroFerramenta(str(exc.detail)) from exc


def _executar(empresa: str, nome: str, a: dict) -> Any:
    import main

    u = "assistente-ia"
    if nome == "consultar_sql":
        tabelas, visoes = _tabelas_da_empresa(empresa)
        return executar_sql(str(a.get("sql") or ""), tabelas, visoes=visoes)
    if nome == "calcular":
        return {"resultado": calcular(str(a.get("expressao") or ""))}
    if nome == "buscar_clientes":
        return _rota(lambda: main.buscar_clientes(q=str(a.get("texto") or ""), empresa=empresa, loja=None, limite=20, usuario=u))
    if nome == "ficha_cliente":
        cliente = str(a.get("cliente") or "")
        ficha: dict[str, Any] = {"cliente": cliente}
        for chave, rota in (("potencial_produtos", main.obter_potencial_produtos_cliente),
                            ("causa_migracao", main.obter_causa_migracao_cliente)):
            try:
                ficha[chave] = _rota(lambda rota=rota: rota(empresa, cliente, None, "fechados", None, u))
            except ErroFerramenta as exc:
                ficha[chave] = {"erro": str(exc)}
        return ficha
    if nome == "ficha_vendedor":
        return _rota(lambda: main.obter_ficha_vendedor(empresa, str(a.get("vendedor") or ""), None, "fechados", None, u))
    if nome == "compra_produto":
        return _rota(lambda: main.obter_produto_compras(
            empresa, str(a.get("descricao") or ""), str(a.get("fabricante") or ""),
            None, "imediato", "impulsionado", False, None, u,
        ))
    if nome == "precificacao_produto":
        return _rota(lambda: main.obter_par_a_precificar(empresa, str(a.get("descricao") or ""), a.get("fabricante") or None, u))
    if nome == "historico_precificacao":
        return _rota(lambda: main.obter_item_historico_precificacao(
            empresa, str(a.get("nivel") or "familia"), str(a.get("nome") or ""), 180, None, None, u,
        ))
    if nome == "detalhe_despesas":
        limite = max(1, min(int(a.get("limite") or 50), 100))
        return _rota(lambda: main.obter_detalhe_despesas(empresa, None, a.get("periodo") or None, a.get("categoria") or None, limite, u))
    if nome == "resumo_tela":
        tela = str(a.get("tela") or "")
        chamadas: dict[str, Callable[[], Any]] = {
            "clientes": lambda: main.obter_painel_clientes(empresa, None, "fechados", None, u),
            "diagnostico": lambda: main.obter_painel_diagnostico(empresa, None, "fechados", None, u),
            "vendedores": lambda: main.listar_vendedores(empresa, None, "fechados", None, u),
            "estoque": lambda: main.obter_resumo_estoque(empresa, None, 6, True, None, u),
            "compras": lambda: main.obter_compras(empresa, None, "imediato", "impulsionado", False, None, None, True, 15, None, u),
            "a_precificar": lambda: main.obter_a_precificar(empresa, u),
            "pos_precificacao": lambda: main.obter_historico_precificacao(empresa, 180, None, None, "familia", False, None, u),
            "despesas": lambda: main.obter_resumo_despesas(empresa, None, 12, True, u),
        }
        if tela not in chamadas:
            raise ErroFerramenta(f"Tela desconhecida. Use uma de: {', '.join(chamadas)}.")
        return _rota(chamadas[tela])
    raise ErroFerramenta(f"Ferramenta desconhecida: {nome}.")


def executar(empresa: str, nome: str, argumentos: dict | None) -> tuple[str, bool]:
    """Roda a ferramenta; devolve (texto para o modelo, houve_erro)."""
    nome = nome.split("__")[-1]
    if nome not in _POR_NOME:
        return f"Ferramenta desconhecida: {nome}.", True
    inicio = time.monotonic()
    try:
        resultado = _executar(empresa, nome, dict(argumentos or {}))
        texto, erro = _serializar(_enxugar(resultado)), False
    except ErroFerramenta as exc:
        texto, erro = str(exc), True
    except Exception as exc:  # noqa: BLE001 — o modelo recebe um erro legível, não um 500
        logger.exception("Ferramenta IA falhou nome=%s empresa=%s", nome, empresa)
        texto, erro = f"A ferramenta falhou ({type(exc).__name__}). Tente outro caminho.", True
    logger.info(
        "Ferramenta IA nome=%s empresa=%s erro=%s segundos=%.2f", nome, empresa, erro, time.monotonic() - inicio,
    )
    return texto, erro
