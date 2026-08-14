"""
normalizar_liquidez.py
======================

Gera as duas bases do relatório Liquidez a partir dos CSVs da fonte
(somente leitura) na pasta de trabalho da empresa:

    Liquidez_Estoque.csv  ← Dados_Estoque_<empresa>.csv
    Liquidez_Vendas.csv   ← Dados_Vendas_<empresa>.csv

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
import warnings
from datetime import date
from pathlib import Path

import pandas as pd

from normalizar_base import (
    ErroNormalizacao,
    formatar_qtd,
    ler_csv_robusto,
    normalizar_mes,
    parse_numero_flexivel,
    resolver_arquivos_dados,
    serie_texto_limpa,
    validar_colunas,
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

# Colunas esperadas em Dados_Estoque_<empresa>.csv (nomes fixos; ordem livre).
COLUNAS_ESTOQUE_ESPERADAS = {
    "Loja", "Fabricante", "Descrição", "Produto", "CODIGO_REFERENCIA_PRODUTO",
    "QTD Estoque", "Preço médio de venda", "Preço médio cmv", "Último custo",
}

RENAME_ESTOQUE = {
    "Fabricante": "NOME_FABRICANTE",
    "Descrição": "descricao",
    "Produto": "CODIGO_INTERNO_PRODUTO",
    "QTD Estoque": "Qtd_estoque",
    "Preço médio de venda": "Preço_médio_de_venda",
    "Preço médio cmv": "Preço_médio_cmv",
    "Último custo": "Último_custo",
}

# Colunas esperadas em Dados_Vendas_<empresa>.csv (nomes fixos; ordem livre).
COLUNAS_VENDAS_ESPERADAS = {
    "Loja", "NOME_FABRICANTE", "descricao", "CODIGO_INTERNO_PRODUTO",
    "CODIGO_REFERENCIA_PRODUTO", "Ano", "Mês", "QTD",
}

RENAME_VENDAS = {
    "Loja": "Nome_Loja",
}


def ler_tabela_liquidez(caminho: Path) -> pd.DataFrame:
    """Lê CSV legado ou planilha Excel sem alterar o arquivo de origem.

    Os exports mais recentes de estoque e vendas chegam em XLSX. Manter a
    escolha pelo sufixo permite reaproveitar o mesmo contrato de colunas sem
    converter manualmente a fonte para CSV.
    """
    if caminho.suffix.casefold() in {".xlsx", ".xlsm", ".xls"}:
        return pd.read_excel(caminho, dtype=str)
    return ler_csv_robusto(caminho, sep=";", quotechar='"', dtype=str)


def formatar_numero_br(valor: float, casas: int = 4) -> str:
    """Número em formato BR (vírgula decimal), sem separador de milhar."""
    if pd.isna(valor):
        return ""
    texto = f"{float(valor):.{casas}f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",")


def normalizar_estoque(caminho_estoque: Path) -> pd.DataFrame:
    """Lê Dados_Estoque_<empresa> e monta a base de estoque da Liquidez."""
    df = ler_tabela_liquidez(caminho_estoque)

    validar_colunas(df, COLUNAS_ESTOQUE_ESPERADAS, caminho_estoque.name)

    df = df.rename(columns=RENAME_ESTOQUE)
    df["CODIGO_INTERNO_PRODUTO"] = serie_texto_limpa(df["CODIGO_INTERNO_PRODUTO"])
    df = df.dropna(subset=["CODIGO_INTERNO_PRODUTO"])
    df = df.drop_duplicates(subset=["Loja", "CODIGO_INTERNO_PRODUTO"], keep="last")

    out = pd.DataFrame({
        "Loja": serie_texto_limpa(df["Loja"]),
        "NOME_FABRICANTE": serie_texto_limpa(df["NOME_FABRICANTE"]),
        "descricao": serie_texto_limpa(df["descricao"]),
        "CODIGO_INTERNO_PRODUTO": serie_texto_limpa(df["CODIGO_INTERNO_PRODUTO"]),
        "CODIGO_REFERENCIA_PRODUTO": serie_texto_limpa(df["CODIGO_REFERENCIA_PRODUTO"]).fillna(""),
        "Qtd_estoque": parse_numero_flexivel(df["Qtd_estoque"]).fillna(0.0),
        "Preço_médio_de_venda": parse_numero_flexivel(df["Preço_médio_de_venda"]).fillna(0.0),
        "Preço_médio_cmv": parse_numero_flexivel(df["Preço_médio_cmv"]).fillna(0.0),
        "Último_custo": parse_numero_flexivel(df["Último_custo"]).fillna(0.0),
    })

    for col in ("Qtd_estoque", "Preço_médio_de_venda", "Preço_médio_cmv", "Último_custo"):
        out[col] = out[col].map(lambda v: formatar_numero_br(v, 4))

    return out[COLUNAS_ESTOQUE]


def normalizar_vendas(caminho_vendas: Path) -> pd.DataFrame:
    """Lê Dados_Vendas_<empresa> e agrega QTD por loja/produto/ano/mês."""
    ano_atual = date.today().year
    anos_permitidos = (ano_atual - 1, ano_atual)

    df = ler_tabela_liquidez(caminho_vendas)

    validar_colunas(df, COLUNAS_VENDAS_ESPERADAS, caminho_vendas.name)

    df = df.rename(columns=RENAME_VENDAS)

    for col in ("Nome_Loja", "NOME_FABRICANTE", "descricao",
                "CODIGO_INTERNO_PRODUTO", "CODIGO_REFERENCIA_PRODUTO"):
        df[col] = serie_texto_limpa(df[col])
    df = df.dropna(subset=["CODIGO_INTERNO_PRODUTO"])
    df["CODIGO_REFERENCIA_PRODUTO"] = df["CODIGO_REFERENCIA_PRODUTO"].fillna("")

    df["Ano"] = pd.to_numeric(serie_texto_limpa(df["Ano"]), errors="coerce")
    df["Mês"] = normalizar_mes(df["Mês"])
    df["QTD"] = parse_numero_flexivel(df["QTD"]).fillna(0.0)

    df = df.dropna(subset=["Ano", "Mês"])
    if df.empty:
        return pd.DataFrame(columns=COLUNAS_VENDAS)

    df["Ano"] = df["Ano"].astype(int)
    df = df[df["Ano"].isin(anos_permitidos)]
    if df.empty:
        return pd.DataFrame(columns=COLUNAS_VENDAS)

    agregado = (
        df.groupby(COLUNAS_GRUPO_VENDAS, dropna=False, as_index=False)
        .agg(QTD=("QTD", "sum"))
    )
    mascara_zero = agregado["QTD"].round(4) == 0
    agregado = agregado[~mascara_zero].copy()
    agregado["QTD"] = agregado["QTD"].apply(formatar_qtd)
    return agregado[COLUNAS_VENDAS]


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

    _caminho_atacado, caminho_estoque, caminho_vendas = resolver_arquivos_dados(pasta_fonte)
    if caminho_estoque is None or caminho_vendas is None:
        raise ErroNormalizacao(
            f"Liquidez exige Dados_Estoque_{pasta_fonte.name}.* e "
            f"Dados_Vendas_{pasta_fonte.name}.* na pasta fonte."
        )
    pasta_trabalho.mkdir(parents=True, exist_ok=True)

    print(f"[Liquidez] Estoque a partir de {caminho_estoque.name}...")
    df_estoque = normalizar_estoque(caminho_estoque)
    caminho_saida_estoque = pasta_trabalho / NOME_ESTOQUE
    df_estoque.to_csv(caminho_saida_estoque, sep=";", index=False, encoding="utf-8-sig")
    print(f"[Liquidez] Gravado {caminho_saida_estoque} ({len(df_estoque):,} linhas).")

    print(f"[Liquidez] Vendas a partir de {caminho_vendas.name}...")
    df_vendas = normalizar_vendas(caminho_vendas)
    caminho_saida_vendas = pasta_trabalho / NOME_VENDAS
    df_vendas.to_csv(caminho_saida_vendas, sep=";", index=False, encoding="utf-8-sig")
    print(f"[Liquidez] Gravado {caminho_saida_vendas} ({len(df_vendas):,} linhas).")

    return caminho_saida_estoque, caminho_saida_vendas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gera Liquidez_Estoque.csv e Liquidez_Vendas.csv a partir dos CSVs da fonte."
    )
    parser.add_argument("pasta_fonte", help="Pasta da empresa com os 3 CSVs (somente leitura)")
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
