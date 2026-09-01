"""CLI noturno para gerar um segundo MD executivo por cliente da carteira.

Uso manual seguro:
    python gerar_analises_ia.py --dry-run
    python gerar_analises_ia.py --so <clientId>

A chave não é aceita por argumento. O orquestrador descriptografa DPAPI e a
expõe somente no ambiente do processo como ``OLLAMA_API_KEY``.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from uuid import UUID

RAIZ = Path(__file__).resolve().parent
BACKEND = RAIZ / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import caminhos_padrao  # noqa: E402
from dossie_ia import (  # noqa: E402
    MODELO_OLLAMA,
    ErroDossieIA,
    executar_lote,
)


def _parse_data_iso(valor: str) -> datetime:
    try:
        data = datetime.fromisoformat(valor.replace("Z", "+00:00"))
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Use data ISO 8601 em --fresh-since.") from exc
    if data.tzinfo is None:
        data = data.astimezone()
    return data


def _parse_uuid(valor: str) -> str:
    try:
        return str(UUID(valor))
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"clientId inválido: {valor}") from exc


def _argumentos() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Gera <clientId>-analise.md com CRM + métricas Prisma.",
    )
    parser.add_argument(
        "--database", type=Path,
        default=Path(caminhos_padrao.database_carteira()) if caminhos_padrao.database_carteira() else None,
        help="database_dev.xlsx da carteira (padrão: OneDrive corporativo).",
    )
    parser.add_argument(
        "--dossie", type=Path,
        default=Path(caminhos_padrao.dossie_carteira()) if caminhos_padrao.dossie_carteira() else None,
        help="Pasta com <clientId>-crm.md (padrão: Carteira/dossie).",
    )
    parser.add_argument(
        "--trabalho", type=Path,
        default=Path(caminhos_padrao.trabalho()) if caminhos_padrao.trabalho() else None,
        help="Pasta de trabalho Prisma com subpastas por empresa.",
    )
    parser.add_argument("--modelo", default=MODELO_OLLAMA, help="Modelo Ollama Cloud direto.")
    parser.add_argument("--so", nargs="+", type=_parse_uuid, metavar="CLIENT_ID")
    parser.add_argument("--fresh-since", type=_parse_data_iso, default=None)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Valida mapeamentos/fontes sem chamar API nem gravar MD.",
    )
    return parser.parse_args()


def main() -> int:
    args = _argumentos()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    if args.database is None or args.dossie is None or args.trabalho is None:
        print(
            "ERRO: caminhos padrão incompletos. Informe --database, --dossie e --trabalho.",
            file=sys.stderr,
        )
        return 2

    try:
        resultados = executar_lote(
            database=args.database.expanduser().resolve(),
            dossie=args.dossie.expanduser().resolve(),
            trabalho=args.trabalho.expanduser().resolve(),
            api_key=os.environ.get("OLLAMA_API_KEY"),
            modelo=args.modelo,
            somente_ids=set(args.so or []),
            fresh_since=args.fresh_since,
            dry_run=args.dry_run,
        )
    except ErroDossieIA as exc:
        print(f"ERRO CONFIG [{exc.codigo}]: {exc}", file=sys.stderr)
        return 2

    contagem = Counter(resultado.status for resultado in resultados)
    for resultado in resultados:
        print(
            f"{resultado.status.upper():8} {resultado.client_id} "
            f"codigo={resultado.codigo} empresa={resultado.empresa}"
        )
    print(
        "RESUMO "
        f"ok={contagem['ok']} pronto={contagem['pronto']} "
        f"erros={contagem['erro']} ignorados={contagem['ignorado']}"
    )
    return 1 if contagem["erro"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
