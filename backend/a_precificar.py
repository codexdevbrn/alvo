"""Tela Precificação: quais SKUs precisam de preço novo, com a prova de cada um.

Movimento: o do PRICE (`margem_price`), por SKU e dia, somando todas as lojas da
empresa — o mesmo da Pós-precificação. Duas janelas encostadas, terminando no
último dia do movimento (já limitado ao corte D-1):

- **recente**: os últimos 30 dias — "como está agora";
- **base**: os 90 dias antes dela — "como estava".

Um SKU entra na lista quando vende nas duas janelas, deixa lucro na mesa (a
margem recente está abaixo da referência) e tem ao menos uma prova:

| Prova | Regra |
|---|---|
| `margem` | margem recente pelo menos 2 pp abaixo da base |
| `custo` | custo unitário subiu, e subiu 2 pp a mais que o preço (sem repasse) |
| `volume` | quantidade por dia caiu 15% ou mais |
| `alvo` | margem recente mais de 1 pp abaixo do alvo vigente da precificação |

Referência = alvo vigente (último evento do SKU no dump de precificação); sem
alvo, a margem da base. "Lucro perdido por dia" é o que o SKU daria a mais com o
preço que leva a margem recente à referência, na mesma quantidade:
`qtd/dia × (custo ÷ (1 − ref) − preço)`. É a régua da ordem, junto com o peso da
curva e o número de provas — perder R$ 300/dia num item A com três provas vem
antes de perder o mesmo num item C com uma.

"Por dia" divide pelos dias em que a empresa vendeu na janela, como no resto do
Prisma: dividir por dia de calendário puniria a janela com mais domingo.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DIAS_RECENTE = 30
DIAS_BASE = 90
QUEDA_MARGEM_PP = 2.0
CUSTO_SEM_REPASSE_PP = 2.0
QUEDA_VOLUME_PCT = -15.0
ABAIXO_ALVO_PP = 1.0
# Menos que isso em qualquer janela e a variação é ruído de uma venda só.
QTD_MINIMA_JANELA = 3.0
CORTES_CURVA = (80.0, 95.0)
PESO_CURVA = {"A": 1.0, "B": 0.6, "C": 0.3}
PROVAS = ("margem", "custo", "volume", "alvo")
LIMITE_LINHAS = 500
SEMANAS_ITEM = 16


class ErroAPrecificar(RuntimeError):
    """Movimento sem o grão por SKU e dia."""


def _pct(novo: pd.Series, antigo: pd.Series) -> pd.Series:
    return (novo / antigo.where(antigo > 0) - 1) * 100


def _margem(receita: pd.Series, cmv: pd.Series) -> pd.Series:
    return (receita - cmv) / receita.where(receita > 0) * 100


def _num(valor: Any, casas: int = 2) -> float | None:
    if valor is None:
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return round(numero, casas) if np.isfinite(numero) else None


def preparar_movimento(bruto: pd.DataFrame, data_corte=None) -> pd.DataFrame:
    """Transações do PRICE → (codigo, dia, receita, cmv, qtd), com o corte D-1.

    Linha sem `segmento` (o balde "NÃO HARMONIZADO") fica fora, como na tela do
    PRICE e na Pós-precificação.
    """
    faltando = {"codigo_produto", "data", "receita", "cmv", "quantidade"} - set(bruto.columns)
    if faltando:
        raise ErroAPrecificar("O movimento do PRICE não tem código de produto por venda.")
    df = bruto
    if "segmento" in df.columns:
        df = df.loc[df["segmento"].notna()]
    mov = pd.DataFrame({
        "codigo": df["codigo_produto"].astype(str).str.strip(),
        "dia": pd.to_datetime(df["data"], errors="coerce").dt.normalize(),
        "receita": df["receita"].astype(float),
        "cmv": df["cmv"].astype(float),
        "qtd": df["quantidade"].astype(float),
        "fabricante": df.get("fabricante", pd.Series("", index=df.index)).fillna("").astype(str).str.strip(),
        "descricao": df.get("descricao", pd.Series("", index=df.index)).fillna("").astype(str).str.strip(),
    }).dropna(subset=["dia"])
    if data_corte is not None:
        mov = mov.loc[mov["dia"] <= pd.Timestamp(data_corte)]
    return mov.reset_index(drop=True)


def alvos_vigentes(dump: pd.DataFrame | None) -> pd.DataFrame:
    """Último alvo de cada SKU no dump: (codigo → alvo, dia_alvo)."""
    vazio = pd.DataFrame(columns=["alvo", "dia_alvo"])
    if dump is None or dump.empty or "codigo" not in dump.columns:
        return vazio
    df = dump.loc[dump["codigo"].fillna("").astype(str).str.strip() != ""].copy()
    df["codigo"] = df["codigo"].astype(str).str.strip()
    df["dia_alvo"] = pd.to_datetime(df["data_exportacao"], errors="coerce").dt.normalize()
    df["alvo"] = pd.to_numeric(df["margem_alvo"], errors="coerce")
    df = df.dropna(subset=["dia_alvo", "alvo"])
    if df.empty:
        return vazio
    df = df.sort_values("dia_alvo").drop_duplicates("codigo", keep="last")
    return df.set_index("codigo")[["alvo", "dia_alvo"]]


def _janelas(mov: pd.DataFrame) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    fim = mov["dia"].max()
    ini_recente = fim - pd.Timedelta(days=DIAS_RECENTE - 1)
    ini_base = ini_recente - pd.Timedelta(days=DIAS_BASE)
    return ini_base, ini_recente, fim


def _curva(receita: pd.Series) -> pd.Series:
    """A/B/C pela receita acumulada; o maior item é sempre A."""
    ordem = receita.sort_values(ascending=False)
    total = float(ordem.sum())
    if total <= 0:
        return pd.Series("C", index=receita.index)
    acumulado = ordem.cumsum() / total * 100
    curva = pd.Series(
        np.select([acumulado <= CORTES_CURVA[0], acumulado <= CORTES_CURVA[1]], ["A", "B"], "C"),
        index=ordem.index,
    )
    curva.iloc[0] = "A"
    return curva.reindex(receita.index)


def calcular_skus(mov: pd.DataFrame, alvos: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Uma linha por SKU com as duas janelas, provas e o lucro perdido por dia."""
    if mov.empty:
        return pd.DataFrame(), {}
    ini_base, ini_recente, fim = _janelas(mov)
    mov = mov.loc[mov["dia"] >= ini_base]
    recente = mov["dia"] >= ini_recente
    dias_base = int(mov.loc[~recente, "dia"].nunique())
    dias_recente = int(mov.loc[recente, "dia"].nunique())

    campos = ["receita", "cmv", "qtd"]
    base = mov.loc[~recente].groupby("codigo")[campos].sum().add_suffix("_b")
    rec = mov.loc[recente].groupby("codigo")[campos].sum().add_suffix("_r")
    # Nome e fabricante mais recentes: o catálogo do PRICE às vezes renomeia.
    nomes = mov.sort_values("dia").groupby("codigo")[["descricao", "fabricante"]].last()
    s = nomes.join(base, how="left").join(rec, how="left").fillna(
        {c: 0.0 for c in [*base.columns, *rec.columns]}
    )

    receita_total_b = float(s["receita_b"].sum())
    s["curva"] = _curva(s["receita_b"] + s["receita_r"])
    s["margem_b"] = _margem(s["receita_b"], s["cmv_b"])
    s["margem_r"] = _margem(s["receita_r"], s["cmv_r"])
    s["preco_b"] = s["receita_b"] / s["qtd_b"].where(s["qtd_b"] > 0)
    s["preco_r"] = s["receita_r"] / s["qtd_r"].where(s["qtd_r"] > 0)
    s["custo_b"] = s["cmv_b"] / s["qtd_b"].where(s["qtd_b"] > 0)
    s["custo_r"] = s["cmv_r"] / s["qtd_r"].where(s["qtd_r"] > 0)
    s["var_preco"] = _pct(s["preco_r"], s["preco_b"])
    s["var_custo"] = _pct(s["custo_r"], s["custo_b"])
    s["qtd_dia_b"] = s["qtd_b"] / max(dias_base, 1)
    s["qtd_dia_r"] = s["qtd_r"] / max(dias_recente, 1)
    s["var_qtd"] = _pct(s["qtd_dia_r"], s["qtd_dia_b"])

    s = s.join(alvos, how="left") if not alvos.empty else s.assign(alvo=np.nan, dia_alvo=pd.NaT)
    s["referencia"] = s["alvo"].where(s["alvo"].notna(), s["margem_b"])
    s["gap"] = s["margem_r"] - s["referencia"]

    ref = s["referencia"].clip(upper=95.0) / 100
    s["preco_sugerido"] = s["custo_r"] / (1 - ref)
    s["reajuste"] = _pct(s["preco_sugerido"], s["preco_r"])
    s["perdido_dia"] = (s["qtd_dia_r"] * (s["preco_sugerido"] - s["preco_r"])).clip(lower=0)

    s["p_margem"] = s["margem_r"] <= s["margem_b"] - QUEDA_MARGEM_PP
    s["p_custo"] = (s["var_custo"] > 0) & (s["var_custo"] - s["var_preco"] >= CUSTO_SEM_REPASSE_PP)
    s["p_volume"] = s["var_qtd"] <= QUEDA_VOLUME_PCT
    s["p_alvo"] = s["alvo"].notna() & (s["margem_r"] < s["alvo"] - ABAIXO_ALVO_PP)
    colunas_prova = [f"p_{p}" for p in PROVAS]
    s[colunas_prova] = s[colunas_prova].fillna(False)
    s["n_provas"] = s[colunas_prova].sum(axis=1).astype(int)

    vende = (s["qtd_b"] >= QTD_MINIMA_JANELA) & (s["qtd_r"] >= QTD_MINIMA_JANELA) & (s["receita_r"] > 0)
    s["a_precificar"] = vende & (s["n_provas"] > 0) & (s["perdido_dia"] > 0)
    s["score"] = s["perdido_dia"] * s["curva"].map(PESO_CURVA) * s["n_provas"]

    receita_fab = s.groupby("fabricante")["receita_b"].transform("sum")
    s["part_receita"] = s["receita_b"] / receita_total_b * 100 if receita_total_b > 0 else np.nan
    s["part_fabricante"] = s["receita_b"] / receita_fab.where(receita_fab > 0) * 100

    contexto = {
        "inicio_base": ini_base,
        "inicio_recente": ini_recente,
        "fim": fim,
        "dias_base": dias_base,
        "dias_recente": dias_recente,
        "receita_total_base": receita_total_b,
    }
    return s, contexto


