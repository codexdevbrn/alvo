"""
precificacao_do_postgres.py
===========================

Gera o `{empresa}_PRECIFICACAO.parquet` de cada empresa na pasta de **trabalho**,
lendo o histórico do Postgres. Substitui a exportação manual que antes aparecia
na pasta fonte.

Por que em lote, e não no request: o Postgres está em IP público e **não suporta
SSL** (o servidor recusa `sslmode=require`), então credencial e dados trafegam em
claro. Ler no backend do app obrigaria toda máquina com o exe a carregar a
credencial e alcançar o banco — quem tivesse o exe teria leitura da precificação
de todas as empresas. Aqui a credencial fica só na máquina do lote, e a máquina
cliente continua lendo arquivo, como sempre fez.

Leitura do banco é somente-leitura (ver `backend/precificacao_postgres.py`).
Escrita acontece só na pasta de trabalho; a fonte nunca é tocada.

**Rodada é o dia.** `data_exportacao` é gravado por linha, em microssegundo, e o
tamanho da rodada varia de 3 a ~15 mil linhas na mesma empresa. Por isso o
arquivo leva **todas** as rodadas (ou as N últimas, com `--rodadas N`) e quem
consome escolhe qual usar — assumir "a mais recente" faria a tela do IBAD cair
de 3804 linhas para 3. Antes o padrão era 3, o que cortava o Histórico: a
Altese tem 63 rodadas desde ago/2025, e o efeito de uma precificação só se lê
contra as anteriores. O maior arquivo (Altese) fica em ~56 mil linhas.

Mapa empresa -> CNPJ
--------------------
O nome da pasta não é derivável do nome da empresa (`Gisalto` está na razão
social, não na fantasia; `LUPI` casa com dois CNPJs diferentes; pastas vão de
`IBAD` a `alianca_itaborai`), e 26 dos 43 CNPJs do histórico não existem na
tabela `empresas`. Casar por semelhança de nome atribuiria a precificação de uma
empresa à pasta de outra, então o mapa é explícito:

    <trabalho>/precificacao_cnpj.json
    {"IBAD": ["01709513000139"], "Altese": ["31263577000110", "31263577000209"]}

Uma pasta pode ter vários CNPJs (matriz e filial). Para preencher o mapa com
prova, e não por nome, use `sugerir_cnpj_precificacao.py`.

Só regera quem precisa
----------------------
Antes de baixar linha, o lote compara a assinatura do recorte no banco
(contagem, dias e extremos de `data_exportacao`) com a do parquet já gravado.
Iguais, a empresa é pulada — nem a consulta de dados sai. Empresa sem
precificação nova custa uma agregação, não 18 mil linhas.

A assinatura leva contagem e extremos, não só o timestamp mais recente, porque
rodada corrigida com data antiga não move o máximo, e mudar `--rodadas` muda o
recorte sem mudar a última data.

Na primeira passada todo mundo é regerado de propósito: a exportação manual
truncava o timestamp em milissegundo (`.490000`) e o banco tem microssegundo
(`.490185`), então nenhuma assinatura antiga casa. Da segunda em diante o
arquivo é gerado aqui e a comparação fica exata.

Uso:
    python precificacao_do_postgres.py
    python precificacao_do_postgres.py --so IBAD
    python precificacao_do_postgres.py --conferir
    python precificacao_do_postgres.py --rodadas 5
    python precificacao_do_postgres.py --forcar

Exit code: 0 se todas ok; 1 se alguma falhou; 2 se erro de configuração.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).resolve().parent / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import caminhos_padrao  # noqa: E402
import base_empresas  # noqa: E402
import precificacao_postgres as pgp  # noqa: E402

FONTE_PADRAO = caminhos_padrao.fonte_dados()
TRABALHO_PADRAO = caminhos_padrao.trabalho()

NOME_MAPA = "precificacao_cnpj.json"
SUFIXO_DUMP = "_PRECIFICACAO.parquet"
#: `None` = todas as rodadas do banco.
RODADAS_PADRAO: int | None = None


class ErroLote(RuntimeError):
    """Erro de configuração do lote — aborta antes de qualquer escrita."""


def _normpath(caminho: str | Path) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(str(caminho))))


def _esta_sob(caminho: str | Path, raiz: str | Path) -> bool:
    """True se `caminho` é a própria `raiz` ou está dentro dela."""
    c, r = _normpath(caminho), _normpath(raiz)
    return c == r or c.startswith(r + os.sep)


def exigir_trabalho_fora_da_fonte(fonte: Path, trabalho: Path) -> None:
    """A fonte é somente-leitura absoluta: nada do lote pode cair dentro dela."""
    if _esta_sob(trabalho, fonte) or _esta_sob(fonte, trabalho):
        raise ErroLote(
            "Pasta de trabalho e fonte não podem ser a mesma nem uma dentro da "
            f"outra.\n  fonte:    {fonte}\n  trabalho: {trabalho}"
        )


def carregar_mapa(trabalho: Path) -> dict[str, list[str]]:
    """Lê `precificacao_cnpj.json` da raiz do trabalho. Ausente = mapa vazio."""
    caminho = trabalho / NOME_MAPA
    if not caminho.is_file():
        return {}
    try:
        bruto = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ErroLote(f"{NOME_MAPA} inválido ({exc}); corrija ou remova o arquivo.") from exc
    if not isinstance(bruto, dict):
        raise ErroLote(f"{NOME_MAPA} deve ser um objeto empresa -> lista de CNPJ.")

    mapa: dict[str, list[str]] = {}
    for empresa, valor in bruto.items():
        lista = [valor] if isinstance(valor, str) else list(valor or [])
        cnpjs = pgp._normalizar_cnpjs(lista)
        if cnpjs:
            mapa[str(empresa)] = cnpjs
    return mapa


def assinatura_arquivo(caminho: Path) -> dict | None:
    """Assinatura do dump já gravado, no mesmo formato da assinatura do banco.

    Lê só a coluna `data_exportacao` — a decisão de regerar não precisa do
    resto. `None` quando o arquivo não existe ou não é legível, e aí o lote
    regera: arquivo ilegível é pior que arquivo reescrito.
    """
    if not caminho.is_file():
        return None
    try:
        df = pd.read_parquet(caminho, columns=["data_exportacao"])
    except Exception:
        return None
    datas = pd.to_datetime(df["data_exportacao"], errors="coerce").dropna()
    if datas.empty:
        return None
    return {
        "linhas": int(len(datas)),
        "dias": sorted({d.isoformat() for d in datas.dt.date.unique()}),
        "ultima": datas.max().isoformat(),
        "primeira": datas.min().isoformat(),
    }


def resolver_cnpjs(
    empresa: str, mapa: dict[str, list[str]], base: dict[str, list[str]] | None = None,
) -> tuple[list[str], str]:
    """(cnpjs, origem). A base do DW (`base_empresas.parquet`, loja → CNPJ
    oficial) vem primeiro; o `precificacao_cnpj.json` fica de reserva para
    empresa que o DW não cobre (a Cativo exporta as lojas sem CNPJ)."""
    if base and base.get(empresa):
        return base[empresa], "base DW"
    if empresa in mapa:
        return mapa[empresa], "mapa"
    return [], "sem mapa"


def gravar_dump(trab_emp: Path, empresa: str, df: pd.DataFrame) -> Path:
    """Grava o parquet que `carregar_csv_precificacao` lê.

    Parquet guarda o timestamp com microssegundo e o CNPJ como texto sem
    esforço; no CSV de antes o primeiro dependia do formato de escrita e o
    segundo de `dtype` na leitura. Troca atômica (tmp + replace) para o app nunca ler
    arquivo pela metade se o lote morrer no meio da escrita.
    """
    trab_emp.mkdir(parents=True, exist_ok=True)
    destino = trab_emp / f"{empresa}{SUFIXO_DUMP}"
    tmp = trab_emp / f".{empresa}{SUFIXO_DUMP}.tmp"
    df.to_parquet(tmp, index=False)
    os.replace(tmp, destino)
    return destino


def _resumo_rodadas(df: pd.DataFrame) -> str:
    if df.empty:
        return "nenhuma rodada"
    por_dia = df.groupby(df["data_exportacao"].dt.date).size().sort_index(ascending=False)
    return "  ".join(f"{dia}:{n}L" for dia, n in por_dia.items())


def _candidatos_por_nome(conn, empresa: str) -> list[str]:
    """Sugestão advisória de CNPJ para pasta sem mapa. Nunca aplicada sozinha.

    Existe só para encurtar o preenchimento manual: casar nome com pasta erra
    (`LUPI` casa com dois CNPJs), então a decisão fica com quem edita o mapa.
    """
    token = "".join(c for c in empresa.lower() if c.isalnum())
    if len(token) < 3:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            select distinct e.cnpj,
                   coalesce(nullif(btrim(e.nome_fantasia), ''), btrim(e.razao_social), '')
              from empresas e
              join historico_precificacao hp on hp.cnpj = e.cnpj
             where lower(regexp_replace(coalesce(e.razao_social, ''), '[^a-zA-Z0-9]', '', 'g')) like %s
                or lower(regexp_replace(coalesce(e.nome_fantasia, ''), '[^a-zA-Z0-9]', '', 'g')) like %s
             limit 5
            """,
            (f"%{token}%", f"%{token}%"),
        )
        return [f"{cnpj} ({nome})" for cnpj, nome in cur.fetchall()]


