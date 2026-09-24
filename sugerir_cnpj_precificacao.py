"""
sugerir_cnpj_precificacao.py
============================

Sugere o CNPJ de cada pasta de empresa para o `precificacao_cnpj.json`, com
prova: compara os pares (código do produto, descrição harmonizada) que cada CNPJ
precificou no Postgres com os do `{empresa}_PRODUTO.parquet` da fonte.

Nome não serve de prova (`Gisalto` está na razão social de outra fantasia,
`LUPI` casa com dois CNPJs), e código sozinho também não: código numérico
sequencial colide entre ERPs — só por código, a 1100 MG "casava" 50-99% com
metade dos CNPJs. Código + descrição harmonizada separa: o dono fica acima de
80% e o segundo colocado abaixo de 2%.

Somente leitura, no banco e na fonte. Não grava o mapa: a decisão fica com quem
edita o arquivo, como em `precificacao_do_postgres.py`.

Uso:
    python sugerir_cnpj_precificacao.py
    python sugerir_cnpj_precificacao.py --minimo 80
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import caminhos_padrao  # noqa: E402
import precificacao_postgres as pgp  # noqa: E402
from engine import analise_funil as af  # noqa: E402
from normalizar_base import ErroNormalizacao, resolver_arquivos_dados  # noqa: E402


def chaves_do_banco(conn) -> tuple[dict[str, set[str]], dict[str, dict], dict[str, str]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct cnpj, upper(btrim(codigo)), lower(btrim(descricao))
              from historico_precificacao
             where coalesce(btrim(codigo), '') <> ''
            """
        )
        chaves: dict[str, set[str]] = {}
        for cnpj, codigo, descricao in cur.fetchall():
            chaves.setdefault(cnpj, set()).add(f"{codigo}|{descricao}")
        cur.execute(
            """
            select cnpj, count(distinct data_exportacao::date), max(data_exportacao::date)
              from historico_precificacao group by cnpj
            """
        )
        info = {c: {"rodadas": int(n), "ultima": str(d)} for c, n, d in cur.fetchall()}
        cur.execute(
            "select cnpj, coalesce(nullif(btrim(nome_fantasia), ''), btrim(razao_social)) from empresas"
        )
        nomes = dict(cur.fetchall())
    return chaves, info, nomes


def chaves_da_fonte(fonte: Path) -> tuple[dict[str, set[str]], list[str]]:
    """Pares do `_PRODUTO` de cada pasta. Arquivo que não abre (placeholder do
    OneDrive que não baixa, por exemplo) vai para a lista de falhas."""
    por_empresa: dict[str, set[str]] = {}
    falhas: list[str] = []
    for pasta in sorted(p for p in fonte.iterdir() if p.is_dir()):
        try:
            _movimento, arquivo, _estoque, _vendas = resolver_arquivos_dados(pasta)
        except ErroNormalizacao:
            continue
        colunas = ("CODIGO_INTERNO_PRODUTO", "DESCRICAO_HARMONIZADA")
        try:
            df = af._ler_tabela_empresa(arquivo, colunas, colunas)
        except Exception as exc:  # noqa: BLE001
            falhas.append(f"{pasta.name} ({exc})")
            continue
        codigo = df["CODIGO_INTERNO_PRODUTO"].fillna("").str.strip().str.upper()
        descricao = df["DESCRICAO_HARMONIZADA"].fillna("").str.strip().str.lower()
        por_empresa[pasta.name] = set(codigo + "|" + descricao)
    return por_empresa, falhas


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    parser.add_argument("--fonte", type=Path, default=caminhos_padrao.fonte_dados())
    parser.add_argument(
        "--minimo", type=float, default=80.0,
        help="%% mínimo dos pares do CNPJ achados na empresa para sugerir (padrão: 80)",
    )
    args = parser.parse_args()

    with contextlib.closing(pgp.conectar()) as conn:
        chaves, info, nomes = chaves_do_banco(conn)
    empresas, falhas = chaves_da_fonte(Path(args.fonte))
    if not empresas:
        print("Nenhum _PRODUTO legível na fonte.", file=sys.stderr)
        sys.exit(2)

    sugestoes: dict[str, list[str]] = {}
    print(f"{'CNPJ':14}  {'nome no banco':30} {'rod':>4}  {'melhor':18} {'%':>6}  {'2º':18} {'%':>6}")
    for cnpj, pares in sorted(chaves.items()):
        ranking = sorted(
            ((len(pares & ec) / len(pares) * 100, emp) for emp, ec in empresas.items()),
            reverse=True,
        )
        (p1, e1), (p2, e2) = ranking[0], ranking[1] if len(ranking) > 1 else (0.0, "-")
        marca = "  <- sugere" if p1 >= args.minimo and p2 < p1 / 2 else ""
        if marca:
            sugestoes.setdefault(e1, []).append(cnpj)
        print(
            f"{cnpj:14}  {str(nomes.get(cnpj) or '?')[:30]:30} {info[cnpj]['rodadas']:>4}  "
            f"{e1[:18]:18} {p1:6.1f}  {e2[:18]:18} {p2:6.1f}{marca}"
        )

    print("\nSugestão para precificacao_cnpj.json (confira antes de colar):")
    for empresa, cnpjs in sorted(sugestoes.items()):
        print(f'  "{empresa}": {cnpjs},')
    if falhas:
        print(f"\n{len(falhas)} empresa(s) sem prova — _PRODUTO não abriu:")
        for falha in falhas:
            print(f"  {falha}")


if __name__ == "__main__":
    main()
