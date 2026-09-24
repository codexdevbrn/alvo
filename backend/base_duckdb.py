"""Base da empresa montada por uma consulta DuckDB direto nos parquet da fonte.

Por que existe: o caminho em pandas lia os dois parquet em ~1 s, mas a limpeza
depois (`af.validar_e_limpar`: strip de texto, nulos, datas e os campos de
período montados por concatenação de string) levava 5 s na IBAD (1,46 milhão de
linhas) e 2,5 s na Altese. Aqui leitura, join com o catálogo, corte D-1 e
limpeza viram uma consulta só, e o DataFrame que sai é **o mesmo** do caminho
antigo — colunas, ordem, tipos e valores —, conferido nas empresas reais e
travado em `tests/test_base_duckdb.py`.

Com isso o `_cache_atacado.parquet` deixou de existir: ele guardava o join na
pasta de trabalho porque o CSV custava ~19 s de parse, e com parquet + DuckDB
a base inteira sai em menos tempo do que ele levava para ser relido.

O que não é reproduzido aqui cai no caminho antigo (`carregar_pandas`), que dá
a mensagem de erro de sempre: esquema fora do padrão (coluna faltando, código
que não é texto), mês fora de 1–12. Harmonização de cliente, normalização de
loja e vendedores de demonstração continuam em `main.py`, depois desta função.

Somente leitura, como `consulta_parquet`: conexão em memória por chamada,
caminho como parâmetro.
"""

from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from engine import analise_funil as af

logger = logging.getLogger(__name__)

NAO_INFORMADO = "Não informado"

#: Tudo que o `str.strip()` do Python remove. O `trim()` do DuckDB tira só o
#: espaço, e a IBAD tem cliente gravado com tabulação no fim ("RODRIGO DOS
#: SANTOS	") — sem isto ele virava um cliente a mais.
ESPACOS_PYTHON = "".join(chr(i) for i in range(0x110000) if chr(i).isspace())
# Atalho: primeiro e último caractere ASCII visíveis (quase todo valor) passam
# direto; o trim com a lista inteira custava 3 s a mais na IBAD.
_MACRO_STRIP = (
    "CREATE MACRO py_strip(x) AS CASE "
    "WHEN x IS NULL OR x = '' THEN x "
    "WHEN unicode(x) BETWEEN 33 AND 126 AND unicode(right(x, 1)) BETWEEN 33 AND 126 THEN x "
    "ELSE trim(x, ?) END"
)

#: Colunas de período, na ordem em que `validar_e_limpar` as acrescenta.
_DERIVADAS = [
    "descricao", "Data_Venda_Diaria", "Receita", "Data_Venda",
    "Periodo_Mensal", "Periodo_Trimestral", "Periodo_Semestral", "Periodo_Anual",
]


class ForaDoPadrao(RuntimeError):
    """Esquema que a consulta não reproduz com segurança — usar o caminho pandas."""


def _q(nome: str) -> str:
    return '"' + nome.replace('"', '""') + '"'


def _texto_ou_nulo(coluna: str) -> str:
    """`""` vira ausente, como `af._vazio_como_ausente`."""
    return f"NULLIF({_q(coluna)}, '')"


def _conferir_esquema(movimento: pa.Schema, produto: pa.Schema) -> str | None:
    """Confere o que a consulta assume. Devolve a coluna de vendedor, se houver."""
    faltando = [c for c in af.COLUNAS_MOVIMENTO_EMPRESA if c not in movimento.names]
    faltando += [c for c in ("CODIGO_INTERNO_PRODUTO", "DESCRICAO_HARMONIZADA") if c not in produto.names]
    if faltando:
        raise ForaDoPadrao("faltam colunas: " + ", ".join(faltando))
    for esquema, colunas in ((movimento, af.COLUNAS_TEXTO_MOVIMENTO),
                             (produto, ("CODIGO_INTERNO_PRODUTO", "DESCRICAO_HARMONIZADA"))):
        for nome in colunas:
            if nome in esquema.names and not pa.types.is_string(esquema.field(nome).type) \
                    and not pa.types.is_large_string(esquema.field(nome).type):
                # Código numérico precisa da conversão cuidadosa de
                # `af._serie_como_texto` (100.0 → "100"); fica com o pandas.
                raise ForaDoPadrao(f"{nome} não é texto ({esquema.field(nome).type})")
    for nome in ("ANO", "MES"):
        if not pa.types.is_integer(movimento.field(nome).type):
            raise ForaDoPadrao(f"{nome} não é inteiro")
    if not pa.types.is_date(movimento.field("DATA_MOVIMENTO").type):
        raise ForaDoPadrao("DATA_MOVIMENTO não é data")
    if "Vendedor" in movimento.names:
        return None
    return next((c for c in af.COLUNAS_VENDEDOR_FONTE if c in movimento.names), None)


