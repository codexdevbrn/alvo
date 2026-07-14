"""
Geração do "summary" do Dashboard (rota /) a partir de um DataFrame limpo.

Produz um dict com EXATAMENTE o mesmo shape do dashboard/public/data/summary.json
gerado por process_data.py na raiz do projeto (contrato consumido por
dashboard/src/types/dashboard.ts e DashboardPage.tsx):

    {
      "maps": {"s": [...], "c": [...], "m": [...], "d": [...], "r": [...], "p": [...]},
      "rows": [[p, s, c, m, d, r, rev, qty], ...],   # índices nos maps + valores
      "monthly": [{"name": "jan/24", "rev": ..., "pid": 202401, "year": 2024}, ...],
      "yoy": {"2024": ..., "2025": ...},
      "updated_at": "dd/mm/aaaa hh:mm",
      "kpis": {"rev": ..., "qty": ..., "avg": ..., "cnt": ...}
    }

A diferença em relação a process_data.py é a origem dos dados: aqui o
DataFrame vem de engine.analise_funil.carregar_csv() (Base.csv por empresa,
schema canônico do Analisador), que já entrega Receita como float, QTD como
int e Data_Venda como datetime — então a lógica foi adaptada para essas
colunas e vetorizada (o iterrows do script original seria lento com 647k
linhas por requisição).
"""

import datetime

import pandas as pd

from engine.analise_funil import MESES_ABREV


def gerar_summary(df: pd.DataFrame, updated_at: str) -> dict:
    """Gera o dict do summary do dashboard a partir do DataFrame limpo do motor.

    `df` deve ser a saída de analise_funil.carregar_csv()/carregar_excel_base()
    (colunas Loja, Cliente, NOME_FABRICANTE, descricao, Código de referêcia,
    Receita, QTD, Data_Venda).
    """
    base = pd.DataFrame(
        {
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
        }
    )
    base["p_p_id"] = base["year"] * 100 + base["m_num"]

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
        base.groupby(["p_p_id", "year", "m_num"])["rev"].sum().reset_index().sort_values("p_p_id")
    )
    monthly = [
        {
            "name": f"{MESES_ABREV[int(linha.m_num)]}/{str(int(linha.year))[2:]}",
            "rev": round(float(linha.rev), 2),
            "pid": int(linha.p_p_id),
            "year": int(linha.year),
        }
        for linha in mensal.itertuples()
    ]

    yoy = {str(int(ano)): round(float(total), 2) for ano, total in base.groupby("year")["rev"].sum().items()}

    return {
        "maps": maps,
        "rows": rows,
        "monthly": monthly,
        "yoy": yoy,
        "updated_at": updated_at,
        "kpis": {
            "rev": round(float(base["rev"].sum()), 2),
            "qty": int(base["qty"].sum()),
            "avg": round(float(base["rev"].mean()), 2) if len(base) else 0.0,
            "cnt": int(len(base)),
        },
    }


def formatar_data_arquivo(mtime: float) -> str:
    return datetime.datetime.fromtimestamp(mtime).strftime("%d/%m/%Y %H:%M")