def rodar_lote(
    fonte: Path,
    trabalho: Path,
    *,
    so: list[str] | None = None,
    rodadas: int | None = RODADAS_PADRAO,
    conferir: bool = False,
    forcar: bool = False,
    log_path: Path | None = None,
) -> tuple[int, int, int, list[str]]:
    """Retorna (gerados, falhas, inalterados, empresas_sem_mapa)."""
    exigir_trabalho_fora_da_fonte(fonte, trabalho)
    if not fonte.is_dir():
        raise ErroLote(f"Pasta fonte inexistente: {fonte}")
    if not conferir and not trabalho.is_dir():
        raise ErroLote(f"Pasta de trabalho inexistente: {trabalho}")

    pastas = sorted(p for p in fonte.iterdir() if p.is_dir())
    if so:
        filtro = {n.strip() for n in so if n.strip()}
        desconhecidas = sorted(filtro - {p.name for p in pastas})
        if desconhecidas:
            raise ErroLote("Pasta(s) inexistente(s) na fonte: " + ", ".join(desconhecidas))
        pastas = [p for p in pastas if p.name in filtro]
    if not pastas:
        raise ErroLote(f"Nenhuma subpasta de empresa em {fonte}")

    mapa = carregar_mapa(trabalho)
    base = base_empresas.cnpjs_por_empresa(base_empresas.carregar_base(trabalho))
    linhas_log: list[str] = []
    inicio = time.time()
    cabecalho = (
        f"=== Dump de precificação do Postgres {datetime.now():%Y-%m-%d %H:%M:%S} ===\n"
        f"Fonte:    {fonte}\n"
        f"Trabalho: {trabalho}\n"
        f"Empresas: {len(pastas)} | rodadas por empresa: {rodadas or 'todas'}"
        f"{' | CONFERIR (não grava)' if conferir else ''}"
        f"{' | FORÇAR (regera tudo)' if forcar else ''}\n"
        f"Base DW:  {base_empresas.NOME_BASE} com {len(base)} empresa(s) | reserva {NOME_MAPA}: {len(mapa)}\n"
    )
    print(cabecalho)
    linhas_log.append(cabecalho)

    # CNPJ resolvido antes de conectar: assim a assinatura de todas as empresas
    # sai numa consulta só, em vez de uma por empresa.
    alvos: list[tuple[str, list[str], str]] = []
    sem_mapa: list[str] = []
    for fonte_emp in pastas:
        cnpjs, origem = resolver_cnpjs(fonte_emp.name, mapa, base)
        if cnpjs:
            alvos.append((fonte_emp.name, cnpjs, origem))
        else:
            sem_mapa.append(fonte_emp.name)

    gerados = falhas = inalterados = 0
    with contextlib.closing(pgp.conectar()) as conn:
        todos_cnpjs = [c for _e, cnpjs, _o in alvos for c in cnpjs]
        assinaturas = pgp.assinaturas_por_cnpj(conn, todos_cnpjs, rodadas=rodadas)

        for i, empresa in enumerate(sem_mapa, start=1):
            sugestoes = _candidatos_por_nome(conn, empresa)
            msg = f"PULA [{i}/{len(sem_mapa)}] {empresa}: sem CNPJ na base do DW nem no mapa."
            if sugestoes:
                msg += " Candidatos (confira antes de usar): " + "; ".join(sugestoes)
            print(msg)
            linhas_log.append(msg)

        for i, (empresa, cnpjs, origem) in enumerate(alvos, start=1):
            marcador = f"[{i}/{len(alvos)}] {empresa}"
            t0 = time.time()
            try:
                no_banco = pgp.dobrar_assinatura(assinaturas, cnpjs)
                if no_banco is None:
                    msg = (
                        f"PULA {marcador}: CNPJ {', '.join(cnpjs)} ({origem}) "
                        "sem linha em historico_precificacao."
                    )
                    print(msg)
                    linhas_log.append(msg)
                    continue

                destino = trabalho / empresa / f"{empresa}{SUFIXO_DUMP}"
                no_arquivo = assinatura_arquivo(destino)
                if not forcar and no_arquivo == no_banco:
                    msg = (
                        f"IGUAL {marcador}: sem precificação nova "
                        f"(última {no_banco['ultima']}, {no_banco['linhas']} linhas)."
                    )
                    print(msg)
                    linhas_log.append(msg)
                    inalterados += 1
                    continue

                df = pgp.carregar_ultimas_rodadas(conn, cnpjs, rodadas=rodadas)
                if df.empty:
                    msg = f"PULA {marcador}: consulta voltou vazia após a assinatura indicar mudança."
                    print(msg, file=sys.stderr)
                    linhas_log.append(msg)
                    continue
                caminho = "(não gravado)" if conferir else str(
                    gravar_dump(trabalho / empresa, empresa, df)
                )
                if no_arquivo is None:
                    motivo = "primeira geração"
                elif no_arquivo == no_banco:
                    motivo = "forçado"
                else:
                    motivo = "precificação nova"
                msg = (
                    f"OK  {marcador} em {time.time() - t0:.1f}s | {motivo} | "
                    f"{len(df)} linhas | cnpj {', '.join(cnpjs)} ({origem}) | "
                    f"{_resumo_rodadas(df)} -> {caminho}"
                )
                print(msg)
                linhas_log.append(msg)
                gerados += 1
            except Exception as exc:  # noqa: BLE001
                msg = f"ERRO {marcador} após {time.time() - t0:.1f}s: {exc}"
                print(msg, file=sys.stderr)
                print(traceback.format_exc(), file=sys.stderr)
                linhas_log.append(msg)
                linhas_log.append(traceback.format_exc())
                falhas += 1

    resumo = (
        f"\n=== Fim ({time.time() - inicio:.1f}s) - {gerados} gerado(s), "
        f"{inalterados} sem mudança, {falhas} erro(s), {len(sem_mapa)} sem mapa ==="
    )
    print(resumo)
    linhas_log.append(resumo)
    if sem_mapa:
        esqueleto = json.dumps({e: [] for e in sem_mapa}, indent=2, ensure_ascii=False)
        aviso = (
            f"\nPara incluir as {len(sem_mapa)} pasta(s) sem mapa, preencha os CNPJ em "
            f"{trabalho / NOME_MAPA}:\n{esqueleto}"
        )
        print(aviso)
        linhas_log.append(aviso)

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("\n".join(linhas_log) + "\n")
        print(f"Log: {log_path}")

    return gerados, falhas, inalterados, sem_mapa