def _select(movimento: pa.Schema, coluna_vendedor: str | None) -> str:
    """Colunas na ordem do movimento (renomeadas), depois as derivadas."""
    renomear = dict(af.MAPA_COLUNAS_MOVIMENTO_EMPRESA)
    if coluna_vendedor:
        renomear[coluna_vendedor] = "Vendedor"
    partes = []
    for nome in movimento.names:
        if nome == "DESCRICAO_PRODUTO":
            continue
        destino = renomear.get(nome, nome)
        if destino == "NOME_FABRICANTE":
            expr = f"py_strip(coalesce({_texto_ou_nulo(nome)}, '{NAO_INFORMADO}'))"
        elif destino == "Cliente":
            expr = (f"CASE WHEN py_strip(coalesce({_texto_ou_nulo(nome)}, '')) = '' "
                    f"THEN '{NAO_INFORMADO}' ELSE py_strip({_q(nome)}) END")
        elif destino == "Código de referêcia":
            expr = f"py_strip(coalesce({_q(nome)}, ''))"
        elif destino == "Vendedor":
            expr = (f"CASE WHEN lower(py_strip(coalesce({_q(nome)}, ''))) IN ('', 'nan', 'none', '<na>') "
                    f"THEN '' ELSE py_strip({_q(nome)}) END")
        elif destino == "QTD":
            # to_numeric → fillna(0) → astype(int): trunca em direção a zero.
            expr = f"CAST(trunc(coalesce({_q(nome)}, 0)) AS BIGINT)"
        elif nome in af.COLUNAS_TEXTO_MOVIMENTO:
            expr = _texto_ou_nulo(nome)
        elif pa.types.is_date(movimento.field(nome).type):
            expr = f"CAST({_q(nome)} AS TIMESTAMP)"
        else:
            expr = _q(nome)
        partes.append(f"{expr} AS {_q(destino)}")

    # descricao: harmonizada do catálogo; sem ela, a bruta do movimento.
    partes.append(
        "CASE WHEN py_strip(coalesce(h.harm, NULLIF(m.DESCRICAO_PRODUTO, ''), '')) = '' "
        f"THEN '{af.DESCRICAO_NAO_HARMONIZADA}' "
        "ELSE py_strip(coalesce(h.harm, NULLIF(m.DESCRICAO_PRODUTO, ''))) END AS descricao"
    )
    partes.append("CAST(m.DATA_MOVIMENTO AS TIMESTAMP) AS Data_Venda_Diaria")
    partes.append('coalesce(m.TOTAL, 0.0) AS "Receita"')
    partes.append('CAST(make_date(m.ANO, m.MES, 1) AS TIMESTAMP) AS "Data_Venda"')
    partes.append("strftime(make_date(m.ANO, m.MES, 1), '%Y-%m') AS \"Periodo_Mensal\"")
    partes.append("CAST(m.ANO AS VARCHAR) || '-T' || CAST(quarter(make_date(m.ANO, m.MES, 1)) AS VARCHAR) "
                  "AS \"Periodo_Trimestral\"")
    partes.append("CAST(m.ANO AS VARCHAR) || '-S' || CASE WHEN m.MES <= 6 THEN '1' ELSE '2' END "
                  "AS \"Periodo_Semestral\"")
    partes.append("CAST(m.ANO AS VARCHAR) AS \"Periodo_Anual\"")
    return ",\n  ".join(partes)


