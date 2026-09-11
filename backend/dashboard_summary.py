"""
Geração do "summary" do Dashboard (rota /) a partir de um DataFrame limpo.

Produz um dict com EXATAMENTE o mesmo shape do dashboard/public/data/summary.json
gerado por process_data.py na raiz do projeto (contrato consumido por
dashboard/src/types/dashboard.ts e DashboardPage.tsx):

    {
      "maps": {"s": [...], "c": [...], "m": [...], "d": [...], "r": [...], "p": [...]},
      "rows": [[p, s, c, m, d, r, rev, qty], ...],   # índices nos maps + valores
      "monthly": [{"name": "jan/24", "rev": ..., "cmv": ..., "pid": 202401, "year": 2024}, ...],
      "yoy": {"2024": ..., "2025": ...},
      "updated_at": "dd/mm/aaaa hh:mm",
      "kpis": {"rev": ..., "qty": ..., "avg": ..., "cnt": ..., "cmv": ...}
    }

`cmv` em `monthly`/`kpis` é o Custo da Mercadoria Vendida somado no período — base
para "Lucro bruto" (receita - CMV) na tela de Monitoramento. Empresa cuja fonte
não preenche a coluna chega com `cmv` zerado; `kpis.cmv == 0` sinaliza "sem CMV"
para quem consome o summary (`monitor_empresas.py` usa isso para esconder a
métrica de lucro dessa empresa, em vez de mostrar lucro == receita).

A diferença em relação a process_data.py é a origem dos dados: aqui o
DataFrame vem de engine.analise_funil.carregar_csv() (Base.csv por empresa,
schema canônico do Analisador), que já entrega Receita como float, QTD como
int e Data_Venda como datetime — então a lógica foi adaptada para essas
colunas e vetorizada (o iterrows do script original seria lento com 647k
linhas por requisição).

Cache em disco: `summary_dashboard.json` na pasta de trabalho da empresa,
invalidado quando Base.csv fica mais novo (mtime).
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
from datetime import date
from pathlib import Path

import pandas as pd

from engine.analise_funil import MESES_ABREV

MESES_NOME = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril", 5: "maio", 6: "junho",
    7: "julho", 8: "agosto", 9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}

NOME_SUMMARY_DASHBOARD = "summary_dashboard.json"
NOME_SUMMARY_DASHBOARD_GZ = "summary_dashboard.json.gz"


def caminho_summary_dashboard(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_SUMMARY_DASHBOARD


def caminho_summary_dashboard_gz(pasta_trabalho: str | Path) -> Path:
    return Path(pasta_trabalho) / NOME_SUMMARY_DASHBOARD_GZ


def summary_dashboard_atualizado(
    pasta_trabalho: str | Path,
    caminho_base_csv: str | Path,
    *,
    mtime_minimo: float = 0.0,
) -> bool:
    """True se o JSON (ou .gz) em disco existe e não é mais antigo que a fonte.

    `mtime_minimo` acrescenta outras entradas que também invalidam o summary
    quando mudam sem a fonte mudar — hoje, a regra de harmonização de clientes.
    """
    caminho_csv = Path(caminho_base_csv)
    if not caminho_csv.is_file():
        return False
    mtime_fonte = max(os.path.getmtime(caminho_csv), mtime_minimo)
    for caminho in (
        caminho_summary_dashboard_gz(pasta_trabalho),
        caminho_summary_dashboard(pasta_trabalho),
    ):
        if caminho.is_file() and os.path.getmtime(caminho) >= mtime_fonte:
            return True
    return False


def gravar_summary_dashboard(pasta_trabalho: str | Path, summary: dict) -> Path:
    """Grava summary_dashboard.json e .json.gz (atômico) na pasta de trabalho.

    Retorna o caminho do .json.gz (preferido para FileResponse).
    """
    pasta = Path(pasta_trabalho)
    pasta.mkdir(parents=True, exist_ok=True)
    destino = caminho_summary_dashboard(pasta)
    destino_gz = caminho_summary_dashboard_gz(pasta)
    payload = json.dumps(summary, ensure_ascii=False, separators=(",", ":")).encode("utf-8")

    fd, tmp_nome = tempfile.mkstemp(
        prefix="summary_dashboard_",
        suffix=".json.tmp",
        dir=str(pasta),
    )
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(payload)
        os.replace(tmp_nome, destino)
    except Exception:
        try:
            os.unlink(tmp_nome)
        except OSError:
            pass
        raise

    fd_gz, tmp_gz = tempfile.mkstemp(
        prefix="summary_dashboard_",
        suffix=".json.gz.tmp",
        dir=str(pasta),
    )
    try:
        os.close(fd_gz)
        with gzip.open(tmp_gz, "wb", compresslevel=4) as f:
            f.write(payload)
        os.replace(tmp_gz, destino_gz)
    except Exception:
        try:
            os.unlink(tmp_gz)
        except OSError:
            pass
        raise

    return destino_gz


def invalidar_summary_dashboard(pasta_trabalho: str | Path) -> None:
    for caminho in (
        caminho_summary_dashboard(pasta_trabalho),
        caminho_summary_dashboard_gz(pasta_trabalho),
    ):
        try:
            caminho.unlink(missing_ok=True)
        except OSError:
            pass


def gerar_e_gravar_summary_dashboard(
    pasta_trabalho: str | Path,
    df: pd.DataFrame,
    *,
    data_ultimo_movimento: date | None = None,
    updated_at: str | None = None,
) -> Path:
    """Gera o summary a partir do DataFrame e grava summary_dashboard.json(+.gz)."""
    summary = gerar_summary(
        df,
        updated_at=updated_at,
        data_ultimo_movimento=data_ultimo_movimento,
    )
    return gravar_summary_dashboard(pasta_trabalho, summary)


def formatar_ultimo_movimento(
    df: pd.DataFrame,
    data_exata: date | None = None,
) -> str:
    """Rótulo do último movimento — data exata (BI) ou mês/ano (fallback da Base.csv)."""
    if data_exata is not None:
        return data_exata.strftime("%d/%m/%Y")
    ultimo = df["Data_Venda"].max()
    if pd.isna(ultimo):
        return "—"
    return f"{MESES_NOME[int(ultimo.month)]}/{int(ultimo.year)}"


def gerar_summary(
    df: pd.DataFrame,
    updated_at: str | None = None,
    data_ultimo_movimento: date | None = None,
) -> dict:
    """Gera o dict do summary do dashboard a partir do DataFrame limpo do motor.

    `df` deve ser a saída de analise_funil.carregar_csv()/carregar_excel_base()
    (colunas Loja, Cliente, NOME_FABRICANTE, descricao, Código de referêcia,
    Receita, QTD, Data_Venda).
    """
    colunas_base: dict = {
            "store": df["Loja"].astype(str),
            "client": df["Cliente"].astype(str),
            "mfr": df["NOME_FABRICANTE"].astype(str),
            "desc": df["descricao"].astype(str),
            # carregar_csv preenche referência vazia com "" — o dashboard
            # estático usa o rótulo "S/ REF" (ver process_data.py).
            "ref": df["Código de referêcia"].astype(str).replace("", "S/ REF"),
            "year": df["Data_Venda"].dt.year,
            "m_num": df["Data_Venda"].dt.month,
            "rev": df["Receita"].astype(float),
            "qty": df["QTD"].astype(int),
            "cmv": df["CMV"].astype(float).fillna(0.0) if "CMV" in df.columns else 0.0,
    }

    # Data diária real (quando a fonte tem coluna de dia) — usada para contar
    # quantos dias distintos tiveram venda em cada período. Permite calcular
    # média diária dividindo pela realidade da base em vez dos dias úteis do
    # calendário (que superestima quando a empresa não vende todo dia útil).
    tem_data_diaria = "Data_Venda_Diaria" in df.columns and df["Data_Venda_Diaria"].notna().any()
    if tem_data_diaria:
        colunas_base["data_diaria"] = pd.to_datetime(df["Data_Venda_Diaria"], errors="coerce")

    base = pd.DataFrame(colunas_base)
    base["p_p_id"] = base["year"] * 100 + base["m_num"]

    # Dias distintos com venda por período — só quando a fonte informa o dia.
    dias_com_venda_por_periodo: dict[int, int] = {}
    if tem_data_diaria:
        _datas_validas = base.dropna(subset=["data_diaria"])
        if len(_datas_validas):
            dias_com_venda_por_periodo = (
                _datas_validas.groupby("p_p_id")["data_diaria"]
                .apply(lambda s: s.dt.date.nunique())
                .to_dict()
            )

    agg = (
        base.groupby(["p_p_id", "store", "client", "mfr", "desc", "ref"], sort=False)
        .agg(rev=("rev", "sum"), qty=("qty", "sum"))
        .reset_index()
    )

    # Dimensões ordenadas por receita decrescente (mesma UX do summary estático)
    def _mapa_ordenado(coluna: str) -> list:
        return base.groupby(coluna)["rev"].sum().sort_values(ascending=False).index.tolist()

    maps = {
        "s": _mapa_ordenado("store"),
        "c": _mapa_ordenado("client"),
        "m": _mapa_ordenado("mfr"),
        "d": _mapa_ordenado("desc"),
        "r": _mapa_ordenado("ref"),
        "p": sorted(int(p) for p in base["p_p_id"].unique()),
    }
    indices = {chave: {valor: i for i, valor in enumerate(valores)} for chave, valores in maps.items()}

    rows = [
        [p, s, c, m, d, r, round(float(rev), 2), int(qty)]
        for p, s, c, m, d, r, rev, qty in zip(
            agg["p_p_id"].map(indices["p"]),
            agg["store"].map(indices["s"]),
            agg["client"].map(indices["c"]),
            agg["mfr"].map(indices["m"]),
            agg["desc"].map(indices["d"]),
            agg["ref"].map(indices["r"]),
            agg["rev"],
            agg["qty"],
        )
    ]

    mensal = (
        base.groupby(["p_p_id", "year", "m_num"])[["rev", "cmv"]]
        .sum()
        .reset_index()
        .sort_values("p_p_id")
    )
    monthly = []
    for linha in mensal.itertuples():
        entrada: dict = {
            "name": f"{MESES_ABREV[int(linha.m_num)]}/{str(int(linha.year))[2:]}",
            "rev": round(float(linha.rev), 2),
            "cmv": round(float(linha.cmv), 2),
            "pid": int(linha.p_p_id),
            "year": int(linha.year),
        }
        dias = dias_com_venda_por_periodo.get(int(linha.p_p_id))
        if dias is not None:
            entrada["dias_com_venda"] = int(dias)
        monthly.append(entrada)

    yoy = {str(int(ano)): round(float(total), 2) for ano, total in base.groupby("year")["rev"].sum().items()}

    return {
        "maps": maps,
        "rows": rows,
        "monthly": monthly,
        "yoy": yoy,
        # "Atualizado" no dashboard = último movimento da base, não o mtime do arquivo.
        "updated_at": (
            updated_at
            if updated_at is not None
            else formatar_ultimo_movimento(df, data_ultimo_movimento)
        ),
        "kpis": {
            "rev": round(float(base["rev"].sum()), 2),
            "qty": int(base["qty"].sum()),
            "avg": round(float(base["rev"].mean()), 2) if len(base) else 0.0,
            "cnt": int(len(base)),
            "cmv": round(float(base["cmv"].sum()), 2),
        },
    }