def _padrao_cli(variavel: str, padrao: str | None) -> Path | None:
    valor = os.environ.get(variavel) or padrao
    return Path(valor) if valor else None


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Gera {empresa}_PRECIFICACAO.parquet na pasta de trabalho a partir do "
            "histórico de precificação no Postgres (leitura somente)."
        )
    )
    parser.add_argument(
        "--fonte", type=Path, default=_padrao_cli("PRISMA_FONTE", FONTE_PADRAO),
        help=f"Pasta fonte, uma subpasta por empresa (padrão: {FONTE_PADRAO})",
    )
    parser.add_argument(
        "--trabalho", type=Path, default=_padrao_cli("PRISMA_TRABALHO", TRABALHO_PADRAO),
        help=f"Pasta de trabalho, onde o dump é gravado (padrão: {TRABALHO_PADRAO})",
    )
    parser.add_argument(
        "--so", nargs="+", metavar="EMPRESA", help="Só estas empresas (nomes das pastas)",
    )
    parser.add_argument(
        "--rodadas", type=int, default=RODADAS_PADRAO,
        help="Quantas rodadas (dias) mais recentes incluir (padrão: todas)",
    )
    parser.add_argument(
        "--conferir", action="store_true",
        help="Mostra o que faria (mapa, rodadas, volume) sem gravar nada",
    )
    parser.add_argument(
        "--forcar", action="store_true",
        help="Regera mesmo quem não teve precificação nova (ignora a assinatura)",
    )
    parser.add_argument(
        "--log", type=Path, default=None,
        help="Arquivo de log (padrão: <trabalho>/_logs/precificacao-YYYY-MM-DD.log)",
    )
    args = parser.parse_args()

    if args.fonte is None or args.trabalho is None:
        print(
            "ERRO: não foi possível descobrir as pastas padrão no OneDrive. "
            "Informe --fonte e --trabalho.",
            file=sys.stderr,
        )
        sys.exit(2)
    if args.rodadas is not None and args.rodadas < 1:
        print("ERRO: --rodadas deve ser >= 1.", file=sys.stderr)
        sys.exit(2)

    fonte = args.fonte.expanduser().resolve()
    trabalho = args.trabalho.expanduser().resolve()
    log_path = args.log
    if log_path is None and not args.conferir:
        log_path = trabalho / "_logs" / f"precificacao-{datetime.now():%Y-%m-%d}.log"
    elif log_path is not None:
        log_path = log_path.expanduser().resolve()

    try:
        _gerados, falhas, _inalterados, _sem_mapa = rodar_lote(
            fonte, trabalho,
            so=args.so, rodadas=args.rodadas, conferir=args.conferir,
            forcar=args.forcar, log_path=log_path,
        )
    except (ErroLote, pgp.ErroPrecificacaoPostgres) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        sys.exit(2)

    sys.exit(1 if falhas else 0)


if __name__ == "__main__":
    main()
