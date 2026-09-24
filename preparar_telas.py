"""
preparar_telas.py
=================

Deixa as telas do Prisma prontas de manhã: chama, para cada empresa, os mesmos
endpoints que o navegador chama ao abrir cada tela (com os mesmos parâmetros do
prefetch em `dashboard/src/utils/prefetchSequencial.ts`, escopo "todas as
lojas"), e cada endpoint grava o resultado no cache em disco
(`backend/cache_telas.py`, pasta `_cache_telas` de cada empresa no trabalho).

Chamar o endpoint — e não reimplementar o cálculo aqui — é o que garante que o
arquivo preparado é exatamente o que a tela calcularia, com a mesma chave. Se
a tela mudar de parâmetro ou de regra, este script continua certo sozinho.

Roda no lote da manhã (`executar_lote_noturno.ps1`), depois dos summaries.
Usa a mesma configuração de pastas do app nesta máquina.

Uso:
    python preparar_telas.py
    python preparar_telas.py --so IBAD Altese
    python preparar_telas.py --paralelo 4

Exit code: 0 ok; 1 se alguma tela falhou (as outras seguem).
"""

from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
import time
from datetime import datetime
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from fastapi.testclient import TestClient  # noqa: E402

import auth  # noqa: E402
import cache_telas  # noqa: E402
import main  # noqa: E402

MODOS_PERIODO = ("fechados", "completo", "mesmo_periodo")
MESES_VENDA_MEDIA = 6          # PADRAO de dashboard/src/utils/vendaMedia.ts
LIMITE_COBERTURA = 1200        # EstoquePage / EstoqueEscopo

#: (nome, rota, parâmetros). Só o que tem cache em disco — o resto é leve.
TELAS = (
    *[(f"Clientes ({m})", "/api/clientes/{e}/painel", {"modo_periodo": m}) for m in MODOS_PERIODO],
    *[(f"Diagnóstico ({m})", "/api/diagnostico/{e}", {"modo_periodo": m}) for m in MODOS_PERIODO],
    *[(f"Vendedores ({m})", "/api/vendedores/{e}", {"modo_periodo": m}) for m in MODOS_PERIODO],
    *[
        (f"Estoque resumo ({'fechado' if f else 'aberto'})", "/api/estoque/resumo/{e}",
         {"meses": MESES_VENDA_MEDIA, **({} if f else {"usar_mes_fechado": "false"})})
        for f in (True, False)
    ],
    *[
        (f"Estoque mapa ({'fechado' if f else 'aberto'})", "/api/estoque/cobertura/{e}",
         {"meses": MESES_VENDA_MEDIA, "limite": LIMITE_COBERTURA,
          **({} if f else {"usar_mes_fechado": "false"})})
        for f in (True, False)
    ],
)


_cliente: TestClient | None = None


def _cliente_http() -> TestClient:
    """Um TestClient por processo (cada worker do pool tem o seu)."""
    global _cliente
    if _cliente is None:
        _cliente = TestClient(main.app)
    return _cliente


def preparar_empresa(empresa: str) -> tuple[str, float, list[str]]:
    """Chama as telas de uma empresa; devolve (empresa, segundos, erros)."""
    cliente = _cliente_http()
    cabecalho = {"Authorization": f"Bearer {auth.criar_token('lote-manha')}"}
    t0 = time.time()
    erros: list[str] = []
    for nome, rota, params in TELAS:
        try:
            resposta = cliente.get(rota.format(e=empresa), params=params, headers=cabecalho)
        except Exception as exc:  # noqa: BLE001
            erros.append(f"{nome}: {exc}")
            continue
        # 404 = a empresa não tem aquele dado (ex.: sem dump de precificação): não é falha.
        if resposta.status_code not in (200, 404):
            erros.append(f"{nome}: HTTP {resposta.status_code} {resposta.text[:120]}")
    # O processo guarda a base de uma empresa na RAM; solta antes da próxima.
    main._cache_base_empresa.clear()
    trabalho = main._resolver_caminho_trabalho()
    if trabalho:
        cache_telas.limpar_antigos(Path(trabalho) / empresa)
    return empresa, time.time() - t0, erros


def _tamanho_base(empresa: str) -> int:
    """Bytes do movimento na fonte — as grandes vão primeiro, para não sobrarem no fim."""
    try:
        fonte = main._resolver_caminho_fonte()
        return (Path(fonte) / empresa / f"{empresa}_MOVIMENTO_ATUAL.parquet").stat().st_size
    except (OSError, TypeError):
        return 0


def main_cli() -> None:
    parser = argparse.ArgumentParser(description="Prepara o cache em disco das telas do Prisma.")
    parser.add_argument("--so", nargs="+", metavar="EMPRESA", help="Só estas empresas")
    parser.add_argument(
        "--paralelo", type=int, default=max(1, min(4, (os.cpu_count() or 2) // 2)),
        help="Empresas preparadas ao mesmo tempo, uma por processo (padrão: metade dos núcleos, até 4)",
    )
    args = parser.parse_args()

    empresas = main._listar_empresas_fonte()
    if args.so:
        empresas = [e for e in empresas if e in set(args.so)]
    if not empresas:
        print("ERRO: nenhuma empresa na pasta fonte configurada.", file=sys.stderr)
        sys.exit(2)
    empresas.sort(key=_tamanho_base, reverse=True)

    print(f"=== Preparação das telas {datetime.now():%Y-%m-%d %H:%M:%S} ===")
    print(f"Empresas: {len(empresas)} | telas por empresa: {len(TELAS)} | paralelo: {args.paralelo} | "
          f"corte D-1: {main.af.data_corte_padrao():%d/%m/%Y}", flush=True)

    inicio = time.time()
    falhas = 0
    feitas = 0

    def relatar(empresa: str, segundos: float, erros: list[str]) -> None:
        nonlocal falhas, feitas
        feitas += 1
        print(f"{'OK ' if not erros else 'ERRO'} [{feitas}/{len(empresas)}] {empresa} em {segundos:.1f}s",
              flush=True)
        for erro in erros:
            print(f"     {erro}", flush=True)
        falhas += bool(erros)

    if args.paralelo <= 1:
        for empresa in empresas:
            relatar(*preparar_empresa(empresa))
    else:
        with ProcessPoolExecutor(max_workers=args.paralelo) as pool:
            futuros = {pool.submit(preparar_empresa, e): e for e in empresas}
            for futuro in as_completed(futuros):
                try:
                    relatar(*futuro.result())
                except Exception as exc:  # noqa: BLE001 — processo morreu (memória, etc.)
                    relatar(futuros[futuro], 0.0, [f"processo falhou: {exc}"])

    print(f"\n=== Fim ({time.time() - inicio:.1f}s) - {len(empresas) - falhas} ok, {falhas} com erro ===")
    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main_cli()
