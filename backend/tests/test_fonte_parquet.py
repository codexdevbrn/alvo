"""Fonte só em parquet, com o esquema tipado que chega das empresas.

O que trava aqui: CSV que sobre na pasta não é lido; identificador sai texto
mesmo que o arquivo o traga numérico (é por ele que movimento e produto se
juntam); data `date32` vira `datetime64`; e o catálogo é lido só nas colunas
que o join usa.
"""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

import main  # noqa: F401  (insere a raiz do projeto no sys.path)
import base_duckdb
from engine import analise_funil as af
from fonte_parquet_util import escrever_fonte
from normalizar_base import (
    ErroNormalizacao,
    resolver_arquivos_dados,
    resolver_caminho_controladoria,
)

MOVIMENTO = [
    {
        "ID_LOJA": "1", "TIPO_MOVIMENTO": "VENDA", "CODIGO_PRODUTO": "0100",
        "CODIGO_REFERENCIA_PRODUTO": "REF-100", "DESCRICAO_PRODUTO": "produto bruto 100",
        "NOME_FABRICANTE": "Fabricante X", "NOME_CLIENTE": "Cliente A", "NOME_VENDEDOR": "João",
        "DATA_MOVIMENTO": "2026-08-15", "DIA": "15", "MES": "8", "ANO": "2026",
        "TOTAL": "1.234,56", "QUANTIDADE": "3", "CMV": "800,00",
    },
    {
        "ID_LOJA": "2", "TIPO_MOVIMENTO": "VENDA", "CODIGO_PRODUTO": "200",
        "CODIGO_REFERENCIA_PRODUTO": "", "DESCRICAO_PRODUTO": "sem harmonizacao",
        "NOME_FABRICANTE": "Fabricante Y", "NOME_CLIENTE": "Cliente B", "NOME_VENDEDOR": "Ana",
        "DATA_MOVIMENTO": "2026-09-02", "DIA": "2", "MES": "9", "ANO": "2026",
        "TOTAL": "99,90", "QUANTIDADE": "1", "CMV": "50,00",
    },
]

PRODUTO = [
    {
        "ID_LOJA": "1", "CODIGO_INTERNO_PRODUTO": "0100", "CODIGO_REFERENCIA_PRODUTO": "REF-100",
        "DESCRICAO_PRODUTO": "PRODUTO 100", "DESCRICAO_HARMONIZADA": "Produto Harmonizado",
        "QUANTIDADE_ESTOQUE": "12",
    },
    {
        "ID_LOJA": "2", "CODIGO_INTERNO_PRODUTO": "200", "CODIGO_REFERENCIA_PRODUTO": "",
        "DESCRICAO_PRODUTO": "PRODUTO 200", "DESCRICAO_HARMONIZADA": "",
        "QUANTIDADE_ESTOQUE": "0",
    },
]

CONTROLADORIA = [
    {"ID_LOJA": "1", "DESCRICAO": "ALUGUEL", "DESCRICAO_HARMONIZADA": "Aluguel",
     "DATA_VENC": "2026-08-10", "DIA": "10", "MES": "8", "ANO": "2026",
     "VALOR": "3.500,00", "FORNECEDOR": "Imobiliária"},
    {"ID_LOJA": "2", "DESCRICAO": "LUZ", "DESCRICAO_HARMONIZADA": "",
     "DATA_VENC": "2026-09-05", "DIA": "5", "MES": "9", "ANO": "2026",
     "VALOR": "420,10", "FORNECEDOR": "Concessionária"},
]


def _empresa(tmp_path: Path, nome: str = "Empresa") -> Path:
    pasta = tmp_path / nome
    pasta.mkdir()
    escrever_fonte(pasta / f"{nome}_MOVIMENTO_ATUAL.parquet", MOVIMENTO)
    escrever_fonte(pasta / f"{nome}_PRODUTO.parquet", PRODUTO)
    return pasta


# --- Resolução de caminho ---------------------------------------------------


def test_resolve_os_dois_parquet(tmp_path):
    pasta = _empresa(tmp_path)
    movimento, produto, _estoque, _vendas = resolver_arquivos_dados(pasta)
    assert movimento.name == "Empresa_MOVIMENTO_ATUAL.parquet"
    assert produto.name == "Empresa_PRODUTO.parquet"


def test_csv_que_sobrou_na_pasta_nao_e_lido(tmp_path):
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    pd.DataFrame(MOVIMENTO).to_csv(pasta / "Empresa_MOVIMENTO_ATUAL.csv", sep=";", index=False)
    pd.DataFrame(PRODUTO).to_csv(pasta / "Empresa_PRODUTO.csv", sep=";", index=False)
    with pytest.raises(ErroNormalizacao, match=r"Empresa_MOVIMENTO_ATUAL\.parquet"):
        resolver_arquivos_dados(pasta)


