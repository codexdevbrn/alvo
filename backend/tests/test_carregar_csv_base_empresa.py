"""Leitura de MOVIMENTO_ATUAL + PRODUTO (parquet) da fonte por empresa."""

from pathlib import Path

import pandas as pd
import pytest

# Importar main inclui a raiz do projeto no sys.path, como acontece no servidor.
import main  # noqa: F401
from engine import analise_funil as af
from fonte_parquet_util import escrever_fonte
from normalizar_base import ErroNormalizacao, resolver_arquivos_dados


def _empresa(tmp_path: Path, nome: str = "Empresa") -> Path:
    pasta = tmp_path / nome
    pasta.mkdir()
    return pasta


def test_resolver_arquivos_dados_exige_movimento_e_produto(tmp_path):
    pasta = _empresa(tmp_path)
    with pytest.raises(ErroNormalizacao):
        resolver_arquivos_dados(pasta)

    escrever_fonte(pasta / "Empresa_MOVIMENTO_ATUAL.parquet", [{"ID_LOJA": "1"}])
    with pytest.raises(ErroNormalizacao):
        resolver_arquivos_dados(pasta)

    escrever_fonte(pasta / "Empresa_PRODUTO.parquet", [{"ID_LOJA": "1"}])
    movimento, produto, estoque, vendas = resolver_arquivos_dados(pasta)
    assert movimento.name == "Empresa_MOVIMENTO_ATUAL.parquet"
    assert produto.name == "Empresa_PRODUTO.parquet"
    assert estoque is None
    assert vendas is None


def test_resolver_arquivos_dados_acha_estoque_e_vendas_opcionais(tmp_path):
    pasta = _empresa(tmp_path)
    escrever_fonte(pasta / "Empresa_MOVIMENTO_ATUAL.parquet", [{"ID_LOJA": "1"}])
    escrever_fonte(pasta / "Empresa_PRODUTO.parquet", [{"ID_LOJA": "1"}])
    (pasta / "Dados_Estoque_Empresa.csv").write_text("x", encoding="utf-8")
    (pasta / "Dados_Vendas_Empresa.csv").write_text("x", encoding="utf-8")

    _movimento, _produto, estoque, vendas = resolver_arquivos_dados(pasta)
    assert estoque.name == "Dados_Estoque_Empresa.csv"
    assert vendas.name == "Dados_Vendas_Empresa.csv"


def _linha_movimento(**overrides) -> dict:
    base = {
        "ID_LOJA": "1",
        "CODIGO_PRODUTO": "100",
        "CODIGO_REFERENCIA_PRODUTO": "REF-100",
        "DESCRICAO_PRODUTO": "produto bruto 100",
        "NOME_FABRICANTE": "Fabricante X",
        "NOME_CLIENTE": "Cliente A",
        "NOME_VENDEDOR": "João",
        "DATA_MOVIMENTO": "2026-08-15",
        "DIA": "15",
        "MES": "8",
        "ANO": "2026",
        "TOTAL": "1.234,56",
        "QUANTIDADE": "3",
        "CMV": "800,00",
    }
    base.update(overrides)
    return base


def _linha_produto(**overrides) -> dict:
    base = {
        "ID_LOJA": "1",
        "CODIGO_INTERNO_PRODUTO": "100",
        "CODIGO_REFERENCIA_PRODUTO": "REF-100",
        "DESCRICAO_PRODUTO": "produto bruto 100",
        "DESCRICAO_HARMONIZADA": "Produto Harmonizado 100",
        "QUANTIDADE_ESTOQUE": "12",
    }
    base.update(overrides)
    return base


def test_carrega_e_junta_descricao_harmonizada(tmp_path):
    pasta = _empresa(tmp_path)
    caminho_movimento = pasta / "Empresa_MOVIMENTO_ATUAL.parquet"
    caminho_produto = pasta / "Empresa_PRODUTO.parquet"
    escrever_fonte(caminho_movimento, [
        _linha_movimento(),
        _linha_movimento(CODIGO_PRODUTO="200", DESCRICAO_PRODUTO="sem harmonizacao"),
    ])
    escrever_fonte(caminho_produto, [
        _linha_produto(),
        _linha_produto(CODIGO_INTERNO_PRODUTO="200", DESCRICAO_HARMONIZADA=""),
    ])

    df = af.carregar_csv_base_empresa(caminho_movimento, caminho_produto)

    por_codigo = df.set_index("Código Interno")["descricao"]
    assert por_codigo["100"] == "Produto Harmonizado 100"
    # Sem DESCRICAO_HARMONIZADA no catálogo: cai para a descrição bruta do movimento.
    assert por_codigo["200"] == "sem harmonizacao"

    assert df["CMV"].tolist() == [800.0, 800.0]
    assert df["QTD"].tolist() == [3.0, 3.0]
    assert df["Receita Acumulada 11 Meses"].tolist() == [1234.56, 1234.56]
    assert df["Vendedor"].tolist() == ["João", "João"]
    assert df["Ano"].tolist() == [2026, 2026]
    assert df["Mês"].tolist() == [8, 8]


def test_montar_estoque_e_vendas_usa_produto_e_cmv_medio(tmp_path):
    pasta = _empresa(tmp_path)
    caminho_movimento = pasta / "Empresa_MOVIMENTO_ATUAL.parquet"
    caminho_produto = pasta / "Empresa_PRODUTO.parquet"
    escrever_fonte(caminho_movimento, [
        # Produto 100: duas vendas, CMV total 1600 / QTD total 6 = custo unitário 266,67ish
        _linha_movimento(CMV="800,00", QUANTIDADE="3"),
        _linha_movimento(CMV="800,00", QUANTIDADE="3"),
    ])
    escrever_fonte(caminho_produto, [_linha_produto(QUANTIDADE_ESTOQUE="12")])

    df_base = af.carregar_csv_base_empresa(caminho_movimento, caminho_produto)
    estoque, vendas = af.montar_estoque_e_vendas(df_base, caminho_produto)

    linha = estoque.set_index("CODIGO_INTERNO_PRODUTO").loc["100"]
    assert linha["Qtd_estoque"] == 12.0
    assert linha["NOME_FABRICANTE"] == "Fabricante X"
    assert linha["descricao"] == "Produto Harmonizado 100"
    assert linha["Preço_médio_cmv"] == pytest.approx(1600.0 / 6.0)
    assert linha["Último_custo"] == 0.0

    assert vendas["QTD"].sum() == 6.0
    assert vendas["CODIGO_INTERNO_PRODUTO"].unique().tolist() == ["100"]


def test_validar_e_limpar_aceita_mes_numerico(tmp_path):
    pasta = _empresa(tmp_path)
    caminho_movimento = pasta / "Empresa_MOVIMENTO_ATUAL.parquet"
    caminho_produto = pasta / "Empresa_PRODUTO.parquet"
    escrever_fonte(caminho_movimento, [_linha_movimento()])
    escrever_fonte(caminho_produto, [_linha_produto()])

    df_bruto = af.carregar_csv_base_empresa(caminho_movimento, caminho_produto)
    df, linhas_vazias = af.validar_e_limpar(df_bruto, receita_em_texto_br=False)

    assert linhas_vazias == 0
    assert df["Data_Venda"].iloc[0] == pd.Timestamp("2026-08-01")
    assert df["Periodo_Mensal"].iloc[0] == "2026-08"
    assert df["Data_Venda_Diaria"].iloc[0] == pd.Timestamp("2026-08-15")
