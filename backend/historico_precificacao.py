"""Histórico de precificações por SKU — aba "Pós-precificação" da tela Precificação.

Ao contrário de `precificacao.py` (uma rodada por vez, grão família × fabricante),
aqui cada linha do dump vira um *evento*: SKU (`codigo`), dia, alvo, margem no dia
e faixa (`fx`). A leitura é de um período, não de uma rodada.

Efeito de um evento: 30 dias antes × até 30 dias depois, cortando o "depois" na
próxima precificação do mesmo SKU — senão o efeito de uma rodada contaminaria o
da seguinte. Como as janelas cortadas têm comprimentos diferentes, a comparação é
por dia de calendário da janela.

Estado *vigente* de um SKU = o evento mais recente dele dentro do filtro: é o alvo
que vale agora e a janela que diz como ele andou desde então. Tabela e indicadores
leem o vigente; a aba de rodadas lê todos os eventos de cada dia.

Movimento: o do PRICE (`margem_price`), que traz `codigo_produto` igual ao
`codigo` do dump. O CSV por empresa não tem esse código — por isso não há fallback.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from periodo_mensal import inicio_mes
from precificacao import (
    _meses_entre,
    _pontos_serie,
    _recortar_meses_com_dado,
    _totais_mensais,
)

JANELA_DIAS = 30
PERIODOS_DIAS = (90, 180, 365)
NIVEIS = ("familia", "fabricante", "par", "sku")
# Na visão por SKU são ~12 mil linhas; a tela lista as maiores e a busca filtra
# no servidor.
LIMITE_LINHAS = 500
LIMITE_SKUS_ITEM = 10
FAIXA_NO_ALVO_PP = 1.0


class ErroHistoricoPrecificacao(RuntimeError):
    """Dump sem código de produto ou movimento sem código — não dá pra casar por SKU."""


# ---------------------------------------------------------------------------
# Preparação (independe de filtro — é o que se cacheia por empresa)
# ---------------------------------------------------------------------------

def preparar_eventos(dump: pd.DataFrame) -> pd.DataFrame:
    """Um evento por (dia, SKU), com o próximo dia em que o mesmo SKU foi precificado."""
    if dump is None or dump.empty or "codigo" not in dump.columns:
        raise ErroHistoricoPrecificacao(
            "O dump de precificação não tem código de produto. Gere pelo Postgres "
            "(precificacao_do_postgres.py) para ver o histórico por SKU."
        )
    df = dump.loc[dump["codigo"].astype(str).str.strip() != ""].copy()
    if df.empty:
        raise ErroHistoricoPrecificacao("O dump de precificação não tem código de produto preenchido.")
    df["codigo"] = df["codigo"].astype(str).str.strip()
    df["ts"] = pd.to_datetime(df["data_exportacao"], errors="coerce")
    df = df.dropna(subset=["ts"])
    df["dia"] = df["ts"].dt.normalize()
    # O banco grava o mesmo SKU mais de uma vez no mesmo dia (106 casos na IBAD);
    # vale a última gravação.
    df = df.sort_values("ts").drop_duplicates(["dia", "codigo"], keep="last")
    fx = df["fx"] if "fx" in df.columns else pd.Series("", index=df.index)
    df["fx"] = fx.fillna("").astype(str).str.strip().str.upper()
    df["faixa"] = df["fx"].str[:1]
    df = df.sort_values(["codigo", "dia"])
    df["proximo"] = df.groupby("codigo")["dia"].shift(-1)
    df = df.rename(columns={"receita": "receita_dump"})
    colunas = [
        "codigo", "descricao", "fabricante", "fx", "faixa", "dia", "proximo",
        "margem_anterior", "margem_alvo", "receita_dump",
    ]
    return df[colunas].reset_index(drop=True)


def preparar_diario(movimento: pd.DataFrame) -> pd.DataFrame:
    """Receita/CMV/qtd por (SKU, dia) — o grão das janelas de efeito."""
    faltando = {"codigo_produto", "Data_Venda_Diaria", "Receita", "CMV", "QTD"} - set(movimento.columns)
    if faltando:
        raise ErroHistoricoPrecificacao(
            "O movimento não tem código de produto por venda; o histórico por SKU "
            "precisa do parquet do PRICE (margem_price)."
        )
    base = pd.DataFrame({
        "codigo": movimento["codigo_produto"].astype(str).str.strip(),
        "dia": pd.to_datetime(movimento["Data_Venda_Diaria"], errors="coerce").dt.normalize(),
        "receita": movimento["Receita"].astype(float),
        "cmv": movimento["CMV"].astype(float),
        "qtd": movimento["QTD"].astype(float),
    }).dropna(subset=["dia"])
    return base.groupby(["codigo", "dia"], sort=False, as_index=False)[["receita", "cmv", "qtd"]].sum()


def calcular_efeitos(eventos: pd.DataFrame, diario: pd.DataFrame) -> pd.DataFrame:
    """Soma antes/depois de cada evento num merge só, sem laço por evento.

    O "por dia" divide pelos dias em que a *loja* vendeu dentro da janela (mesma
    régua de "dias com venda" do resto do Prisma) — dividir por dia de calendário
    punia a janela que caía com mais domingo e feriado."""
    e = eventos.copy()
    janela = pd.Timedelta(days=JANELA_DIAS)
    if diario.empty:
        for coluna in ("ini_a", "fim_a", "ini_d", "fim_d"):
            e[coluna] = e["dia"]
        dias_loja = np.array([], dtype="datetime64[ns]")
    else:
        inicio = diario["dia"].min()
        fim = diario["dia"].max() + pd.Timedelta(days=1)  # exclusivo
        e["ini_a"] = (e["dia"] - janela).clip(lower=inicio)
        e["fim_a"] = e["dia"].clip(lower=inicio)
        e["ini_d"] = e["dia"]
        teto = (e["dia"] + janela).clip(upper=fim)
        e["fim_d"] = e["proximo"].where(e["proximo"].notna() & (e["proximo"] < teto), teto)
        ativo = (diario["receita"] != 0) | (diario["qtd"] != 0)
        dias_loja = np.sort(diario.loc[ativo, "dia"].unique().astype("datetime64[ns]"))

    def contar(ini: str, fim_col: str) -> np.ndarray:
        a = e[ini].to_numpy().astype("datetime64[ns]")
        b = e[fim_col].to_numpy().astype("datetime64[ns]")
        return np.clip(np.searchsorted(dias_loja, b) - np.searchsorted(dias_loja, a), 0, None)

    e["dias_a"] = contar("ini_a", "fim_a")
    e["dias_d"] = contar("ini_d", "fim_d")

    e = e.reset_index(drop=True)
    e["ev"] = e.index
    somas = ["receita", "cmv", "qtd"]
    for lado in ("a", "d"):
        for coluna in somas:
            e[f"{coluna}_{lado}"] = 0.0
    if not diario.empty:
        d = diario.loc[diario["codigo"].isin(set(e["codigo"]))]
        d = d.loc[(d["dia"] >= e["ini_a"].min()) & (d["dia"] < e["fim_d"].max())]
        m = e[["ev", "codigo", "ini_a", "fim_a", "ini_d", "fim_d"]].merge(d, on="codigo")
        for lado, ini, fim_col in (("a", "ini_a", "fim_a"), ("d", "ini_d", "fim_d")):
            dentro = m.loc[(m["dia"] >= m[ini]) & (m["dia"] < m[fim_col])]
            ag = dentro.groupby("ev")[somas].sum()
            for coluna in somas:
                e.loc[ag.index, f"{coluna}_{lado}"] = ag[coluna].to_numpy()
    e["mensuravel"] = (e["dias_a"] > 0) & (e["dias_d"] > 0)
    # Por evento: somar isso num grupo dá o "por dia" do grupo inteiro.
    for lado in ("a", "d"):
        dias = e[f"dias_{lado}"].where(e[f"dias_{lado}"] > 0)
        e[f"ld_{lado}"] = ((e[f"receita_{lado}"] - e[f"cmv_{lado}"]) / dias).fillna(0.0)
        e[f"qd_{lado}"] = (e[f"qtd_{lado}"] / dias).fillna(0.0)
    return e.drop(columns=["ev"])


def preparar_serie(movimento: pd.DataFrame) -> pd.DataFrame:
    """Movimento no formato de `precificacao._totais_mensais`, com o SKU."""
    return pd.DataFrame({
        "codigo": movimento["codigo_produto"].astype(str).str.strip(),
        "_data": pd.to_datetime(movimento["Data_Venda_Diaria"], errors="coerce"),
        "Receita": movimento["Receita"].astype(float),
        "CMV": movimento["CMV"].astype(float),
        "QTD": movimento["QTD"].astype(float),
    })


# ---------------------------------------------------------------------------
# Agregação
# ---------------------------------------------------------------------------

def _chave(df: pd.DataFrame, nivel: str) -> pd.Series:
    if nivel == "familia":
        return df["descricao"].astype(str)
    if nivel == "fabricante":
        return df["fabricante"].astype(str)
    if nivel == "par":
        return df["descricao"].astype(str) + " · " + df["fabricante"].astype(str)
    return df["codigo"].astype(str)


def _agrupar(df: pd.DataFrame, chave: pd.Series) -> pd.DataFrame:
    """Somas por grupo, incluindo as bases das médias ponderadas pela receita do dump."""
    peso = df["receita_dump"].fillna(0.0).clip(lower=0)
    tem_alvo = df["margem_alvo"].notna()
    tem_ant = df["margem_anterior"].notna()
    base = df.assign(
        _p_alvo=peso.where(tem_alvo, 0.0),
        _alvo_x=(df["margem_alvo"].fillna(0.0) * peso).where(tem_alvo, 0.0),
        _p_ant=peso.where(tem_ant, 0.0),
        _ant_x=(df["margem_anterior"].fillna(0.0) * peso).where(tem_ant, 0.0),
        _ld_a=df["ld_a"].where(df["mensuravel"], 0.0),
        _ld_d=df["ld_d"].where(df["mensuravel"], 0.0),
        _qd_a=df["qd_a"].where(df["mensuravel"], 0.0),
        _qd_d=df["qd_d"].where(df["mensuravel"], 0.0),
    )
    colunas = [
        "receita_a", "cmv_a", "qtd_a", "receita_d", "cmv_d", "qtd_d",
        "_p_alvo", "_alvo_x", "_p_ant", "_ant_x", "_ld_a", "_ld_d", "_qd_a", "_qd_d",
    ]
    return base.groupby(chave, sort=False)[colunas].sum()


def _tabela(s: pd.DataFrame) -> pd.DataFrame:
    """Das somas por grupo para as colunas da tela — vetorizado (a visão por SKU
    tem ~15 mil grupos)."""
    alvo = (s["_alvo_x"] / s["_p_alvo"]).where(s["_p_alvo"] > 0)
    no_dia = (s["_ant_x"] / s["_p_ant"]).where(s["_p_ant"] > 0)
    m_a = ((s["receita_a"] - s["cmv_a"]) / s["receita_a"] * 100).where(s["receita_a"] > 0)
    m_d = ((s["receita_d"] - s["cmv_d"]) / s["receita_d"] * 100).where(s["receita_d"] > 0)
    gap = m_d - alvo
    situacao = np.select(
        [s["receita_d"] <= 0, alvo.isna(), gap.abs() <= FAIXA_NO_ALVO_PP, gap > 0],
        ["sem_venda", "sem_alvo", "no_alvo", "acima"],
        default="abaixo",
    )
    return pd.DataFrame({
        "alvo": alvo,
        "margem_no_dia": no_dia,
        "margem_antes": m_a,
        "margem_depois": m_d,
        "gap_pp": gap,
        "receita_antes": s["receita_a"],
        "receita_depois": s["receita_d"],
        "lucro_dia_antes": s["_ld_a"].where(s["_ld_a"] != 0),
        "lucro_dia_depois": s["_ld_d"].where(s["_ld_d"] != 0),
        "qtd_dia_antes": s["_qd_a"].where(s["_qd_a"] != 0),
        "qtd_dia_depois": s["_qd_d"].where(s["_qd_d"] != 0),
        "efeito_lucro_pct": ((s["_ld_d"] - s["_ld_a"]) / s["_ld_a"] * 100).where(s["_ld_a"] > 0),
        "efeito_qtd_pct": ((s["_qd_d"] - s["_qd_a"]) / s["_qd_a"] * 100).where(s["_qd_a"] > 0),
        "situacao": situacao,
    }, index=s.index)


def _registros(tab: pd.DataFrame) -> list[dict]:
    tab = tab.copy()
    numericas = tab.select_dtypes("number").columns
    tab[numericas] = tab[numericas].round(4)
    return tab.astype(object).where(tab.notna(), None).to_dict("records")


def _faixas(serie: pd.Series) -> list[str]:
    return sorted(set(serie) - {""})


def _vigentes(filtrados: pd.DataFrame) -> pd.DataFrame:
    return filtrados.sort_values("dia").groupby("codigo", sort=False).tail(1)


def _iso(dia: pd.Timestamp | None) -> str | None:
    return None if dia is None or pd.isna(dia) else pd.Timestamp(dia).strftime("%Y-%m-%d")


def _filtrar(
    eventos: pd.DataFrame,
    *,
    inicio_periodo: pd.Timestamp | None,
    rodadas: list[str] | None,
    faixas: list[str] | None,
) -> pd.DataFrame:
    f = eventos
    if inicio_periodo is not None:
        f = f.loc[f["dia"] >= inicio_periodo]
    if rodadas:
        dias = {pd.Timestamp(r).normalize() for r in rodadas}
        f = f.loc[f["dia"].isin(dias)]
    if faixas:
        f = f.loc[f["faixa"].isin({x.upper() for x in faixas})]
    return f


def _limites(serie_mov: pd.DataFrame, periodo_dias: int):
    if serie_mov.empty or serie_mov["_data"].notna().sum() == 0:
        return None, None, None
    fim = pd.Timestamp(serie_mov["_data"].max()).normalize()
    inicio = pd.Timestamp(serie_mov["_data"].min()).normalize()
    return inicio, fim, fim - pd.Timedelta(days=int(periodo_dias))


def _serie(serie_mov: pd.DataFrame, codigos: set[str] | None) -> list[dict]:
    df = serie_mov if codigos is None else serie_mov.loc[serie_mov["codigo"].isin(codigos)]
    df = df.loc[df["_data"].notna()]
    if df.empty:
        return []
    totais = _totais_mensais(df)
    meses = _meses_entre(df["_data"].min(), df["_data"].max())
    meses = _recortar_meses_com_dado(meses, totais, None)
    return _pontos_serie(totais, meses)


def _marcadores(eventos: pd.DataFrame) -> list[dict]:
    if eventos.empty:
        return []
    por_dia = eventos.groupby("dia")["codigo"].nunique()
    return [
        {"dia": _iso(dia), "periodo": inicio_mes(dia).strftime("%Y-%m"), "skus": int(skus)}
        for dia, skus in por_dia.items()
    ]


# ---------------------------------------------------------------------------
# Respostas
# ---------------------------------------------------------------------------

def montar_historico(
    eventos: pd.DataFrame,
    serie_mov: pd.DataFrame,
    *,
    periodo_dias: int = 180,
    rodadas: list[str] | None = None,
    faixas: list[str] | None = None,
    nivel: str = "familia",
    todos: bool = False,
    busca: str | None = None,
) -> dict:
    """Linha do tempo, indicadores, série e tabela da aba Pós-precificação.

    `eventos` já vem de `calcular_efeitos`. `todos` só troca a série do gráfico
    (loja inteira × SKUs precificados) — a tabela é, por definição, do que foi
    precificado.
    """
    if nivel not in (*NIVEIS, "rodada"):
        raise ValueError(f"nível inválido: {nivel}")
    inicio_mov, fim_mov, inicio_periodo = _limites(serie_mov, periodo_dias)

    # Linha do tempo: todas as rodadas do dump, marcando o que cabe no período e
    # o que dá para medir (precisa de movimento antes do dia).
    linha_tempo = []
    if not eventos.empty:
        por_dia = eventos.groupby("dia").agg(skus=("codigo", "nunique"), mensuravel=("mensuravel", "any"))
        pares = eventos.drop_duplicates(["dia", "descricao", "fabricante"]).groupby("dia").size()
        selecionadas = {pd.Timestamp(r).normalize() for r in rodadas} if rodadas else None
        for dia, linha in por_dia.iterrows():
            linha_tempo.append({
                "dia": _iso(dia),
                "skus": int(linha.skus),
                "pares": int(pares.get(dia, 0)),
                "mensuravel": bool(linha.mensuravel),
                "no_periodo": inicio_periodo is None or dia >= inicio_periodo,
                "selecionada": selecionadas is None or dia in selecionadas,
            })

    filtrados = _filtrar(eventos, inicio_periodo=inicio_periodo, rodadas=rodadas, faixas=faixas)
    vigentes = _vigentes(filtrados)
    codigos = set(vigentes["codigo"])

    kpis: dict[str, Any] = {
        "skus": int(len(vigentes)),
        "pares": int(vigentes.drop_duplicates(["descricao", "fabricante"]).shape[0]),
        "rodadas": int(filtrados["dia"].nunique()),
        "receita_coberta_pct": None,
        "pct_acima": None,
        "situacoes": {},
    }
    if not vigentes.empty:
        total = _tabela(_agrupar(vigentes, pd.Series("todos", index=vigentes.index)))
        kpis.update(_registros(total)[0])
        situacoes = _tabela(_agrupar(vigentes, vigentes["codigo"]))["situacao"].value_counts()
        kpis["situacoes"] = {k: int(situacoes.get(k, 0)) for k in ("acima", "no_alvo", "abaixo", "sem_venda", "sem_alvo")}
        com_venda = int(situacoes.sum() - situacoes.get("sem_venda", 0))
        if com_venda:
            kpis["pct_acima"] = round(100 * int(situacoes.get("acima", 0)) / com_venda, 4)
    if inicio_periodo is not None:
        no_periodo = serie_mov.loc[serie_mov["_data"] >= inicio_periodo]
        total_rec = float(no_periodo["Receita"].sum())
        if total_rec > 0:
            coberta = float(no_periodo.loc[no_periodo["codigo"].isin(codigos), "Receita"].sum())
            kpis["receita_coberta_pct"] = round(100 * coberta / total_rec, 4)

    tab = pd.DataFrame()
    if nivel == "rodada" and not filtrados.empty:
        chave = filtrados["dia"].dt.strftime("%Y-%m-%d")
        tab = _tabela(_agrupar(filtrados, chave))
        tab["skus"] = filtrados.groupby(chave)["codigo"].nunique()
        tab["precificacoes"] = 1
        tab["ultima"] = tab.index
        tab["faixas"] = filtrados.groupby(chave)["faixa"].agg(_faixas)
        tab = tab.sort_index(ascending=False)
    elif nivel != "rodada" and not vigentes.empty:
        chave_v = _chave(vigentes, nivel)
        chave_f = _chave(filtrados, nivel)
        tab = _tabela(_agrupar(vigentes, chave_v))
        tab["skus"] = vigentes.groupby(chave_v)["codigo"].nunique()
        contagem = filtrados.groupby(chave_f)["dia"].agg(["nunique", "max"])
        tab["precificacoes"] = contagem["nunique"]
        tab["ultima"] = contagem["max"].dt.strftime("%Y-%m-%d")
        if nivel == "sku":
            info = vigentes.set_index("codigo")
            for coluna in ("descricao", "fabricante", "fx"):
                tab[coluna] = info[coluna]
            tab["faixas"] = info["faixa"].map(lambda f: [f] if f else [])
        else:
            tab["faixas"] = vigentes.groupby(chave_v)["faixa"].agg(_faixas)
        if busca and busca.strip():
            texto = tab.index.to_series().astype(str)
            if nivel == "sku":
                texto = texto + " " + tab["descricao"].astype(str) + " " + tab["fabricante"].astype(str)
            tab = tab.loc[texto.str.casefold().str.contains(busca.strip().casefold(), regex=False)]
        tab = tab.sort_values(["receita_depois", "receita_antes"], ascending=False)
    total_linhas = int(len(tab))
    linhas: list[dict] = []
    if total_linhas:
        tab = tab.head(LIMITE_LINHAS)
        tab.insert(0, "nome", tab.index.astype(str))
        linhas = _registros(tab.reset_index(drop=True))

    return {
        "periodo_dias": int(periodo_dias),
        "janela_dias": JANELA_DIAS,
        "inicio_periodo": _iso(inicio_periodo),
        "inicio_movimento": _iso(inicio_mov),
        "fim_movimento": _iso(fim_mov),
        "faixas_disponiveis": _faixas(eventos["faixa"]) if not eventos.empty else [],
        "linha_tempo": linha_tempo,
        "kpis": kpis,
        "serie_mensal": _serie(serie_mov, None if todos else codigos),
        "marcadores": _marcadores(filtrados),
        "nivel": nivel,
        "linhas": linhas,
        "total_linhas": total_linhas,
    }


def montar_item(
    eventos: pd.DataFrame,
    serie_mov: pd.DataFrame,
    *,
    nivel: str,
    nome: str,
    periodo_dias: int = 180,
    rodadas: list[str] | None = None,
    faixas: list[str] | None = None,
) -> dict:
    """Painel do item: histórico de precificações, série do item e SKUs que mais pesam."""
    if nivel not in NIVEIS:
        raise ValueError(f"nível inválido: {nivel}")
    _, _, inicio_periodo = _limites(serie_mov, periodo_dias)
    filtrados = _filtrar(eventos, inicio_periodo=inicio_periodo, rodadas=rodadas, faixas=faixas)
    grupo = filtrados.loc[_chave(filtrados, nivel) == nome]
    # O histórico mostra também as rodadas fora do filtro — é o que conta a
    # história do item; só a janela de efeito dos SKUs respeita o filtro.
    todas = eventos.loc[_chave(eventos, nivel) == nome]
    historico: list[dict] = []
    if not todas.empty:
        chave = todas["dia"].dt.strftime("%Y-%m-%d")
        tab = _tabela(_agrupar(todas, chave))[["alvo", "margem_no_dia"]]
        tab["skus"] = todas.groupby(chave)["codigo"].nunique()
        tab["mensuravel"] = todas.groupby(chave)["mensuravel"].any()
        tab["no_filtro"] = tab.index.isin(set(grupo["dia"].dt.strftime("%Y-%m-%d")))
        tab = tab.sort_index(ascending=False)
        tab.insert(0, "dia", tab.index)
        historico = _registros(tab.reset_index(drop=True))
    vigentes = _vigentes(grupo)
    skus: list[dict] = []
    if not vigentes.empty:
        tab = _tabela(_agrupar(vigentes, vigentes["codigo"]))
        info = vigentes.set_index("codigo")
        for coluna in ("descricao", "fabricante", "fx"):
            tab[coluna] = info[coluna]
        tab = tab.sort_values("receita_depois", ascending=False).head(LIMITE_SKUS_ITEM)
        tab.insert(0, "codigo", tab.index)
        skus = _registros(tab.reset_index(drop=True))
    return {
        "nivel": nivel,
        "nome": nome,
        "skus_total": int(len(vigentes)),
        "fabricantes": int(vigentes["fabricante"].nunique()) if not vigentes.empty else 0,
        "faixas": _faixas(vigentes["faixa"]) if not vigentes.empty else [],
        "historico": historico,
        "serie_mensal": _serie(serie_mov, set(todas["codigo"])),
        "marcadores": _marcadores(todas),
        "skus": skus,
    }
