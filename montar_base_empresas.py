"""
montar_base_empresas.py
=======================

Mantém `{trabalho}/base_empresas.parquet` (empresa / loja / CNPJ) para as
empresas da pasta fonte (Dados Alvos). Ver `backend/base_empresas.py`.

Incremental: o mapa salvo fica como está. Só empresa que entrou na Dados Alvos
e ainda não está no mapa tem o `{empresa}_EMPRESA.dw_2d` buscado no DW e é
adicionada; empresa que saiu da Dados Alvos sai do mapa. `--refazer` relê o DW
de todas (use quando uma empresa abrir ou fechar loja).

Só lê o DW e a fonte; só grava no trabalho.

Uso:
    python montar_base_empresas.py
    python montar_base_empresas.py --refazer
    python montar_base_empresas.py --conferir     (mostra, não grava)

Exit code: 0 ok; 1 se empresa nova ficou sem arquivo no DW; 2 se erro de configuração.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import base_empresas  # noqa: E402
import caminhos_padrao  # noqa: E402


def _caminho(valor: str | None) -> Path | None:
    return Path(valor).expanduser().resolve() if valor else None


def main() -> None:
    parser = argparse.ArgumentParser(description="Mantém a base empresa/loja/CNPJ a partir do DW.")
    parser.add_argument("--fonte", default=os.environ.get("PRISMA_FONTE") or caminhos_padrao.fonte_dados())
    parser.add_argument("--trabalho", default=os.environ.get("PRISMA_TRABALHO") or caminhos_padrao.trabalho())
    parser.add_argument("--dw", default=os.environ.get("PRISMA_DW") or caminhos_padrao.dw())
    parser.add_argument("--refazer", action="store_true", help="Relê o DW de todas as empresas")
    parser.add_argument("--conferir", action="store_true", help="Mostra o resultado sem gravar")
    args = parser.parse_args()

    fonte, trabalho, dw = _caminho(args.fonte), _caminho(args.trabalho), _caminho(args.dw)
    if not fonte or not dw or not trabalho:
        print("ERRO: informe --fonte, --trabalho e --dw (padrões do OneDrive não encontrados).", file=sys.stderr)
        sys.exit(2)

    empresas = sorted((p.name for p in fonte.iterdir() if p.is_dir()), key=str.casefold)
    atual = (
        pd.DataFrame(columns=base_empresas.COLUNAS_BASE)
        if args.refazer else base_empresas.carregar_base(trabalho)
    )
    base, novas, removidas, avisos = base_empresas.atualizar_base(atual, dw, empresas)
    # Complemento manual (loja → CNPJ) para empresa cujo DW vem sem CNPJ.
    base, complementadas = base_empresas.aplicar_complemento(
        base, base_empresas.carregar_complemento(trabalho), empresas,
    )
    for mudanca in complementadas:
        print(f"COMPLEMENTO {mudanca}")
    # "Loja sem CNPJ" é recalculado sobre a base já complementada.
    avisos = [a for a in avisos if "sem CNPJ no DW" not in a] + [
        f"{linha.empresa}: loja {linha.id_loja!r} sem CNPJ (nem no DW nem no complemento)"
        for linha in base[base["cnpj"].fillna("") == ""].itertuples()
    ]

    print(f"DW: {dw}\nDados Alvos: {len(empresas)} empresa(s) | no mapa: {base['empresa'].nunique()} "
          f"| lojas: {len(base)} | com CNPJ: {len(base_empresas.cnpjs_por_empresa(base))}")
    print(f"Adicionadas: {', '.join(novas) or '-'}")
    print(f"Removidas (saíram da Dados Alvos): {', '.join(removidas) or '-'}")
    for aviso in avisos:
        print(f"AVISO {aviso}")
    if args.conferir:
        print(base.to_string(index=False))
        return

    if novas or removidas or complementadas or args.refazer or not (trabalho / base_empresas.NOME_BASE).is_file():
        print(f"Gravado: {base_empresas.gravar_base(base, trabalho)}")
    else:
        print("Sem empresa nova: mapa mantido.")
    faltando = [e for e in empresas if e not in set(base["empresa"])]
    if faltando:
        print(f"Sem arquivo no DW (tenta de novo na próxima): {', '.join(faltando)}")
    sys.exit(1 if faltando else 0)


if __name__ == "__main__":
    main()
