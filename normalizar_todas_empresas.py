"""
normalizar_todas_empresas.py
============================

Pré-gera, de madrugada, o summary_dashboard.json(.gz) de cada empresa na pasta de
trabalho. É a única tarefa que ainda precisa rodar em lote, e a razão é o custo:
ler os CSVs de uma empresa grande é 94% do tempo de gerar um summary. Sem este
lote, o primeiro usuário que abrir cada empresa no horário comercial paga essa
espera — foi o que provocou o erro de timeout de 45s relatado no Dashboard.

Não grava mais nenhum arquivo intermediário na pasta de trabalho (nem Base.csv,
nem Liquidez_*.csv): o app lê MOVIMENTO_ATUAL.csv + PRODUTO.csv da fonte direto
em memória (ver `main._carregar_atacado_df`).

Uso:
    python normalizar_todas_empresas.py
    python normalizar_todas_empresas.py --fonte "..." --trabalho "..."
    python normalizar_todas_empresas.py --so Frandiesel

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

from normalizar_base import ErroNormalizacao, resolver_arquivos_dados

# backend/ no path para gerar summary_dashboard.json (mesmo módulo do FastAPI).
_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import caminhos_padrao  # noqa: E402
import harmonizar_clientes  # noqa: E402
from dashboard_summary import gerar_e_gravar_summary_dashboard  # noqa: E402
from monitor_empresas import obter_resumo_monitor  # noqa: E402
from engine import analise_funil as af  # noqa: E402

# Os padrões vêm de caminhos_padrao, a mesma resolução que o app usa: a raiz local
# do OneDrive contém o nome do usuário do Windows, então um caminho fixo aqui só
# funciona na máquina de quem o escreveu.
#
# Trocar o formato da fonte sem atualizar este caminho quebra o lote em
# silêncio — já aconteceu antes (fonte antiga -> "Dados Mais Atacado.xlsx" ->
# MOVIMENTO_ATUAL.csv/PRODUTO.csv) e os summaries pararam de ser atualizados
# sem ninguém notar até o timeout de 45s aparecer no Dashboard.
FONTE_PADRAO = caminhos_padrao.fonte_dados()
TRABALHO_PADRAO = caminhos_padrao.trabalho()


def _padrao_cli(variavel: str, padrao: str | None) -> Path | None:
    """Valor da variável de ambiente, senão o padrão do OneDrive, senão None.

    None é possível: numa máquina sem o OneDrive corporativo montado não há padrão
    a oferecer, e é melhor exigir --fonte/--trabalho do que montar um caminho
    inválido.
    """
    valor = os.environ.get(variavel) or padrao
    return Path(valor) if valor else None


def listar_empresas(pasta_fonte: Path) -> list[str]:
    if not pasta_fonte.is_dir():
        raise ErroNormalizacao(f"Pasta fonte inexistente: {pasta_fonte}")
    nomes: list[str] = []
    for entrada in sorted(pasta_fonte.iterdir()):
        if not entrada.is_dir():
            continue
        try:
            resolver_arquivos_dados(entrada)
        except ErroNormalizacao:
            continue
        nomes.append(entrada.name)
    return nomes


def _harmonizar_clientes(trab_emp: Path, df):
    """Mesma regra de nomes de cliente que o app aplica ao carregar a base.

    Sem isso o lote gravaria um summary com os nomes crus por cima do que o app
    produziria — o Dashboard mostraria o cliente duplicado até alguém forçar a
    regeneração.
    """
    return harmonizar_clientes.aplicar_em_cliente(
        df, harmonizar_clientes.carregar_regra(trab_emp),
    )


def _gerar_summary(fonte_emp: Path, trab_emp: Path) -> Path:
    """Summary lendo MOVIMENTO_ATUAL + PRODUTO da fonte direto, sem arquivo intermediário.

    Mesmo caminho que o app usa em runtime, o que garante que o arquivo pré-gerado
    aqui é idêntico ao que ele produziria sozinho: o único jeito de o lote não
    virar uma segunda implementação que divirja com o tempo.
    """
    caminho_movimento, caminho_produto, _estoque, _vendas = resolver_arquivos_dados(fonte_emp)
    df_bruto = af.carregar_csv_base_empresa(caminho_movimento, caminho_produto)
    df, _linhas_vazias = af.validar_e_limpar(df_bruto, receita_em_texto_br=False)
    return gerar_e_gravar_summary_dashboard(trab_emp, _harmonizar_clientes(trab_emp, df))


def normalizar_lote(
    pasta_fonte: Path,
    pasta_trabalho: Path,
    *,
    so: list[str] | None = None,
    log_path: Path | None = None,
) -> tuple[int, int]:
    """Retorna (ok, falhas)."""
    empresas = listar_empresas(pasta_fonte)
    if so:
        filtro = {n.strip() for n in so if n.strip()}
        desconhecidas = sorted(filtro - set(empresas))
        if desconhecidas:
            raise ErroNormalizacao(
                "Empresa(s) sem MOVIMENTO_ATUAL.csv/PRODUTO.csv na fonte: " + ", ".join(desconhecidas)
            )
        empresas = [n for n in empresas if n in filtro]

    if not empresas:
        raise ErroNormalizacao(
            f"Nenhuma empresa com MOVIMENTO_ATUAL.csv/PRODUTO.csv em {pasta_fonte}"
        )

    log_linhas: list[str] = []
    inicio_lote = time.time()
    cabecalho = (
        f"=== Pré-geração de summaries {datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
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
            caminho_summary = _gerar_summary(fonte_emp, trab_emp)
            destino = str(caminho_summary)
            # O resumo do Monitoramento é DERIVADO do summary, e o cache dele é
            # invalidado pelo mtime do summary que acabou de ser reescrito. Sem
            # regerar aqui, todo dia o primeiro usuário a abrir a tela pagava a
            # reconstrução dos 46 resumos — 18s de CPU com os arquivos já locais,
            # mais o download dos ~65 MB de summary numa máquina onde o OneDrive
            # ainda não baixou. Com o resumo pronto, a tela abre em 0,4s.
            resumo_monitor = "resumo ok"
            try:
                if obter_resumo_monitor(trab_emp, forcar=True) is None:
                    resumo_monitor = "sem resumo (summary não encontrado)"
            except Exception as exc:  # noqa: BLE001
                # O summary é o produto do lote; falhar no derivado não pode
                # marcar a empresa como erro nem abortar as seguintes.
                resumo_monitor = f"resumo falhou: {exc}"
                print(f"AVISO {marcador}: {resumo_monitor}", file=sys.stderr)

            elapsed = time.time() - t0
            msg = (
                f"OK  {marcador} em {elapsed:.1f}s -> {destino} "
                f"(summary: {caminho_summary.name}, {resumo_monitor})"
            )
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
        f"\n=== Fim do lote ({time.time() - inicio_lote:.1f}s) - "
        f"{ok} ok, {falhas} erro(s) ==="
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
        description=(
            "Pré-gera summary_dashboard.json(.gz) de todas as empresas na pasta "
            "de trabalho, lendo MOVIMENTO_ATUAL.csv + PRODUTO.csv da fonte."
        )
    )
    parser.add_argument(
        "--fonte",
        type=Path,
        default=_padrao_cli("PRISMA_FONTE", FONTE_PADRAO),
        help=f"Pasta fonte, uma subpasta por empresa (padrão: {FONTE_PADRAO})",
    )
    parser.add_argument(
        "--trabalho",
        type=Path,
        default=_padrao_cli("PRISMA_TRABALHO", TRABALHO_PADRAO),
        help=f"Pasta de trabalho (padrão: {TRABALHO_PADRAO})",
    )
    parser.add_argument(
        "--so",
        nargs="+",
        metavar="EMPRESA",
        help="Normaliza só estas empresas (nomes das pastas)",
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=None,
        help="Arquivo de log (padrão: <trabalho>/_logs/normalizacao-YYYY-MM-DD.log)",
    )
    args = parser.parse_args()

    if args.fonte is None or args.trabalho is None:
        print(
            "ERRO: não foi possível descobrir as pastas padrão no OneDrive. "
            "Informe --fonte e --trabalho.",
            file=sys.stderr,
        )
        sys.exit(2)

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