def test_nome_e_extensao_sem_diferenciar_caixa(tmp_path):
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    escrever_fonte(pasta / "EMPRESA_movimento_atual.PARQUET", MOVIMENTO)
    escrever_fonte(pasta / "empresa_produto.Parquet", PRODUTO)
    movimento, produto, _estoque, _vendas = resolver_arquivos_dados(pasta)
    assert movimento.name == "EMPRESA_movimento_atual.PARQUET"
    assert produto.name == "empresa_produto.Parquet"


def test_controladoria_em_parquet(tmp_path):
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    assert resolver_caminho_controladoria(pasta) is None
    escrever_fonte(pasta / "Empresa_CONTROLADORIA.parquet", CONTROLADORIA)
    assert resolver_caminho_controladoria(pasta).name == "Empresa_CONTROLADORIA.parquet"


# --- Leitura -----------------------------------------------------------------


def test_carrega_base_tipada(tmp_path):
    movimento, produto, _e, _v = resolver_arquivos_dados(_empresa(tmp_path))
    df = af.carregar_csv_base_empresa(movimento, produto)

    assert df["Loja"].tolist() == ["1", "2"]
    assert df["Código Interno"].tolist() == ["0100", "200"]  # zero à esquerda preservado
    assert df["descricao"].tolist() == ["Produto Harmonizado", "sem harmonizacao"]
    assert pd.isna(df["Código de referêcia"].iloc[1])  # vazio vira ausente
    assert df["Receita Acumulada 11 Meses"].tolist() == pytest.approx([1234.56, 99.90])
    assert df["QTD"].tolist() == pytest.approx([3.0, 1.0])
    assert df["CMV"].tolist() == pytest.approx([800.0, 50.0])
    assert df["Ano"].tolist() == [2026, 2026]
    assert df["Mês"].tolist() == [8, 9]
    assert df["Vendedor"].tolist() == ["João", "Ana"]
    assert df["Data_Venda_Diaria"].dtype == "datetime64[ns]"
    assert df["Data_Venda_Diaria"].dt.strftime("%Y-%m-%d").tolist() == ["2026-08-15", "2026-09-02"]


def test_codigo_numerico_no_parquet_ainda_casa_no_join(tmp_path):
    """Código gravado como número (com nulo, vira float) não pode virar "100.0"
    e deixar de casar com o catálogo."""
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    movimento = pd.DataFrame(MOVIMENTO)
    movimento["CODIGO_PRODUTO"] = [100.0, None]
    movimento["TOTAL"] = [1234.56, 99.90]
    movimento["QUANTIDADE"] = [3.0, 1.0]
    movimento["CMV"] = [800.0, 50.0]
    movimento[["DIA", "MES", "ANO"]] = movimento[["DIA", "MES", "ANO"]].astype(int)
    movimento.to_parquet(pasta / "Empresa_MOVIMENTO_ATUAL.parquet", index=False)
    produto = pd.DataFrame(PRODUTO)
    produto["CODIGO_INTERNO_PRODUTO"] = [100, 200]
    produto.to_parquet(pasta / "Empresa_PRODUTO.parquet", index=False)

    m, p, _e, _v = resolver_arquivos_dados(pasta)
    df = af.carregar_csv_base_empresa(m, p)
    assert df["Código Interno"].iloc[0] == "100"
    assert df["descricao"].iloc[0] == "Produto Harmonizado"


def test_catalogo_e_lido_so_nas_colunas_do_join(tmp_path, monkeypatch):
    movimento, produto, _e, _v = resolver_arquivos_dados(_empresa(tmp_path))
    pedidas = {}
    original = pd.read_parquet

    def espiao(caminho, columns=None, **kwargs):
        pedidas[Path(caminho).name] = columns
        return original(caminho, columns=columns, **kwargs)

    monkeypatch.setattr(af.pd, "read_parquet", espiao)
    af.carregar_csv_base_empresa(movimento, produto)
    assert pedidas["Empresa_PRODUTO.parquet"] == ["CODIGO_INTERNO_PRODUTO", "DESCRICAO_HARMONIZADA"]
    assert pedidas["Empresa_MOVIMENTO_ATUAL.parquet"] is None  # movimento vem inteiro