def _linha(codigo: str, r: pd.Series) -> dict[str, Any]:
    return {
        "codigo": codigo,
        "descricao": r["descricao"],
        "fabricante": r["fabricante"] or "Não informado",
        "curva": r["curva"],
        "provas": [p for p in PROVAS if bool(r[f"p_{p}"])],
        "part_receita": _num(r["part_receita"], 3),
        "part_fabricante": _num(r["part_fabricante"], 2),
        "receita_base": _num(r["receita_b"]),
        "margem_base": _num(r["margem_b"]),
        "margem_recente": _num(r["margem_r"]),
        "alvo": _num(r["alvo"]),
        "dia_alvo": None if pd.isna(r["dia_alvo"]) else pd.Timestamp(r["dia_alvo"]).date().isoformat(),
        "referencia": _num(r["referencia"]),
        "gap": _num(r["gap"]),
        "var_custo": _num(r["var_custo"]),
        "var_preco": _num(r["var_preco"]),
        "var_qtd": _num(r["var_qtd"]),
        "qtd_dia_recente": _num(r["qtd_dia_r"], 3),
        "preco_atual": _num(r["preco_r"]),
        "custo_atual": _num(r["custo_r"]),
        "preco_sugerido": _num(r["preco_sugerido"]),
        "reajuste": _num(r["reajuste"]),
        "perdido_dia": _num(r["perdido_dia"]),
    }


