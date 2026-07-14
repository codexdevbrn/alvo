"""
Harmoniza a coluna `descricao` do Base.csv de uma empresa usando a planilha
de harmonização (harm.xlsx) da própria empresa.

Uso:
    python harmonizar_descricoes.py "base-clientes/teste"
    python harmonizar_descricoes.py "base-clientes/teste" --harm outra.xlsx --base Base.csv
    python harmonizar_descricoes.py "base-clientes/teste" --dry-run

Lógica de match:
- A planilha de harmonização tem 2 colunas relevantes: a PRIMEIRA é o código
  do produto (deve bater com a coluna `Código Interno` do Base.csv) e a
  SEGUNDA é a descrição harmonizada. A leitura tenta primeiro pelos nomes
  conhecidos ("CODIGO_INTERNO_PRODUTO" / "Descrição") e, se não encontrar,
  cai no fallback por posição (1ª e 2ª colunas).
- Match encontrado com descrição harmonizada não vazia -> usa a harmonizada.
- Sem match, ou match com descrição vazia/nula -> `descricao` fica VAZIA
  (em branco). Isso é proposital: o motor de análise
  (backend/engine/analise_funil.py) rotula descrição vazia/NaN como
  "Não harmonizados", que é exatamente o comportamento da base de produção
  do Power BI (GABARITO HARM[descricao]).

Segurança:
- Antes de sobrescrever o Base.csv, é criado um backup `Base.antes-harm.csv`
  na mesma pasta — apenas na PRIMEIRA execução (se o backup já existir, ele é
  preservado, para não perder o estado original em re-execuções).
- Alternativamente, use --dry-run para só imprimir o relatório sem gravar.

Formato preservado:
- Tudo é lido como texto (dtype=str), então a formatação numérica BR da
  receita ("1.234,56"), zeros à esquerda em códigos etc. saem intactos;
  só a coluna `descricao` é alterada. Saída: sep ';', encoding utf-8-sig.
"""

import argparse
import os
import shutil
import sys
import warnings

import pandas as pd

COLUNA_CODIGO_BASE = "Código Interno"
COLUNA_DESCRICAO_BASE = "descricao"

# Nomes conhecidos das colunas da planilha de harmonização (com fallback
# por posição caso a planilha use outros nomes).
NOMES_COLUNA_CODIGO_HARM = ("CODIGO_INTERNO_PRODUTO",)
NOMES_COLUNA_DESCRICAO_HARM = ("Descrição", "Descricao", "DESCRICAO")


def carregar_harmonizacao(caminho_harm: str) -> dict[str, str]:
    """Lê a planilha de harmonização e devolve {codigo: descricao_harmonizada}.

    Só entram no dicionário pares com código E descrição não vazios — códigos
    sem descrição harmonizada devem resultar em descricao vazia no Base.csv,
    o que já é o comportamento padrão de "sem match".
    """
    with warnings.catch_warnings():
        # openpyxl emite um UserWarning inofensivo de "no default style"
        warnings.simplefilter("ignore", UserWarning)
        planilha = pd.read_excel(caminho_harm, dtype=str)

    col_codigo = next((c for c in NOMES_COLUNA_CODIGO_HARM if c in planilha.columns), None)
    col_descricao = next((c for c in NOMES_COLUNA_DESCRICAO_HARM if c in planilha.columns), None)
    if col_codigo is None:
        col_codigo = planilha.columns[0]
    if col_descricao is None:
        col_descricao = planilha.columns[1]

    mapa: dict[str, str] = {}
    for codigo, descricao in zip(planilha[col_codigo], planilha[col_descricao]):
        if pd.isna(codigo) or pd.isna(descricao):
            continue
        codigo = str(codigo).strip()
        descricao = str(descricao).strip()
        if codigo and descricao:
            mapa[codigo] = descricao
    return mapa


def harmonizar(pasta_empresa: str, nome_harm: str, nome_base: str, dry_run: bool) -> None:
    caminho_base = os.path.join(pasta_empresa, nome_base)
    caminho_harm = (
        nome_harm if os.path.isabs(nome_harm) else os.path.join(pasta_empresa, nome_harm)
    )

    for caminho, rotulo in ((caminho_base, "arquivo base"), (caminho_harm, "planilha de harmonização")):
        if not os.path.exists(caminho):
            sys.exit(f"ERRO: {rotulo} não encontrado: {caminho}")

    print(f"Lendo planilha de harmonização: {caminho_harm}")
    mapa = carregar_harmonizacao(caminho_harm)
    print(f"  {len(mapa)} códigos com descrição harmonizada.")

    print(f"Lendo base: {caminho_base}")
    # dtype=str preserva a formatação original (receita BR, códigos etc.);
    # keep_default_na=False evita que células vazias virem "nan" na regravação.
    df = pd.read_csv(caminho_base, sep=";", encoding="utf-8-sig", dtype=str, keep_default_na=False)

    for coluna in (COLUNA_CODIGO_BASE, COLUNA_DESCRICAO_BASE):
        if coluna not in df.columns:
            sys.exit(f"ERRO: coluna '{coluna}' não encontrada no {nome_base}. Colunas: {list(df.columns)}")

    codigos = df[COLUNA_CODIGO_BASE].str.strip()
    df[COLUNA_DESCRICAO_BASE] = codigos.map(mapa).fillna("")

    total = len(df)
    harmonizadas = int((df[COLUNA_DESCRICAO_BASE] != "").sum())
    nao_harmonizadas = total - harmonizadas

    print()
    print("=== Relatório de harmonização ===")
    print(f"Total de linhas:           {total:,}".replace(",", "."))
    print(f"Com descrição harmonizada: {harmonizadas:,}".replace(",", ".") + f" ({harmonizadas / total:.1%})")
    print(f"Sem harmonização (vazias): {nao_harmonizadas:,}".replace(",", ".") + f" ({nao_harmonizadas / total:.1%})")
    print()
    print("Top 10 descrições harmonizadas por contagem de linhas:")
    top10 = df.loc[df[COLUNA_DESCRICAO_BASE] != "", COLUNA_DESCRICAO_BASE].value_counts().head(10)
    for descricao, contagem in top10.items():
        print(f"  {descricao:<40} {contagem:>8,}".replace(",", "."))

    if dry_run:
        print("\n--dry-run: nada foi gravado.")
        return

    caminho_backup = os.path.join(pasta_empresa, "Base.antes-harm.csv")
    if not os.path.exists(caminho_backup):
        shutil.copy2(caminho_base, caminho_backup)
        print(f"\nBackup criado: {caminho_backup}")
    else:
        print(f"\nBackup já existia (preservado): {caminho_backup}")

    df.to_csv(caminho_base, sep=";", encoding="utf-8-sig", index=False)
    print(f"Base sobrescrita com descrições harmonizadas: {caminho_base}")


def main():
    parser = argparse.ArgumentParser(description="Harmoniza a coluna descricao do Base.csv de uma empresa.")
    parser.add_argument("pasta_empresa", help="Pasta da empresa (ex: base-clientes/teste)")
    parser.add_argument("--harm", default="harm.xlsx",
                        help="Planilha de harmonização (padrão: harm.xlsx dentro da pasta da empresa)")
    parser.add_argument("--base", default="Base.csv",
                        help="Nome do arquivo base dentro da pasta (padrão: Base.csv)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Só imprime o relatório, sem gravar nada")
    args = parser.parse_args()

    harmonizar(args.pasta_empresa, args.harm, args.base, args.dry_run)


if __name__ == "__main__":
    main()