def test_coluna_obrigatoria_ausente_falha_pelo_rodape(tmp_path):
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    escrever_fonte(pasta / "Empresa_MOVIMENTO_ATUAL.parquet", [
        {k: v for k, v in MOVIMENTO[0].items() if k != "CMV"}
    ])
    escrever_fonte(pasta / "Empresa_PRODUTO.parquet", PRODUTO)
    m, p, _e, _v = resolver_arquivos_dados(pasta)
    with pytest.raises(af.ErroCarregamentoCSV, match="sem colunas: CMV"):
        af.carregar_csv_base_empresa(m, p)


def test_arquivo_que_nao_e_parquet_da_erro_claro(tmp_path):
    pasta = _empresa(tmp_path)
    (pasta / "Empresa_MOVIMENTO_ATUAL.parquet").write_text("isto não é parquet", encoding="utf-8")
    m, p, _e, _v = resolver_arquivos_dados(pasta)
    with pytest.raises(af.ErroCarregamentoCSV, match="Empresa_MOVIMENTO_ATUAL.parquet"):
        af.carregar_csv_base_empresa(m, p)


def test_despesas_em_parquet(tmp_path):
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    df = af.carregar_csv_despesas(escrever_fonte(pasta / "Empresa_CONTROLADORIA.parquet", CONTROLADORIA))
    assert df["Loja"].tolist() == ["1", "2"]
    # Sem harmonização, a categoria cai para a descrição bruta.
    assert df["categoria"].tolist() == ["Aluguel", "LUZ"]
    assert df["Valor"].tolist() == pytest.approx([3500.0, 420.10])
    assert df["Ano"].tolist() == [2026, 2026]
    assert df["Mês"].tolist() == [8, 9]


def test_estoque_le_o_catalogo_inteiro(tmp_path):
    movimento, produto, _e, _v = resolver_arquivos_dados(_empresa(tmp_path))
    base = af.carregar_csv_base_empresa(movimento, produto)
    estoque, _vendas = af.montar_estoque_e_vendas(base, produto)
    por_codigo = estoque.set_index("CODIGO_INTERNO_PRODUTO")
    assert por_codigo.loc["0100", "Qtd_estoque"] == pytest.approx(12.0)
    assert por_codigo.loc["0100", "descricao"] == "Produto Harmonizado"


def test_base_pelo_duckdb_igual_ao_pandas_e_sem_escrita(tmp_path):
    pasta = _empresa(tmp_path, "fonte")
    movimento, produto, _e, _v = resolver_arquivos_dados(pasta)
    corte = pd.Timestamp("2100-01-01").date()

    novo, _ = base_duckdb.carregar_duckdb(movimento, produto, corte)
    velho, _ = base_duckdb.carregar_pandas(movimento, produto, corte)
    pd.testing.assert_frame_equal(novo, velho.reset_index(drop=True))
    # A fonte continua intocada: só os dois arquivos que já estavam lá.
    assert sorted(p.name for p in pasta.iterdir()) == [
        "fonte_MOVIMENTO_ATUAL.parquet", "fonte_PRODUTO.parquet",
    ]


def test_utilitario_grava_o_esquema_da_fonte_real(tmp_path):
    """Guarda do próprio teste: se o utilitário deixasse de gravar o esquema da
    fonte (date32/int32/double), os testes acima passariam lendo outra coisa."""
    esquema = pq.read_schema(escrever_fonte(tmp_path / "m.parquet", MOVIMENTO))
    assert esquema.field("DATA_MOVIMENTO").type == pa.date32()
    assert esquema.field("ANO").type == pa.int32()
    assert esquema.field("TOTAL").type == pa.float64()
    assert esquema.field("CODIGO_PRODUTO").type == pa.string()


def test_harmonizada_da_outra_loja_vale_quando_a_primeira_vem_vazia(tmp_path):
    """Mesmo código em duas lojas, a primeira sem harmonização: a descrição do
    catálogo é uma só, então a da segunda loja vale para as duas."""
    pasta = tmp_path / "Empresa"
    pasta.mkdir()
    escrever_fonte(pasta / "Empresa_MOVIMENTO_ATUAL.parquet", [MOVIMENTO[0]])
    escrever_fonte(pasta / "Empresa_PRODUTO.parquet", [
        {**PRODUTO[0], "ID_LOJA": "1", "DESCRICAO_HARMONIZADA": ""},
        {**PRODUTO[0], "ID_LOJA": "2"},
    ])
    m, p, _e, _v = resolver_arquivos_dados(pasta)
    df = af.carregar_csv_base_empresa(m, p)
    assert df["descricao"].tolist() == ["Produto Harmonizado"]
