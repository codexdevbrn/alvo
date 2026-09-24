"""Leitura do Postgres de precificação — substitui o `{empresa}_PRECIFICACAO.csv`
exportado à mão.

Somente leitura, imposto em três camadas: a sessão sobe com
`default_transaction_read_only=on`, `set_session(readonly=True)` marca a conexão
do lado do cliente, e `_exigir_sessao_somente_leitura` confirma no próprio
servidor antes de qualquer consulta. Só o lote usa este módulo — o app
empacotado não importa nada daqui, então a credencial não viaja no exe.

`empresas.certificado_senha` é senha de certificado digital: nenhuma consulta
aqui seleciona coluna `certificado_*`.

**Rodada é o dia, não o timestamp.** `data_exportacao` é gravado linha a linha
com precisão de microssegundo (3804 linhas de uma exportação = 3804 timestamps
distintos), então agrupar por igualdade de timestamp devolveria uma linha por
"rodada". O tamanho varia de 3 a ~15 mil linhas entre rodadas da mesma empresa,
e é por isso que o consumidor escolhe a rodada em vez de assumir a mais recente.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd

#: Colunas de `historico_precificacao` que o dump reproduz, na ordem do arquivo.
#: Espelho da tabela menos o `id` (chave técnica, sem uso no Prisma).
#: `cnpj`/`descricao`/`fabricante` são as chaves que `carregar_csv_precificacao`
#: exige; `codigo` e `fx` não são lidos hoje, mas descartá-los tornaria o arquivo
#: uma versão curada do dump em vez de um espelho, e recuperá-los depois custaria
#: outro lote.
COLUNAS_DUMP = (
    "cnpj", "descricao", "codigo", "fabricante",
    "margem_anterior", "margem_alvo", "receita", "cmv", "fx",
    "data_exportacao", "markup_alvo", "preco_atual", "preco_sugerido", "variacao_pct",
)

#: Texto para não perder zero à esquerda do CNPJ nem virar float no `codigo`.
COLUNAS_TEXTO = ("cnpj", "descricao", "codigo", "fabricante", "fx")

_TIMEOUT_CONEXAO = 15
_TIMEOUT_CONSULTA_MS = 120_000


class ErroPrecificacaoPostgres(RuntimeError):
    """Falha de configuração, conexão ou contrato do banco de precificação."""


@dataclass(frozen=True)
class Conexao:
    host: str
    porta: str
    usuario: str
    senha: str
    banco: str

    @property
    def destino(self) -> str:
        """Identificação sem segredo, para log."""
        return f"{self.host}:{self.porta}/{self.banco}"


def _carregar_dotenv(raiz: Path | None = None) -> None:
    """Carrega o `.env` da raiz do repositório, se houver.

    `python-dotenv` é dependência só do lote; sem ele, as variáveis precisam já
    estar no ambiente. Não sobrescreve variável existente — ambiente explícito
    vence arquivo.
    """
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    caminho = (raiz or Path(__file__).resolve().parents[1]) / ".env"
    if caminho.is_file():
        load_dotenv(caminho, override=False)


def config_do_ambiente(raiz: Path | None = None) -> Conexao:
    """Lê PG_* do ambiente (com `.env` como reserva)."""
    _carregar_dotenv(raiz)
    faltando = [
        chave for chave in ("PG_HOST", "PG_USER", "PG_PASSWORD", "PG_DATABASE")
        if not (os.environ.get(chave) or "").strip()
    ]
    if faltando:
        raise ErroPrecificacaoPostgres(
            "Variáveis de conexão ausentes: " + ", ".join(faltando)
            + ". Defina no ambiente ou no .env da raiz (ver .env.example)."
        )
    return Conexao(
        host=os.environ["PG_HOST"].strip(),
        porta=(os.environ.get("PG_PORT") or "5432").strip(),
        usuario=os.environ["PG_USER"].strip(),
        senha=os.environ["PG_PASSWORD"],
        banco=os.environ["PG_DATABASE"].strip(),
    )


def _exigir_sessao_somente_leitura(conn) -> None:
    with conn.cursor() as cur:
        cur.execute("show transaction_read_only")
        if (cur.fetchone() or [""])[0] != "on":
            raise ErroPrecificacaoPostgres(
                "A sessão não subiu somente-leitura; abortando antes de consultar."
            )


def conectar(config: Conexao | None = None):
    """Conexão somente-leitura. Quem chama fecha."""
    try:
        import psycopg2
    except ImportError as exc:
        raise ErroPrecificacaoPostgres(
            "psycopg2 não instalado; rode pip install -r backend/requirements.txt"
        ) from exc

    cfg = config or config_do_ambiente()
    try:
        conn = psycopg2.connect(
            host=cfg.host, port=cfg.porta, user=cfg.usuario, password=cfg.senha,
            dbname=cfg.banco, connect_timeout=_TIMEOUT_CONEXAO,
            options=(
                f"-c default_transaction_read_only=on "
                f"-c statement_timeout={_TIMEOUT_CONSULTA_MS}"
            ),
        )
    except Exception as exc:
        # A mensagem do driver repete host e usuário; o destino já vai no log sem
        # segredo, e a senha nunca aparece nela.
        raise ErroPrecificacaoPostgres(
            f"Não foi possível conectar em {cfg.destino}: {type(exc).__name__}"
        ) from exc
    conn.set_session(readonly=True, autocommit=True)
    _exigir_sessao_somente_leitura(conn)
    return conn


def _normalizar_cnpjs(cnpjs: Iterable[str]) -> list[str]:
    """Só dígitos, sem vazio, sem repetido, ordem estável.

    As duas tabelas guardam 14 dígitos sem pontuação (verificado), mas o mapa é
    preenchido à mão — normalizar aqui evita que um CNPJ com máscara no mapa
    devolva zero linha em silêncio.
    """
    vistos: dict[str, None] = {}
    for bruto in cnpjs:
        digitos = "".join(c for c in str(bruto) if c.isdigit())
        if digitos:
            vistos.setdefault(digitos, None)
    return list(vistos)


def listar_rodadas(conn, cnpjs: Sequence[str]) -> list[dict]:
    """Rodadas disponíveis (uma por dia), da mais recente para a mais antiga."""
    alvo = _normalizar_cnpjs(cnpjs)
    if not alvo:
        return []
    with conn.cursor() as cur:
        cur.execute(
            """
            select data_exportacao::date as dia,
                   count(*) as linhas,
                   count(distinct (lower(btrim(descricao)), lower(btrim(fabricante)))) as pares
              from historico_precificacao
             where cnpj = any(%s)
             group by 1
             order by 1 desc
            """,
            (alvo,),
        )
        return [
            {"dia": dia.isoformat(), "linhas": int(linhas), "pares": int(pares)}
            for dia, linhas, pares in cur.fetchall()
        ]


def _limite_rodadas(rodadas: int | None) -> int:
    """`None` = todas as rodadas; o SQL recebe um teto que nenhuma empresa alcança."""
    if rodadas is None:
        return 2_147_483_647
    if rodadas < 1:
        raise ValueError("rodadas deve ser >= 1")
    return rodadas


def assinaturas_por_cnpj(
    conn, cnpjs: Sequence[str], rodadas: int | None = None,
) -> dict[str, list[dict]]:
    """Por CNPJ, as `rodadas` mais recentes (todas, se `None`) com contagem e
    extremos do timestamp.

    Uma consulta agregada para todos os CNPJs de uma vez: é com isso que o lote
    decide quem regerar, sem transferir as ~237 mil linhas do recorte completo.
    Os extremos entram junto da contagem porque rodada acrescentada com data
    antiga (correção retroativa) não move o timestamp mais recente.
    """
    limite = _limite_rodadas(rodadas)
    alvo = _normalizar_cnpjs(cnpjs)
    if not alvo:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            with ranqueado as (
              select cnpj, data_exportacao, data_exportacao::date as dia,
                     dense_rank() over (
                       partition by cnpj order by data_exportacao::date desc
                     ) as r
                from historico_precificacao
               where cnpj = any(%s)
            )
            select cnpj, dia, count(*), max(data_exportacao), min(data_exportacao)
              from ranqueado
             where r <= %s
             group by cnpj, dia
             order by cnpj, dia desc
            """,
            (alvo, limite),
        )
        saida: dict[str, list[dict]] = {}
        for cnpj, dia, linhas, ultima, primeira in cur.fetchall():
            saida.setdefault(cnpj, []).append({
                "dia": dia.isoformat(),
                "linhas": int(linhas),
                "ultima": pd.Timestamp(ultima).isoformat(),
                "primeira": pd.Timestamp(primeira).isoformat(),
            })
    return saida


