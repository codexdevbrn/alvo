"""
normalizar_liquidez.py
======================

Gera as duas bases do relatório Liquidez a partir do BI (somente leitura)
na pasta de trabalho da empresa:

    Liquidez_Estoque.csv  ← *_PRODUTO.*
    Liquidez_Vendas.csv   ← *_MOVIMENTO_* (agregado sem cliente)

Layout de saída (estoque):
    Loja;NOME_FABRICANTE;descricao;CODIGO_INTERNO_PRODUTO;CODIGO_REFERENCIA_PRODUTO;
    Qtd_estoque;Preço_médio_de_venda;Preço_médio_cmv;Último_custo

Layout de saída (vendas):
    Nome_Loja;NOME_FABRICANTE;descricao;CODIGO_INTERNO_PRODUTO;CODIGO_REFERENCIA_PRODUTO;
    Ano;Mês;QTD

Uso:
    python normalizar_liquidez.py "<pasta_fonte>/<empresa>" --trabalho "<pasta_trabalho>/<empresa>"
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import warnings
from pathlib import Path

import pandas as pd

from normalizar_base import (
    CHUNKSIZE,
    COLS_MOVIMENTO,
    MESES_PT,
    MOVIMENTOS_VALIDOS,
    ErroNormalizacao,
    _parse_numero_br,
    formatar_loja,
    formatar_qtd,
    resolver_arquivos_bi,
)

NOME_ESTOQUE = "Liquidez_Estoque.csv"
NOME_VENDAS = "Liquidez_Vendas.csv"

COLUNAS_ESTOQUE = [
    "Loja",
    "NOME_FABRICANTE",
    "descricao",
    "CODIGO_INTERNO_PRODUTO",
    "CODIGO_REFERENCIA_PRODUTO",
    "Qtd_estoque",
    "Preço_médio_de_venda",
    "Preço_médio_cmv",
    "Último_custo",
]

COLUNAS_VENDAS = [
    "Nome_Loja",
    "NOME_FABRICANTE",
    "descricao",
    "CODIGO_INTERNO_PRODUTO",
    "CODIGO_REFERENCIA_PRODUTO",
    "Ano",
    "Mês",
    "QTD",
]

COLUNAS_GRUPO_VENDAS = [
    "Nome_Loja",
    "NOME_FABRICANTE",
    "descricao",
    "CODIGO_INTERNO_PRODUTO",
    "CODIGO_REFERENCIA_PRODUTO",
    "Ano",
    "Mês",
]

COLS_PRODUTO_LIQUIDEZ = [
    "ID_LOJA",
    "CODIGO_INTERNO_PRODUTO",
    "CODIGO_REFERENCIA_PRODUTO",
    "DESCRICAO_PRODUTO",
    "NOME_FABRICANTE",
    "QUANTIDADE_ESTOQUE",
    "PRECO_UNITARIO_PRODUTO",
    "CUSTO_MEDIO_UNITARIO",
    "ULTIMO_CUSTO",
]


def formatar_numero_br(valor: float, casas: int = 4) -> str:
    """Número em formato BR (vírgula decimal), sem separador de milhar."""
    if pd.isna(valor):
        return ""
    texto = f"{float(valor):.{casas}f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def normalizar_estoque(caminho_produto: Path) -> pd.DataFrame:
    """Lê o catálogo de produtos e monta a base de estoque da Liquidez."""
    produtos = pd.read_csv(
        caminho_produto,
        sep=";",
        quotechar='"',
        encoding="utf-8-sig",
        dtype=str,
        usecols=lambda c: c in COLS_PRODUTO_LIQUIDEZ,
    )
    faltando = [c for c in COLS_PRODUTO_LIQUIDEZ if c not in produtos.columns]
    if faltando:
        raise ErroNormalizacao(
            f"Arquivo de produtos sem colunas necessárias para Liquidez: {', '.join(faltando)}."
        )

    produtos = produtos.drop_duplicates(
        subset=["ID_LOJA", "CODIGO_INTERNO_PRODUTO"], keep="last",
    )

    out = pd.DataFrame({
        "Loja": formatar_loja(produtos["ID_LOJA"].astype(str)),
        "NOME_FABRICANTE": produtos["NOME_FABRICANTE"],
        "descricao": produtos["DESCRICAO_PRODUTO"],
        "CODIGO_INTERNO_PRODUTO": produtos["CODIGO_INTERNO_PRODUTO"],
        "CODIGO_REFERENCIA_PRODUTO": produtos["CODIGO_REFERENCIA_PRODUTO"].fillna(""),
        "Qtd_estoque": _parse_numero_br(produtos["QUANTIDADE_ESTOQUE"]).fillna(0.0),
        "Preço_médio_de_venda": _parse_numero_br(produtos["PRECO_UNITARIO_PRODUTO"]).fillna(0.0),
        "Preço_médio_cmv": _parse_numero_br(produtos["CUSTO_MEDIO_UNITARIO"]).fillna(0.0),
        "Último_custo": _parse_numero_br(produtos["ULTIMO_CUSTO"]).fillna(0.0),
    })

    for col in ("Qtd_estoque", "Preço_médio_de_venda", "Preço_médio_cmv", "Último_custo"):
        out[col] = out[col].map(lambda v: formatar_numero_br(v, 4))

    return out[COLUNAS_ESTOQUE]


def _processar_chunk_vendas(
    chunk: pd.DataFrame,
    produtos: pd.DataFrame,
    anos_permitidos: tuple[int, int],
) -> pd.DataFrame | None:
    chunk = chunk[chunk["TIPO_MOVIMENTO"].isin(MOVIMENTOS_VALIDOS)].copy()
    if chunk.empty:
        return None

    if "MOV" in chunk.columns:
        mov = chunk["MOV"].fillna("").astype(str).str.strip().str.upper()
        espelho = (chunk["TIPO_MOVIMENTO"] == "DEVOLUCAO") & mov.eq("S")
        chunk = chunk.loc[~espelho].copy()
        if chunk.empty:
            return None

    chunk["QUANTIDADE"] = _parse_numero_br(chunk["QUANTIDADE"]).fillna(0.0)
    eh_devolucao = chunk["TIPO_MOVIMENTO"] == "DEVOLUCAO"
    chunk.loc[eh_devolucao, "QUANTIDADE"] *= -1

    mes_num = chunk["DATA_MOVIMENTO"].str.slice(3, 5).astype(int)
    ano_num = chunk["DATA_MOVIMENTO"].str.slice(6, 10).astype(int)
    chunk["Ano"] = ano_num
    chunk["Mês"] = mes_num.map(MESES_PT)
    chunk = chunk[chunk["Ano"].isin(anos_permitidos)]
    if chunk.empty:
        return None

    chunk["Nome_Loja"] = formatar_loja(chunk["ID_LOJA"])
    chunk = chunk.merge(produtos, how="left", on=["ID_LOJA", "CODIGO_PRODUTO"])
    chunk["CODIGO_INTERNO_PRODUTO"] = chunk["CODIGO_PRODUTO"]
    chunk["descricao"] = chunk["DESCRICAO_PRODUTO"]
    chunk["CODIGO_REFERENCIA_PRODUTO"] = chunk["CODIGO_REFERENCIA_PRODUTO"].fillna("")

    agregado = (
        chunk.groupby(COLUNAS_GRUPO_VENDAS, dropna=False, as_index=False)
        .agg(QTD=("QUANTIDADE", "sum"))
    )
    return agregado


def normalizar_vendas(caminho_movimento: Path, caminho_produto: Path) -> pd.DataFrame:
    """Agrega QTD por loja/produto/ano/mês (sem cliente) para Liquidez."""
    from datetime import date

    ano_atual = date.today().year
    anos_permitidos = (ano_atual - 1, ano_atual)

    produtos = pd.read_csv(
        caminho_produto,
        sep=";",
        quotechar='"',
        encoding="utf-8-sig",
        dtype=str,
        usecols=[
            "ID_LOJA",
            "CODIGO_INTERNO_PRODUTO",
            "CODIGO_REFERENCIA_PRODUTO",
            "DESCRICAO_PRODUTO",
            "NOME_FABRICANTE",
        ],
    )
    produtos = produtos.rename(columns={"CODIGO_INTERNO_PRODUTO": "CODIGO_PRODUTO"})
    produtos = produtos.drop_duplicates(subset=["ID_LOJA", "CODIGO_PRODUTO"], keep="last")

    peek = pd.read_csv(
        caminho_movimento, sep=";", nrows=0, encoding="utf-8-sig", quotechar='"',
    )
    usecols = [c for c in COLS_MOVIMENTO if c in peek.columns]
    if "CODIGO_PRODUTO" not in usecols or "QUANTIDADE" not in usecols:
        raise ErroNormalizacao("Arquivo de movimento sem CODIGO_PRODUTO/QUANTIDADE.")

    inicio = time.time()
    partes: list[pd.DataFrame] = []
    leitor = pd.read_csv(
        caminho_movimento,
        sep=";",
        quotechar='"',
        encoding="utf-8-sig",
        dtype=str,
        usecols=usecols,
        chunksize=CHUNKSIZE,
    )
    for chunk in leitor:
        parte = _processar_chunk_vendas(chunk, produtos, anos_permitidos)
        if parte is not None and not parte.empty:
            partes.append(parte)

    print(f"[Liquidez/Vendas] Leitura em {time.time() - inicio:.1f}s.")
    if not partes:
        return pd.DataFrame(columns=COLUNAS_VENDAS)

    consolidado = pd.concat(partes, ignore_index=True)
    final = (
        consolidado.groupby(COLUNAS_GRUPO_VENDAS, dropna=False, as_index=False)
        .agg(QTD=("QTD", "sum"))
    )
    mascara_zero = final["QTD"].round(4) == 0
    final = final[~mascara_zero].copy()
    final["Ano"] = final["Ano"].astype(int)
    final["QTD"] = final["QTD"].apply(formatar_qtd)
    return final[COLUNAS_VENDAS]


def normalizar_liquidez_pasta(
    pasta_fonte: Path,
    pasta_trabalho: Path,
) -> tuple[Path, Path]:
    """Gera Liquidez_Estoque.csv e Liquidez_Vendas.csv no trabalho."""
    pasta_fonte = Path(pasta_fonte).resolve()
    pasta_trabalho = Path(pasta_trabalho).resolve()

    fonte_s = os.path.normcase(os.path.realpath(str(pasta_fonte)))
    trab_s = os.path.normcase(os.path.realpath(str(pasta_trabalho)))
    if trab_s == fonte_s or trab_s.startswith(fonte_s + os.sep):
        raise ErroNormalizacao(
            f"Escrita proibida na pasta fonte. pasta_trabalho ({pasta_trabalho}) "
            f"não pode ser igual a pasta_fonte nem estar dentro dela ({pasta_fonte})."
        )

    caminho_movimento, caminho_produto = resolver_arquivos_bi(pasta_fonte)
    pasta_trabalho.mkdir(parents=True, exist_ok=True)

    print(f"[Liquidez] Estoque a partir de {caminho_produto.name}...")
    df_estoque = normalizar_estoque(caminho_produto)
    caminho_estoque = pasta_trabalho / NOME_ESTOQUE
    df_estoque.to_csv(caminho_estoque, sep=";", index=False, encoding="utf-8-sig")
    print(f"[Liquidez] Gravado {caminho_estoque} ({len(df_estoque):,} linhas).")

    print(f"[Liquidez] Vendas a partir de {caminho_movimento.name}...")
    df_vendas = normalizar_vendas(caminho_movimento, caminho_produto)
    caminho_vendas = pasta_trabalho / NOME_VENDAS
    df_vendas.to_csv(caminho_vendas, sep=";", index=False, encoding="utf-8-sig")
    print(f"[Liquidez] Gravado {caminho_vendas} ({len(df_vendas):,} linhas).")

    return caminho_estoque, caminho_vendas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera Liquidez_Estoque.csv e Liquidez_Vendas.csv a partir do BI."
    )
    parser.add_argument("pasta_fonte", help="Pasta da empresa com BI/ (somente leitura)")
    parser.add_argument(
        "--trabalho",
        required=True,
        help="Pasta de escrita distinta da fonte.",
    )
    args = parser.parse_args()
    try:
        normalizar_liquidez_pasta(Path(args.pasta_fonte), Path(args.trabalho))
    except ErroNormalizacao as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        main()
