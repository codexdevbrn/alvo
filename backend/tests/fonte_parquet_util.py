"""Grava arquivo da fonte em parquet com o esquema que a fonte real manda.

Os testes descrevem as linhas como texto — "1.234,56", "2026-08-15" —, que é
como se lê uma planilha. Aqui elas viram o parquet tipado que chega de verdade:
identificador string, `DATA_MOVIMENTO`/`DATA_VENC` date32, `DIA`/`MES`/`ANO`
int32, valores double. Coluna fora dessa lista fica string.
"""

from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from engine import analise_funil as af

COLUNAS_DATA = {"DATA_MOVIMENTO", "DATA_VENC"}
COLUNAS_INTEIRO = {"DIA", "MES", "ANO"}
COLUNAS_VALOR = {"TOTAL", "QUANTIDADE", "CMV", "QUANTIDADE_ESTOQUE", "VALOR"}


def escrever_fonte(caminho: Path, linhas: list[dict]) -> Path:
    df = pd.DataFrame(linhas)
    campos, colunas = [], []
    for nome in df.columns:
        serie = df[nome]
        if nome in COLUNAS_DATA:
            valores = pd.to_datetime(serie, errors="coerce", dayfirst="/" in str(serie.iloc[0]))
            array = pa.array([v.date() if pd.notna(v) else None for v in valores], pa.date32())
        elif nome in COLUNAS_INTEIRO:
            array = pa.array(pd.to_numeric(serie).astype("int32").tolist(), pa.int32())
        elif nome in COLUNAS_VALOR:
            valores = af._normalizar_numero_excel(serie.astype(str))
            array = pa.array([None if pd.isna(v) else float(v) for v in valores], pa.float64())
        else:
            array = pa.array([None if pd.isna(v) else str(v) for v in serie], pa.string())
        campos.append(pa.field(nome, array.type))
        colunas.append(array)
    pq.write_table(pa.Table.from_arrays(colunas, schema=pa.schema(campos)), caminho)
    return caminho
