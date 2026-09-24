"""
aguardar_fonte.py
=================

Primeiro passo do lote da manhã: espera os parquets do dia chegarem na pasta
fonte (Dados Alvos) antes de processar.

Por que existe: a base vai até ontem (D-1), mas o dia de ontem só está no
arquivo depois que a exportação do dia roda — em set/2026 os parquets chegavam
entre 08:18 e 08:31. Um lote de horário fixo cedo processaria o arquivo de
anteontem e deixaria as telas prontas com um dia a menos; um de horário fixo
tarde deixaria o usuário esperando. Este passo deixa o lote começar cedo e
seguir assim que a fonte estiver lá.

"Pronto" = arquivo de movimento modificado **hoje**. Não "tem venda de ontem":
numa segunda-feira, loja fechada no domingo nunca teria esse dia.

Sai quando todas as empresas estão prontas ou quando o prazo chega — aí segue
com o que tem, e lista quem ficou para trás (a passada da tarde pega depois).
Só lê a fonte.

Uso:
    python aguardar_fonte.py                 (prazo 09:30, confere a cada 5 min)
    python aguardar_fonte.py --ate 10:00 --intervalo 120

Exit code: 0 todas prontas; 1 prazo estourado com alguma pendente.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import caminhos_padrao  # noqa: E402
from normalizar_base import ErroNormalizacao, resolver_arquivos_dados  # noqa: E402


def pendentes(fonte: Path, hoje: date) -> tuple[list[str], int]:
    """(empresas cujo movimento ainda não foi atualizado hoje, total de empresas)."""
    faltam, total = [], 0
    for pasta in sorted((p for p in fonte.iterdir() if p.is_dir()), key=lambda p: p.name.casefold()):
        try:
            movimento, _produto, _e, _v = resolver_arquivos_dados(pasta)
        except ErroNormalizacao:
            continue
        total += 1
        try:
            atualizado = date.fromtimestamp(movimento.stat().st_mtime)
        except OSError:
            atualizado = None
        if atualizado != hoje:
            faltam.append(pasta.name)
    return faltam, total


def main() -> None:
    parser = argparse.ArgumentParser(description="Espera os parquets do dia chegarem na fonte.")
    parser.add_argument("--fonte", default=caminhos_padrao.fonte_dados())
    parser.add_argument("--ate", default="09:30", help="Prazo HH:MM; depois dele segue com o que tiver")
    parser.add_argument("--intervalo", type=int, default=300, help="Segundos entre conferências")
    args = parser.parse_args()
    if not args.fonte:
        print("ERRO: pasta fonte não encontrada.", file=sys.stderr)
        sys.exit(2)

    fonte = Path(args.fonte)
    hora, minuto = (int(x) for x in args.ate.split(":"))
    prazo = datetime.now().replace(hour=hora, minute=minuto, second=0, microsecond=0)
    hoje = date.today()

    while True:
        faltam, total = pendentes(fonte, hoje)
        agora = datetime.now()
        print(f"[{agora:%H:%M}] {total - len(faltam)}/{total} empresas com o arquivo de hoje", flush=True)
        if not faltam:
            sys.exit(0)
        if agora >= prazo:
            print(f"Prazo {args.ate} atingido. Seguindo sem: {', '.join(faltam)}", flush=True)
            sys.exit(1)
        time.sleep(min(args.intervalo, max(1, (prazo - agora).total_seconds())))


if __name__ == "__main__":
    main()