def dobrar_assinatura(por_cnpj: dict[str, list[dict]], cnpjs: Sequence[str]) -> dict | None:
    """Junta as assinaturas dos CNPJs de uma pasta numa só.

    A pasta pode ter matriz e filial, e o recorte de rodadas é por CNPJ
    (`partition by cnpj`), então os dias das duas entram na mesma sacola — é
    exatamente o conjunto que `carregar_ultimas_rodadas` devolveria.
    """
    partes = [p for cnpj in _normalizar_cnpjs(cnpjs) for p in por_cnpj.get(cnpj, ())]
    if not partes:
        return None
    return {
        "linhas": sum(p["linhas"] for p in partes),
        "dias": sorted({p["dia"] for p in partes}),
        "ultima": max(p["ultima"] for p in partes),
        "primeira": min(p["primeira"] for p in partes),
    }


def carregar_ultimas_rodadas(conn, cnpjs: Sequence[str], rodadas: int | None = None) -> pd.DataFrame:
    """Linhas cruas das `rodadas` datas mais recentes desses CNPJs (todas, se `None`).

    O recorte é por empresa (`partition by cnpj`): matriz e filial podem ter
    rodado em dias diferentes, e cortar por data global deixaria a filial de fora.
    """
    limite = _limite_rodadas(rodadas)
    alvo = _normalizar_cnpjs(cnpjs)
    if not alvo:
        return pd.DataFrame(columns=list(COLUNAS_DUMP))

    colunas_prefixadas = ", ".join(f"hp.{c}" for c in COLUNAS_DUMP)
    colunas = ", ".join(COLUNAS_DUMP)
    sql = f"""
        with ranqueado as (
          select {colunas_prefixadas},
                 dense_rank() over (
                   partition by hp.cnpj order by hp.data_exportacao::date desc
                 ) as _r
            from historico_precificacao hp
           where hp.cnpj = any(%s)
        )
        select {colunas}
          from ranqueado
         where _r <= %s
         order by data_exportacao
    """
    with conn.cursor() as cur:
        cur.execute(sql, (alvo, limite))
        linhas = cur.fetchall()

    df = pd.DataFrame(linhas, columns=list(COLUNAS_DUMP))
    for coluna in COLUNAS_TEXTO:
        df[coluna] = df[coluna].astype("string").fillna("").str.strip()
    df["data_exportacao"] = pd.to_datetime(df["data_exportacao"], errors="coerce")
    return df


def nomes_por_cnpj(conn, cnpjs: Sequence[str]) -> dict[str, str]:
    """CNPJ -> nome da empresa, só para log e para conferir o mapa.

    Não seleciona coluna `certificado_*`. Nome é informativo: 26 dos 43 CNPJs do
    histórico não existem em `empresas`, então isto pode voltar vazio.
    """
    alvo = _normalizar_cnpjs(cnpjs)
    if not alvo:
        return {}
    with conn.cursor() as cur:
        cur.execute(
            """
            select cnpj, coalesce(nullif(btrim(nome_fantasia), ''), btrim(razao_social), '')
              from empresas
             where cnpj = any(%s)
            """,
            (alvo,),
        )
        return {cnpj: nome for cnpj, nome in cur.fetchall() if nome}