def montar_a_precificar(skus: pd.DataFrame, contexto: dict[str, Any]) -> dict[str, Any]:
    """Resposta da tela: indicadores, fabricantes e a lista ordenada."""
    if skus.empty:
        return {
            "janela": None,
            "resumo": {"skus": 0, "curva_a": 0, "fabricantes": 0, "receita_em_jogo": 0.0,
                       "part_receita": None, "perdido_dia": 0.0, "custo_sem_repasse": 0,
                       "com_alvo": 0},
            "fabricantes": [],
            "itens": [],
            "total_itens": 0,
        }
    sel = skus.loc[skus["a_precificar"]].sort_values("score", ascending=False)
    total_b = contexto["receita_total_base"]

    fab = (
        sel.assign(fabricante=sel["fabricante"].replace("", "Não informado"))
        .groupby("fabricante")
        .agg(perdido_dia=("perdido_dia", "sum"), skus=("perdido_dia", "size"), receita=("receita_b", "sum"))
        .sort_values("perdido_dia", ascending=False)
    )
    fabricantes = [
        {
            "nome": nome,
            "perdido_dia": _num(r["perdido_dia"]),
            "skus": int(r["skus"]),
            "part_receita": _num(r["receita"] / total_b * 100, 2) if total_b > 0 else None,
        }
        for nome, r in fab.iterrows()
    ]

    receita_em_jogo = float(sel["receita_b"].sum())
    return {
        "janela": {
            "inicio_base": contexto["inicio_base"].date().isoformat(),
            "inicio_recente": contexto["inicio_recente"].date().isoformat(),
            "fim": contexto["fim"].date().isoformat(),
            "dias_base": contexto["dias_base"],
            "dias_recente": contexto["dias_recente"],
        },
        "resumo": {
            "skus": int(len(sel)),
            "curva_a": int((sel["curva"] == "A").sum()),
            "fabricantes": int(len(fab)),
            "receita_em_jogo": _num(receita_em_jogo),
            "part_receita": _num(receita_em_jogo / total_b * 100, 2) if total_b > 0 else None,
            "perdido_dia": _num(sel["perdido_dia"].sum()),
            "custo_sem_repasse": int(sel["p_custo"].sum()),
            "com_alvo": int(sel["alvo"].notna().sum()),
        },
        "fabricantes": fabricantes,
        # A lista é longa (milhares na IBAD); a tela mostra as primeiras e a
        # ordem já põe o que importa no topo.
        "itens": [_linha(codigo, r) for codigo, r in sel.head(LIMITE_LINHAS).iterrows()],
        "total_itens": int(len(sel)),
    }


def serie_semanal(mov: pd.DataFrame, codigo: str) -> list[dict[str, Any]]:
    """Preço e custo unitários por semana (segunda a domingo) do SKU."""
    df = mov.loc[mov["codigo"] == codigo]
    if df.empty:
        return []
    inicio = df["dia"].max() - pd.Timedelta(weeks=SEMANAS_ITEM)
    df = df.loc[df["dia"] > inicio]
    semana = df["dia"] - pd.to_timedelta(df["dia"].dt.weekday, unit="D")
    tot = df.groupby(semana)[["receita", "cmv", "qtd"]].sum()
    tot = tot.loc[tot["qtd"] > 0]
    return [
        {
            "semana": dia.date().isoformat(),
            "preco": _num(r["receita"] / r["qtd"]),
            "custo": _num(r["cmv"] / r["qtd"]),
            "qtd": _num(r["qtd"], 3),
        }
        for dia, r in tot.iterrows()
    ]
