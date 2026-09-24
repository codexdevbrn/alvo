"""Base da empresa pelo DuckDB (`base_duckdb`) sai igual ao caminho pandas.

A garantia vale nas 41 empresas reais (conferido na troca, set/2026); aqui ela
fica travada com as linhas que mais custaram: espaço que não é espaço, texto
vazio, código vazio dos dois lados, harmonização repetida no catálogo, venda
depois do corte D-1.
"""

from __future__ import annotations

import datetime as dt

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import base_duckdb
from engine import analise_funil as af
from tests.fonte_parquet_util import escrever_fonte

CORTE = dt.date(2026, 9, 23)


def _mov(**extra):
    linha = {
        "ID_LOJA": "1", "TIPO_MOVIMENTO": "V", "CODIGO_PRODUTO": "100",
        "CODIGO_REFERENCIA_PRODUTO": "R1", "DESCRICAO_PRODUTO": "Filtro bruto",
        "NOME_FABRICANTE": "BOSCH", "NOME_CLIENTE": "JOAO", "NOME_VENDEDOR": "ANA",
        "DATA_MOVIMENTO": "2026-09-10", "DIA": "10", "MES": "9", "ANO": "2026",
        "TOTAL": "100,50", "QUANTIDADE": "2", "CMV": "60",
    }
    linha.update(extra)
    return linha


def _prod(codigo, harmonizada, descricao="x"):
    return {
        "ID_LOJA": "1", "CODIGO_INTERNO_PRODUTO": codigo, "CODIGO_REFERENCIA_PRODUTO": "R",
        "DESCRICAO_PRODUTO": descricao, "DESCRICAO_HARMONIZADA": harmonizada, "QUANTIDADE_ESTOQUE": "1",
    }


@pytest.fixture
def fonte(tmp_path):
    movimento = escrever_fonte(tmp_path / "E_MOVIMENTO_ATUAL.parquet", [
        _mov(),
        _mov(NOME_CLIENTE="RODRIGO DOS SANTOS\t", NOME_FABRICANTE=" MAHLE "),
        _mov(NOME_CLIENTE="", NOME_FABRICANTE="", NOME_VENDEDOR="nan", CODIGO_REFERENCIA_PRODUTO=""),
        _mov(NOME_CLIENTE="   ", NOME_VENDEDOR="  Beto  "),
        _mov(CODIGO_PRODUTO="200", DESCRICAO_PRODUTO=""),
        _mov(CODIGO_PRODUTO="", DESCRICAO_PRODUTO="Interruptor"),
        _mov(CODIGO_PRODUTO=" 300 ", QUANTIDADE="2,9", TOTAL=""),
        _mov(DATA_MOVIMENTO="2026-09-24"),                      # depois do corte: sai
        _mov(MES="3", DIA="5", DATA_MOVIMENTO="2026-03-05"),
    ])
    produto = escrever_fonte(tmp_path / "E_PRODUTO.parquet", [
        _prod("100", "Filtro de Óleo"),
        _prod("100", "Filtro Outro"),                           # repetido: vale o primeiro
        _prod("300", "NaN"),                                    # não é harmonização
        _prod("300", "Pastilha"),
        _prod("   ", "Coxim Motor"),                            # código vazio não casa
    ])
    return movimento, produto


def test_duckdb_igual_ao_pandas(fonte):
    movimento, produto = fonte
    novo, vazias_novo = base_duckdb.carregar_duckdb(movimento, produto, CORTE)
    velho, vazias_velho = base_duckdb.carregar_pandas(movimento, produto, CORTE)
    pd.testing.assert_frame_equal(novo, velho.reset_index(drop=True))
    assert vazias_novo == vazias_velho == 0


def test_valores_das_linhas_dificeis(fonte):
    df, _ = base_duckdb.carregar_duckdb(*fonte, CORTE)
    assert len(df) == 8                                           # a de 24/09 saiu
    assert df.loc[1, "Cliente"] == "RODRIGO DOS SANTOS"           # tab some
    assert df.loc[1, "NOME_FABRICANTE"] == "MAHLE"                # nbsp some
    assert (df.loc[2, "Cliente"], df.loc[2, "NOME_FABRICANTE"]) == ("Não informado", "Não informado")
    assert (df.loc[2, "Vendedor"], df.loc[2, "Código de referêcia"]) == ("", "")
    assert (df.loc[3, "Cliente"], df.loc[3, "Vendedor"]) == ("Não informado", "Beto")
    assert df.loc[0, "descricao"] == "Filtro de Óleo"
    assert df.loc[4, "descricao"] == af.DESCRICAO_NAO_HARMONIZADA
    assert df.loc[5, "descricao"] == "Interruptor"
    assert df.loc[6, "descricao"] == "Pastilha"
    assert (df.loc[6, "QTD"], df.loc[6, "Receita"]) == (2, 0.0)
    assert df.loc[7, ["Periodo_Mensal", "Periodo_Trimestral", "Periodo_Semestral", "Periodo_Anual"]].tolist() == [
        "2026-03", "2026-T1", "2026-S1", "2026",
    ]


def test_codigo_numerico_cai_no_pandas(tmp_path, fonte):
    """Código gravado como número precisa da conversão cuidadosa do pandas."""
    _movimento, produto = fonte
    tabela = pq.read_table(_movimento)
    i = tabela.schema.get_field_index("CODIGO_PRODUTO")
    tabela = tabela.set_column(i, "CODIGO_PRODUTO", pa.array([100.0] * tabela.num_rows))
    movimento = tmp_path / "N_MOVIMENTO_ATUAL.parquet"
    pq.write_table(tabela, movimento)

    with pytest.raises(base_duckdb.ForaDoPadrao):
        base_duckdb.carregar_duckdb(movimento, produto, CORTE)
    df, _ = base_duckdb.carregar_base_empresa(movimento, produto, CORTE)
    assert (df["descricao"] == "Filtro de Óleo").all()


def test_mes_invalido_da_o_erro_de_sempre(tmp_path):
    movimento = escrever_fonte(tmp_path / "E_MOVIMENTO_ATUAL.parquet", [_mov(MES="13")])
    produto = escrever_fonte(tmp_path / "E_PRODUTO.parquet", [_prod("100", "Filtro")])
    with pytest.raises(af.ErroCarregamentoCSV, match="mês"):
        base_duckdb.carregar_base_empresa(movimento, produto, CORTE)