def _consulta(movimento: pa.Schema, coluna_vendedor: str | None) -> str:
    colunas = _select(movimento, coluna_vendedor)
    # Coluna do movimento sem prefixo resolve em `m`: o catálogo só expõe
    # `codigo` e `harm`, que a fonte não usa.
    return f"""
WITH catalogo AS (
  SELECT py_strip(CODIGO_INTERNO_PRODUTO) AS codigo,
         py_strip(DESCRICAO_HARMONIZADA) AS harm,
         file_row_number AS n
  FROM read_parquet(?, file_row_number = true)
  WHERE NULLIF(py_strip(CODIGO_INTERNO_PRODUTO), '') IS NOT NULL
    AND DESCRICAO_HARMONIZADA IS NOT NULL
    AND lower(py_strip(DESCRICAO_HARMONIZADA)) NOT IN ('', 'nan', 'none', '<na>')
),
mapa AS (
  -- Primeira harmonizada válida do código no arquivo, como `_mapa_descricao_harmonizada`.
  SELECT codigo, arg_min(harm, n) AS harm FROM catalogo GROUP BY codigo
)
SELECT
  {colunas}
FROM read_parquet(?, file_row_number = true) AS m
-- Código vazio não casa: venda sem código fica com a descrição do movimento.
LEFT JOIN mapa AS h ON h.codigo = NULLIF(py_strip(m.CODIGO_PRODUTO), '')
WHERE m.ANO IS NOT NULL AND m.MES IS NOT NULL
  AND (m.DATA_MOVIMENTO IS NULL OR m.DATA_MOVIMENTO <= ?)
ORDER BY m.file_row_number
"""


def _ajustar_tipos(df: pd.DataFrame) -> pd.DataFrame:
    """Datas como no caminho pandas: diárias em `ns`, `Data_Venda` em `us`.

    Texto já chega `str` pelo Arrow. Sair por `.df()` custava 4,3 s na IBAD só
    convertendo string para objeto Python; por Arrow a consulta inteira leva ~1 s.
    """
    for coluna in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[coluna]) and coluna != "Data_Venda":
            df[coluna] = df[coluna].astype("datetime64[ns]")
    df["Data_Venda"] = df["Data_Venda"].astype("datetime64[us]")
    return df


def carregar_duckdb(caminho_movimento: Path, caminho_produto: Path, data_corte) -> tuple[pd.DataFrame, int]:
    """Base limpa e cortada em D-1, com a contagem de linhas sem ano/mês."""
    movimento = pq.read_schema(caminho_movimento)
    produto = pq.read_schema(caminho_produto)
    coluna_vendedor = _conferir_esquema(movimento, produto)

    with duckdb.connect(":memory:") as conexao:
        # Macro não aceita parâmetro preparado: a lista entra como literal, com
        # aspas escapadas (não há aspas nela, mas o escape custa nada).
        conexao.execute(_MACRO_STRIP.replace("?", "'" + ESPACOS_PYTHON.replace("'", "''") + "'"))
        invalidos, sem_ano_mes = conexao.execute(
            "SELECT count(*) FILTER (WHERE MES NOT BETWEEN 1 AND 12), "
            "count(*) FILTER (WHERE ANO IS NULL OR MES IS NULL) "
            "FROM read_parquet(?) WHERE DATA_MOVIMENTO IS NULL OR DATA_MOVIMENTO <= ?",
            [str(caminho_movimento), data_corte],
        ).fetchone()
        if invalidos:
            raise ForaDoPadrao(f"{invalidos} linhas com mês fora de 1–12")
        tabela = conexao.execute(
            _consulta(movimento, coluna_vendedor),
            [str(caminho_produto), str(caminho_movimento), data_corte],
        ).to_arrow_table()
    return _ajustar_tipos(tabela.to_pandas()), int(sem_ano_mes)


def carregar_pandas(caminho_movimento: Path, caminho_produto: Path, data_corte) -> tuple[pd.DataFrame, int]:
    """Caminho antigo, para o que a consulta não cobre (e para conferir a nova)."""
    bruto = af.carregar_csv_base_empresa(caminho_movimento, caminho_produto)
    return af.validar_e_limpar(af.cortar_ate(bruto, data_corte), receita_em_texto_br=False)


def carregar_base_empresa(caminho_movimento: Path, caminho_produto: Path, data_corte) -> tuple[pd.DataFrame, int]:
    """DuckDB quando o esquema é o padrão da fonte; pandas quando não é."""
    try:
        return carregar_duckdb(Path(caminho_movimento), Path(caminho_produto), data_corte)
    except ForaDoPadrao as exc:
        logger.info("Base de %s pelo caminho pandas: %s", Path(caminho_movimento).name, exc)
    except (duckdb.Error, OSError) as exc:
        # Arquivo travado pelo OneDrive, placeholder não baixado: o caminho pandas
        # tem as mensagens que dizem ao usuário o que fazer.
        logger.warning("DuckDB não leu %s (%s); tentando pelo pandas", Path(caminho_movimento).name, exc)
    return carregar_pandas(Path(caminho_movimento), Path(caminho_produto), data_corte)
