"""
normalizar_todas_empresas.py
============================

Normaliza em lote todas as empresas da pasta fonte (subpastas com BI/)
para a pasta de trabalho: Base.csv + Liquidez_*.csv via normalizar_pasta_empresa.

Pensado para rodar de madrugada (Agendador de Tarefas). No horário comercial
o app só lê o CSV pronto (_ensure_base_csv não regenera automaticamente;
só o botão Regenerar base ou este lote atualizam os arquivos).

Uso:
    python normalizar_todas_empresas.py
    python normalizar_todas_empresas.py --fonte "..." --trabalho "..."
    python normalizar_todas_empresas.py --so Frandiesel
    python normalizar_todas_empresas.py --sem-harmonizacao --sem-validacao

Exit code: 0 se todas ok; 1 se alguma falhou; 2 se erro de configuração.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
import traceback
import warnings
from datetime import datetime
from pathlib import Path

from normalizar_base import ErroNormalizacao, normalizar_pasta_empresa

# Defaults alinhados ao ambiente 2D (podem ser sobrescritos por CLI / env).
FONTE_PADRAO = Path(
    r"C:\Users\bi_2d_gzgh6n0\OneDrive - 2dconsultores.com.br\DB\DW"
)
TRABALHO_PADRAO = Path(
    r"C:\Users\bi_2d_gzgh6n0\OneDrive - 2dconsultores.com.br"
    r"\01 - Marco + Monitores\Ecossistema-Monitoria\analisador"
)


def listar_empresas(pasta_fonte: Path) -> list[str]:
    if not pasta_fonte.is_dir():
        raise ErroNormalizacao(f"Pasta fonte inexistente: {pasta_fonte}")
    nomes: list[str] = []
    for entrada in sorted(pasta_fonte.iterdir()):
        if not entrada.is_dir():
            continue
        if (entrada / "BI").is_dir():
            nomes.append(entrada.name)
    return nomes


def normalizar_lote(
    pasta_fonte: Path,
    pasta_trabalho: Path,
    *,
    so: list[str] | None = None,
    aplicar_harmonizacao: bool = True,
    validar_resultado: bool = True,
    log_path: Path | None = None,
) -> tuple[int, int]:
    """Retorna (ok, falhas)."""
    empresas = listar_empresas(pasta_fonte)
    if so:
        filtro = {n.strip() for n in so if n.strip()}
        desconhecidas = sorted(filtro - set(empresas))
        if desconhecidas:
            raise ErroNormalizacao(
                "Empresa(s) sem BI/ na fonte: " + ", ".join(desconhecidas)
            )
        empresas = [n for n in empresas if n in filtro]

    if not empresas:
        raise ErroNormalizacao(f"Nenhuma empresa com BI/ em {pasta_fonte}")

    log_linhas: list[str] = []
    inicio_lote = time.time()
    cabecalho = (
        f"=== Normalização em lote {datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
        f"Fonte:    {pasta_fonte}\n"
        f"Trabalho: {pasta_trabalho}\n"
        f"Empresas: {len(empresas)}\n"
    )
    print(cabecalho)
    log_linhas.append(cabecalho)

    ok = 0
    falhas = 0
    for i, nome in enumerate(empresas, start=1):
        fonte_emp = pasta_fonte / nome
        trab_emp = pasta_trabalho / nome
        marcador = f"[{i}/{len(empresas)}] {nome}"
        print("\n" + "=" * 70)
        print(marcador)
        print("=" * 70)
        t0 = time.time()
        try:
            caminho = normalizar_pasta_empresa(
                fonte_emp,
                pasta_trabalho=trab_emp,
                aplicar_harmonizacao=aplicar_harmonizacao,
                validar_resultado=validar_resultado,
            )
            elapsed = time.time() - t0
            msg = f"OK  {marcador} em {elapsed:.1f}s → {caminho}"
            print(msg)
            log_linhas.append(msg)
            ok += 1
        except Exception as exc:
            elapsed = time.time() - t0
            msg = f"ERRO {marcador} após {elapsed:.1f}s: {exc}"
            print(msg, file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
            log_linhas.append(msg)
            log_linhas.append(traceback.format_exc())
            falhas += 1

    resumo = (
        f"\n=== Fim do lote ({time.time() - inicio_lote:.1f}s) — "
        f"{ok} ok, {falhas} erro(s) ===\n"
    )
    print(resumo)
    log_linhas.append(resumo)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(log_linhas) + "\n")
        print(f"Log: {log_path}")

    return ok, falhas


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Normaliza todas as empresas (BI → Base.csv + Liquidez) na pasta de trabalho."
    )
    parser.add_argument(
        "--fonte",
        type=Path,
        default=Path(os.environ.get("PRISMA_FONTE", FONTE_PADRAO)),
        help=f"Pasta fonte com subpastas/BI (padrão: {FONTE_PADRAO})",
    )
    parser.add_argument(
        "--trabalho",
        type=Path,
        default=Path(os.environ.get("PRISMA_TRABALHO", TRABALHO_PADRAO)),
        help=f"Pasta de trabalho (padrão: {TRABALHO_PADRAO})",
    )
    parser.add_argument(
        "--so",
        nargs="+",
        metavar="EMPRESA",
        help="Normaliza só estas empresas (nomes das pastas)",
    )
    parser.add_argument("--sem-harmonizacao", action="store_true")
    parser.add_argument("--sem-validacao", action="store_true")
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Arquivo de log (padrão: <trabalho>/_logs/normalizacao-YYYY-MM-DD.log)",
    )
    args = parser.parse_args()

    fonte = args.fonte.expanduser().resolve()
    trabalho = args.trabalho.expanduser().resolve()
    log_path = args.log
    if log_path is None:
        log_path = trabalho / "_logs" / f"normalizacao-{datetime.now():%Y-%m-%d}.log"
    else:
        log_path = log_path.expanduser().resolve()

    try:
        _ok, falhas = normalizar_lote(
            fonte,
            trabalho,
            so=args.so,
            aplicar_harmonizacao=not args.sem_harmonizacao,
            validar_resultado=not args.sem_validacao,
            log_path=log_path,
        )
    except ErroNormalizacao as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(2)

    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        main()
