"""Ferramentas do chat: SQL blindado, calculadora, sessões, MCP e rota."""

from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

import ferramentas_ia
import main
import mcp_prisma
from ferramentas_ia import ErroFerramenta, calcular, executar_sql


def _vendas() -> dict:
    return {"base": pd.DataFrame({"cliente": ["A", "A", "B"], "receita": [10.0, 5.0, 7.0]})}


def test_sql_agrega_nas_tabelas_registradas():
    resultado = executar_sql(
        "select cliente, sum(receita) total from vendas group by 1 order by 1",
        _vendas(), visoes={"vendas": "select * from base"},
    )
    assert resultado["colunas"] == ["cliente", "total"]
    assert resultado["linhas"] == [["A", 15.0], ["B", 7.0]]
    assert resultado["cortado"] is False


@pytest.mark.parametrize("sql", [
    "select * from read_parquet('C:/qualquer.parquet')",
    "select * from read_csv('dados.csv')",
])
def test_sql_nao_le_arquivos(sql):
    with pytest.raises(ErroFerramenta, match="Erro no SQL"):
        executar_sql(sql, _vendas())


@pytest.mark.parametrize("sql", [
    "delete from base",
    "copy base to 'x.csv'",
    "select 1; select 2",
    "   ",
])
def test_sql_so_aceita_uma_consulta_de_leitura(sql):
    with pytest.raises(ErroFerramenta):
        executar_sql(sql, _vendas())


def test_sql_corta_em_200_linhas():
    tabelas = {"base": pd.DataFrame({"n": range(500)})}
    resultado = executar_sql("select n from base", tabelas)
    assert resultado["total_linhas"] == ferramentas_ia.MAX_LINHAS_SQL
    assert resultado["cortado"] is True


def test_calculadora_aceita_virgula_decimal_e_recusa_codigo():
    assert calcular("(804588,60 - 910659,72) / 910659,72 * 100") == pytest.approx(-11.6477, abs=1e-4)
    assert calcular("round(sum([1, 2, 3.5]), 1)") == 6.5
    with pytest.raises(ErroFerramenta):
        calcular("__import__('os').system('dir')")
    with pytest.raises(ErroFerramenta):
        calcular("1/0")


def test_sessao_fixa_a_empresa_e_expira_ao_encerrar():
    token = ferramentas_ia.criar_sessao("Peca.com")
    assert ferramentas_ia.empresa_da_sessao(token) == "Peca.com"
    ferramentas_ia.encerrar_sessao(token)
    assert ferramentas_ia.empresa_da_sessao(token) is None
    assert ferramentas_ia.empresa_da_sessao("inventado") is None


def test_descricao_do_passo_em_linguagem_de_tela():
    assert ferramentas_ia.descrever_chamada("mcp__prisma__ficha_cliente", {"cliente": "MCAR"}) == "Abrindo a ficha de MCAR"
    assert ferramentas_ia.descrever_chamada(
        "consultar_sql", {"sql": "select * from vendas join estoque using (sku)"},
    ) == "Consultando vendas e estoque"


def test_ferramenta_desconhecida_volta_como_erro_para_o_modelo():
    texto, erro = ferramentas_ia.executar("Peca.com", "apagar_tudo", {})
    assert erro is True and "desconhecida" in texto


def test_mcp_responde_protocolo_e_lista_catalogo():
    inicio = mcp_prisma.responder({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                   "params": {"protocolVersion": "2025-06-18"}})
    assert inicio["result"]["capabilities"] == {"tools": {}}
    assert mcp_prisma.responder({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    lista = mcp_prisma.responder({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    nomes = {f["name"] for f in lista["result"]["tools"]}
    assert {"consultar_sql", "ficha_cliente", "calcular"} <= nomes
    desconhecido = mcp_prisma.responder({"jsonrpc": "2.0", "id": 3, "method": "resources/list"})
    assert desconhecido["error"]["code"] == -32601


def test_mcp_repassa_chamada_ao_prisma(monkeypatch):
    monkeypatch.setattr(mcp_prisma, "_chamar_prisma", lambda nome, args: (f"{nome}:{json.dumps(args)}", False))
    resposta = mcp_prisma.responder({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                                     "params": {"name": "calcular", "arguments": {"expressao": "1+1"}}})
    assert resposta["result"] == {"content": [{"type": "text", "text": 'calcular:{"expressao": "1+1"}'}], "isError": False}


def test_rota_de_ferramentas_exige_sessao_valida():
    cliente = TestClient(main.app, client=("127.0.0.1", 50000))
    corpo = {"nome": "calcular", "argumentos": {"expressao": "2*3"}}

    sem_sessao = cliente.post("/api/ia/ferramentas/executar", json=corpo)
    assert sem_sessao.status_code == 403

    token = ferramentas_ia.criar_sessao("Peca.com")
    try:
        ok = cliente.post("/api/ia/ferramentas/executar", json=corpo, headers={"X-Prisma-Sessao": token})
    finally:
        ferramentas_ia.encerrar_sessao(token)
    assert ok.status_code == 200
    assert ok.json() == {"texto": '{"resultado": 6.0}', "erro": False}


def test_rota_de_ferramentas_recusa_chamada_de_fora_da_maquina():
    cliente = TestClient(main.app, client=("192.168.0.20", 50000))
    token = ferramentas_ia.criar_sessao("Peca.com")
    try:
        resposta = cliente.post(
            "/api/ia/ferramentas/executar",
            json={"nome": "calcular", "argumentos": {"expressao": "1"}},
            headers={"X-Prisma-Sessao": token},
        )
    finally:
        ferramentas_ia.encerrar_sessao(token)
    assert resposta.status_code == 403
