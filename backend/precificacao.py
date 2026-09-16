"""Acompanhamento pós-precificação.

O dump `{empresa}_PRECIFICACAO.csv` diz *quem* entrou na rodada e *qual* alvo
de margem foi gravado. O movimento da empresa diz *como* esses pares
família × fabricante venderam depois da data do dump, contra uma janela de
mesmo comprimento imediatamente anterior.

Sem código de produto no dump: o join é `descricao` (= DESCRICAO_HARMONIZADA)
+ `fabricante`. Família ou fabricante que não estava no dump não entra — senão
a tela misturaria o que foi precificado com o resto do catálogo.

A série mensal cobre as duas janelas (antes + depois) para o gráfico parecer
com o da tela de precificação: margem, lucro bruto / dia com venda e
quantidade / dia com venda. `lucro_dia` e `qtd_dia` são as mesmas medidas do
monitor — valor do mês ÷ dias com venda real, não ÷ dias úteis de calendário.
"""

from __future__ import annotations

import math
from collections import Counter
from datetime import date
from typing import Any

import pandas as pd

from periodo_mensal import (
    deslocar_mes,
    inicio_mes,
    mes_atual_calendario,
    numero,
    rotulo_periodo,
    variacao,
)

COLUNA_DATA_DIARIA = "Data_Venda_Diaria"
COLUNA_DATA_MES = "Data_Venda"
COLUNA_RECEITA = "Receita"
COLUNA_CMV = "CMV"
COLUNA_QTD = "QTD"

SITUACOES = ("acima", "abaixo", "no_alvo", "sem_venda", "sem_alvo")

# Janela da visão "Detalhada": dia a dia, não mês a mês. Fixa e pequena de
# propósito — é um zoom no entorno do corte, não outra forma de ver a janela
# antes/depois inteira (que já é o gráfico mensal).
JANELA_DETALHE_DIAS = 20


def _chave_texto(serie: pd.Series) -> pd.Series:
    return serie.fillna("").astype(str).str.strip().str.casefold()


def _margem_pct(receita: float, cmv: float) -> float | None:
    if receita <= 0:
        return None
    return (receita - cmv) / receita * 100


def _por_dia(valor: float, dias: int) -> float | None:
    if dias <= 0:
        return None
    return valor / dias


def _ponderar(valores: pd.Series, pesos: pd.Series) -> float | None:
    validos = valores.notna() & pesos.notna() & (pesos > 0)
    if not bool(validos.any()):
        return None
    peso = float(pesos.loc[validos].sum())
    if peso <= 0:
        return None
    return float((valores.loc[validos] * pesos.loc[validos]).sum() / peso)


def _json_num(valor: Any) -> float:
    return round(numero(valor), 4)


def _json_opt(valor: Any) -> float | None:
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        return None
    try:
        convertido = float(valor)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(convertido):
        return None
    return round(convertido, 4)


def _iso(valor: pd.Timestamp | None) -> str | None:
    if valor is None or pd.isna(valor):
        return None
    return pd.Timestamp(valor).strftime("%Y-%m-%d")


def _datas_movimento(movimento: pd.DataFrame) -> pd.Series:
    if COLUNA_DATA_DIARIA in movimento.columns:
        datas = pd.to_datetime(movimento[COLUNA_DATA_DIARIA], errors="coerce")
        if bool(datas.notna().any()):
            return datas
    if COLUNA_DATA_MES in movimento.columns:
        return pd.to_datetime(movimento[COLUNA_DATA_MES], errors="coerce")
    return pd.Series(pd.NaT, index=movimento.index, dtype="datetime64[ns]")


def _teto_mes_fechado(ultimo: pd.Timestamp, hoje: date) -> pd.Timestamp:
    """Último instante da janela 'depois' quando o mês corrente ainda está aberto."""
    if inicio_mes(ultimo) != mes_atual_calendario(hoje):
        return ultimo
    return inicio_mes(ultimo) - pd.Timedelta(days=1)


def _contar_dias_venda(df: pd.DataFrame) -> int:
    if df.empty or "_data" not in df.columns:
        return 0
    tem_data = df["_data"].notna()
    ativo = pd.Series(False, index=df.index)
    if COLUNA_RECEITA in df.columns:
        ativo = ativo | (df[COLUNA_RECEITA].fillna(0) != 0)
    if COLUNA_QTD in df.columns:
        ativo = ativo | (df[COLUNA_QTD].fillna(0) != 0)
    validos = df.loc[tem_data & ativo, "_data"]
    if validos.empty:
        return 0
    return int(pd.to_datetime(validos).dt.normalize().nunique())


def _agregar(df: pd.DataFrame) -> dict[str, Any]:
    if df.empty:
        return {
            "receita": 0.0,
            "cmv": 0.0,
            "qtd": 0.0,
            "lucro": 0.0,
            "margem": None,
            "dias_venda": 0,
            "lucro_dia": None,
            "qtd_dia": None,
        }
    receita = float(df[COLUNA_RECEITA].sum())
    cmv = float(df[COLUNA_CMV].sum()) if COLUNA_CMV in df.columns else 0.0
    qtd = float(df[COLUNA_QTD].sum()) if COLUNA_QTD in df.columns else 0.0
    lucro = receita - cmv
    dias = _contar_dias_venda(df)
    return {
        "receita": receita,
        "cmv": cmv,
        "qtd": qtd,
        "lucro": lucro,
        "margem": _margem_pct(receita, cmv),
        "dias_venda": dias,
        "lucro_dia": _por_dia(lucro, dias),
        "qtd_dia": _por_dia(qtd, dias),
    }


# Cartões "semana / quinzena / mês pós precificação": comparação de mesmo
# comprimento (N dias antes do corte vs N dias depois), não a janela
# antes/depois inteira — essa responde "melhorou no total", os cartões
# respondem "melhorou logo na largada, e continuou melhorando".
JANELAS_FIXAS: tuple[tuple[str, int], ...] = (("semana", 7), ("quinzena", 15), ("mes", 30))


def _fatia_por_dias(
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    dias: int,
    lado: str,
) -> pd.DataFrame:
    if mov_pares.empty or "_data" not in mov_pares.columns or data_corte is None:
        return mov_pares.iloc[0:0]
    if lado == "depois":
        ini, fim = data_corte, data_corte + pd.Timedelta(days=dias)
    else:
        ini, fim = data_corte - pd.Timedelta(days=dias), data_corte
    mascara = (mov_pares["_data"] >= ini) & (mov_pares["_data"] < fim)
    return mov_pares.loc[mascara]


def _resumo_janela_fixa(
    dump_grupo: pd.DataFrame,
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    dias: int,
    ultimo_disponivel: pd.Timestamp | None,
) -> dict:
    antes = _fatia_por_dias(mov_pares, data_corte, dias, "antes")
    depois = _fatia_por_dias(mov_pares, data_corte, dias, "depois")
    ant = _agregar(antes)
    dep = _agregar(depois)
    alvo = _ponderar(dump_grupo["margem_alvo"], dump_grupo["receita"])
    gap = None if dep["margem"] is None or alvo is None else dep["margem"] - alvo
    completa = bool(
        data_corte is not None
        and ultimo_disponivel is not None
        and ultimo_disponivel >= data_corte + pd.Timedelta(days=dias - 1)
    )
    return {
        "dias": dias,
        "completa": completa,
        "receita_antes": _json_num(ant["receita"]),
        "receita_depois": _json_num(dep["receita"]),
        "lucro_antes": _json_num(ant["lucro"]),
        "lucro_depois": _json_num(dep["lucro"]),
        "qtd_antes": _json_num(ant["qtd"]),
        "qtd_depois": _json_num(dep["qtd"]),
        "margem_antes": _json_opt(ant["margem"]),
        "margem_depois": _json_opt(dep["margem"]),
        "dias_venda_antes": int(ant["dias_venda"]),
        "dias_venda_depois": int(dep["dias_venda"]),
        "lucro_dia_antes": _json_opt(ant["lucro_dia"]),
        "lucro_dia_depois": _json_opt(dep["lucro_dia"]),
        "qtd_dia_antes": _json_opt(ant["qtd_dia"]),
        "qtd_dia_depois": _json_opt(dep["qtd_dia"]),
        "variacao_receita_pct": _json_opt(variacao(dep["receita"], ant["receita"])),
        "variacao_lucro_pct": _json_opt(variacao(dep["lucro"], ant["lucro"])),
        "variacao_qtd_pct": _json_opt(variacao(dep["qtd"], ant["qtd"])),
        "margem_alvo": _json_opt(alvo),
        "gap_alvo_pp": _json_opt(gap),
    }


def _janela_fixa_vazia(dias: int) -> dict:
    return {
        "dias": dias,
        "completa": False,
        "receita_antes": 0.0,
        "receita_depois": 0.0,
        "lucro_antes": 0.0,
        "lucro_depois": 0.0,
        "qtd_antes": 0.0,
        "qtd_depois": 0.0,
        "margem_antes": None,
        "margem_depois": None,
        "dias_venda_antes": 0,
        "dias_venda_depois": 0,
        "lucro_dia_antes": None,
        "lucro_dia_depois": None,
        "qtd_dia_antes": None,
        "qtd_dia_depois": None,
        "variacao_receita_pct": None,
        "variacao_lucro_pct": None,
        "variacao_qtd_pct": None,
        "margem_alvo": None,
        "gap_alvo_pp": None,
    }


def _janelas_fixas(
    dump_grupo: pd.DataFrame,
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    ultimo_disponivel: pd.Timestamp | None,
) -> dict[str, dict]:
    return {
        chave: _resumo_janela_fixa(dump_grupo, mov_pares, data_corte, dias, ultimo_disponivel)
        for chave, dias in JANELAS_FIXAS
    }


def _item_entidade(
    nome: str,
    dump_grupo: pd.DataFrame,
    antes: pd.DataFrame,
    depois: pd.DataFrame,
    serie: list[dict],
    serie_diaria: list[dict],
    janelas: dict[str, dict],
) -> dict:
    ant = _agregar(antes)
    dep = _agregar(depois)
    alvo = _ponderar(dump_grupo["margem_alvo"], dump_grupo["receita"])
    gap = None if dep["margem"] is None or alvo is None else dep["margem"] - alvo
    if dep["receita"] <= 0:
        situacao = "sem_venda"
    elif gap is None:
        situacao = "sem_alvo"
    elif abs(gap) <= 1.0:
        situacao = "no_alvo"
    elif gap > 0:
        situacao = "acima"
    else:
        situacao = "abaixo"
    return {
        "nome": nome,
        "skus_dump": int(len(dump_grupo)),
        "receita_dump": _json_num(dump_grupo["receita"].sum()),
        "margem_anterior_dump": _json_opt(_ponderar(dump_grupo["margem_anterior"], dump_grupo["receita"])),
        "margem_alvo": _json_opt(alvo),
        "receita_antes": _json_num(ant["receita"]),
        "receita_depois": _json_num(dep["receita"]),
        "lucro_antes": _json_num(ant["lucro"]),
        "lucro_depois": _json_num(dep["lucro"]),
        "qtd_antes": _json_num(ant["qtd"]),
        "qtd_depois": _json_num(dep["qtd"]),
        "margem_antes": _json_opt(ant["margem"]),
        "margem_depois": _json_opt(dep["margem"]),
        "dias_venda_antes": int(ant["dias_venda"]),
        "dias_venda_depois": int(dep["dias_venda"]),
        "lucro_dia_antes": _json_opt(ant["lucro_dia"]),
        "lucro_dia_depois": _json_opt(dep["lucro_dia"]),
        "qtd_dia_antes": _json_opt(ant["qtd_dia"]),
        "qtd_dia_depois": _json_opt(dep["qtd_dia"]),
        "variacao_receita_pct": _json_opt(variacao(dep["receita"], ant["receita"])),
        "variacao_lucro_pct": _json_opt(variacao(dep["lucro"], ant["lucro"])),
        "variacao_qtd_pct": _json_opt(variacao(dep["qtd"], ant["qtd"])),
        "gap_alvo_pp": _json_opt(gap),
        "situacao": situacao,
        "serie_mensal": serie,
        "serie_diaria": serie_diaria,
        "janelas": janelas,
    }


def montar_pos_precificacao(
    dump: pd.DataFrame,
    movimento: pd.DataFrame,
    *,
    usar_mes_fechado: bool = True,
    hoje: date | None = None,
) -> dict:
    """Resumo da última rodada de precificação + desempenho no movimento.

    `dump` já vem de `carregar_csv_precificacao`. `movimento` é a base canônica
    (com `descricao`, `NOME_FABRICANTE`, `Receita`, `CMV`, `QTD` e data).
    """
    hoje_ref = hoje or date.today()
    vazio = _resposta_vazia()
    if dump is None or dump.empty:
        return vazio

    dump = dump.copy()
    dump = dump[dump["descricao"].astype(str).str.strip() != ""]
    dump = dump[dump["fabricante"].astype(str).str.strip() != ""]
    if dump.empty:
        return vazio

    data_corte = dump["data_exportacao"].max()
    if pd.isna(data_corte):
        data_corte = None
    else:
        data_corte = pd.Timestamp(data_corte).normalize()

    pares = dump.assign(
        _d=_chave_texto(dump["descricao"]),
        _f=_chave_texto(dump["fabricante"]),
    )
    pares["_chave"] = pares["_d"] + "\x1f" + pares["_f"]
    chaves = set(pares["_chave"])

    if movimento is None or movimento.empty or COLUNA_RECEITA not in movimento.columns:
        mov_pares = pd.DataFrame()
        ultimo = None
    elif "descricao" not in movimento.columns or "NOME_FABRICANTE" not in movimento.columns:
        mov_pares = pd.DataFrame()
        ultimo = None
    else:
        chave_mov = _chave_texto(movimento["descricao"]) + "\x1f" + _chave_texto(movimento["NOME_FABRICANTE"])
        colunas = [coluna for coluna in (
            "descricao", "NOME_FABRICANTE", COLUNA_RECEITA, COLUNA_CMV, COLUNA_QTD,
            COLUNA_DATA_DIARIA, COLUNA_DATA_MES, "Periodo_Mensal",
        ) if coluna in movimento.columns]
        mov_pares = movimento.loc[chave_mov.isin(chaves), colunas].copy()
        if COLUNA_CMV not in mov_pares.columns:
            mov_pares[COLUNA_CMV] = 0.0
        if COLUNA_QTD not in mov_pares.columns:
            mov_pares[COLUNA_QTD] = 0.0
        datas = _datas_movimento(mov_pares)
        mov_pares["_data"] = datas
        ultimo = datas.max() if bool(datas.notna().any()) else None
        if usar_mes_fechado and ultimo is not None and not pd.isna(ultimo):
            ultimo = _teto_mes_fechado(pd.Timestamp(ultimo), hoje_ref)

    inicio_depois = data_corte
    fim_depois = pd.Timestamp(ultimo) if ultimo is not None and not pd.isna(ultimo) else None
    inicio_antes = None
    fim_antes = data_corte
    if inicio_depois is not None and fim_depois is not None and fim_depois >= inicio_depois:
        duracao = fim_depois - inicio_depois
        inicio_antes = inicio_depois - duracao
    elif inicio_depois is not None and (fim_depois is None or fim_depois < inicio_depois):
        fim_depois = None

    if "_data" in mov_pares.columns and not mov_pares.empty:
        mascara_depois = pd.Series(False, index=mov_pares.index)
        mascara_antes = pd.Series(False, index=mov_pares.index)
        if inicio_depois is not None and fim_depois is not None:
            mascara_depois = (mov_pares["_data"] >= inicio_depois) & (mov_pares["_data"] <= fim_depois)
        if inicio_antes is not None and fim_antes is not None:
            mascara_antes = (mov_pares["_data"] >= inicio_antes) & (mov_pares["_data"] < fim_antes)
        depois = mov_pares.loc[mascara_depois]
        antes = mov_pares.loc[mascara_antes]
    else:
        depois = mov_pares.iloc[0:0]
        antes = mov_pares.iloc[0:0]

    ant = _agregar(antes)
    dep = _agregar(depois)
    alvo_geral = _ponderar(dump["margem_alvo"], dump["receita"])
    gap_geral = None if dep["margem"] is None or alvo_geral is None else dep["margem"] - alvo_geral

    precos = dump["preco_sugerido"] if "preco_sugerido" in dump.columns else pd.Series(dtype=float)
    skus_com_preco = int(precos.notna().sum()) if not precos.empty else 0

    inicio_serie = inicio_antes if inicio_antes is not None else inicio_depois
    fim_serie = fim_depois if fim_depois is not None else fim_antes
    meses = _meses_entre(inicio_serie, fim_serie)
    janela = pd.concat([antes, depois]) if not antes.empty or not depois.empty else depois
    serie_geral = _pontos_serie(_totais_mensais(janela), meses)
    series_prod = _series_por_nome(janela, "descricao", dump["descricao"], meses)
    series_fab = _series_por_nome(janela, "NOME_FABRICANTE", dump["fabricante"], meses)

    janela_dia_ini = None if data_corte is None else data_corte - pd.Timedelta(days=JANELA_DETALHE_DIAS)
    janela_dia_fim = None if data_corte is None else data_corte + pd.Timedelta(days=JANELA_DETALHE_DIAS)
    if janela_dia_ini is not None and inicio_antes is not None:
        janela_dia_ini = max(janela_dia_ini, inicio_antes)
    if janela_dia_fim is not None and fim_depois is not None:
        janela_dia_fim = min(janela_dia_fim, fim_depois)
    dias_detalhe = _dias_entre(janela_dia_ini, janela_dia_fim)
    serie_diaria_geral = _pontos_serie_diaria(_totais_diarios(janela), dias_detalhe)
    series_prod_dia = _series_por_nome_dia(janela, "descricao", dump["descricao"], dias_detalhe)
    series_fab_dia = _series_por_nome_dia(janela, "NOME_FABRICANTE", dump["fabricante"], dias_detalhe)

    janelas_geral = _janelas_fixas(dump, mov_pares, data_corte, fim_depois)
    produtos = _rollup(
        dump, antes, depois, "descricao", "descricao", series_prod, series_prod_dia,
        mov_pares, data_corte, fim_depois,
    )
    fabricantes = _rollup(
        dump, antes, depois, "fabricante", "NOME_FABRICANTE", series_fab, series_fab_dia,
        mov_pares, data_corte, fim_depois,
    )

    return {
        "data_precificacao": _iso(data_corte),
        "periodo_corte": inicio_mes(data_corte).strftime("%Y-%m") if data_corte is not None else None,
        "periodo_antes": {"inicio": _iso(inicio_antes), "fim": _iso(fim_antes)},
        "periodo_depois": {"inicio": _iso(inicio_depois), "fim": _iso(fim_depois)},
        "dias": int((fim_depois - inicio_depois).days) if inicio_depois is not None and fim_depois is not None else 0,
        "linhas_dump": int(len(dump)),
        "familias": int(dump["descricao"].nunique()),
        "fabricantes_qtd": int(dump["fabricante"].nunique()),
        "pares": int(len(chaves)),
        "skus_com_preco_sugerido": skus_com_preco,
        "tem_movimento_depois": dep["receita"] > 0,
        "resumo": {
            "receita_dump": _json_num(dump["receita"].sum()),
            "margem_anterior_dump": _json_opt(_ponderar(dump["margem_anterior"], dump["receita"])),
            "margem_alvo": _json_opt(alvo_geral),
            "receita_antes": _json_num(ant["receita"]),
            "receita_depois": _json_num(dep["receita"]),
            "lucro_antes": _json_num(ant["lucro"]),
            "lucro_depois": _json_num(dep["lucro"]),
            "qtd_antes": _json_num(ant["qtd"]),
            "qtd_depois": _json_num(dep["qtd"]),
            "margem_antes": _json_opt(ant["margem"]),
            "margem_depois": _json_opt(dep["margem"]),
            "dias_venda_antes": int(ant["dias_venda"]),
            "dias_venda_depois": int(dep["dias_venda"]),
            "lucro_dia_antes": _json_opt(ant["lucro_dia"]),
            "lucro_dia_depois": _json_opt(dep["lucro_dia"]),
            "qtd_dia_antes": _json_opt(ant["qtd_dia"]),
            "qtd_dia_depois": _json_opt(dep["qtd_dia"]),
            "variacao_receita_pct": _json_opt(variacao(dep["receita"], ant["receita"])),
            "variacao_lucro_pct": _json_opt(variacao(dep["lucro"], ant["lucro"])),
            "variacao_qtd_pct": _json_opt(variacao(dep["qtd"], ant["qtd"])),
            "gap_alvo_pp": _json_opt(gap_geral),
            "situacoes": _contar_situacoes(produtos),
            "janelas": janelas_geral,
        },
        "serie_mensal": serie_geral,
        "serie_diaria": serie_diaria_geral,
        "produtos": produtos,
        "fabricantes": fabricantes,
    }


def _meses_entre(inicio: pd.Timestamp | None, fim: pd.Timestamp | None) -> list[pd.Timestamp]:
    if inicio is None or fim is None or pd.isna(inicio) or pd.isna(fim) or fim < inicio:
        return []
    cursor = inicio_mes(pd.Timestamp(inicio))
    ultimo = inicio_mes(pd.Timestamp(fim))
    meses: list[pd.Timestamp] = []
    while cursor <= ultimo and len(meses) < 36:
        meses.append(cursor)
        cursor = deslocar_mes(cursor, 1)
    return meses


def _totais_mensais(df: pd.DataFrame, extra_grupo: str | None = None) -> pd.DataFrame:
    if df.empty or "_data" not in df.columns:
        return pd.DataFrame()
    tmp = df.loc[df["_data"].notna()].copy()
    if tmp.empty:
        return pd.DataFrame()
    tmp["_mes"] = tmp["_data"].map(lambda d: inicio_mes(pd.Timestamp(d)))
    tmp["_dia"] = pd.to_datetime(tmp["_data"]).dt.normalize()
    if COLUNA_QTD not in tmp.columns:
        tmp[COLUNA_QTD] = 0.0
    if COLUNA_CMV not in tmp.columns:
        tmp[COLUNA_CMV] = 0.0
    ativo = (tmp[COLUNA_RECEITA].fillna(0) != 0) | (tmp[COLUNA_QTD].fillna(0) != 0)
    grupos = ["_mes"] if extra_grupo is None else [extra_grupo, "_mes"]
    totais = tmp.groupby(grupos, sort=True).agg(
        receita=(COLUNA_RECEITA, "sum"),
        cmv=(COLUNA_CMV, "sum"),
        qtd=(COLUNA_QTD, "sum"),
    )
    dias = tmp.loc[ativo].groupby(grupos)["_dia"].nunique()
    totais["dias_venda"] = dias.reindex(totais.index).fillna(0).astype(int)
    return totais


def _ler_mes(totais: pd.DataFrame, mes: pd.Timestamp) -> tuple[float, float, float, int]:
    if totais.empty or mes not in totais.index:
        return 0.0, 0.0, 0.0, 0
    linha = totais.loc[mes]
    if isinstance(linha, pd.DataFrame):
        return (
            float(linha["receita"].sum()),
            float(linha["cmv"].sum()),
            float(linha["qtd"].sum()),
            int(linha["dias_venda"].sum()),
        )
    return (
        float(linha["receita"]),
        float(linha["cmv"]),
        float(linha["qtd"]),
        int(linha["dias_venda"]),
    )


def _pontos_serie(totais: pd.DataFrame, meses: list[pd.Timestamp]) -> list[dict]:
    pontos = []
    for mes in meses:
        rec, cmv, qtd, dias = _ler_mes(totais, mes)
        lucro = rec - cmv
        pontos.append({
            "periodo": mes.strftime("%Y-%m"),
            "rotulo": rotulo_periodo(mes),
            "receita": _json_num(rec),
            "lucro": _json_num(lucro),
            "qtd": _json_num(qtd),
            "margem": _json_opt(_margem_pct(rec, cmv)),
            "dias_venda": int(dias),
            "lucro_dia": _json_opt(_por_dia(lucro, int(dias))),
            "qtd_dia": _json_opt(_por_dia(qtd, int(dias))),
        })
    return pontos


def _dias_entre(inicio: pd.Timestamp | None, fim: pd.Timestamp | None, limite: int = 90) -> list[pd.Timestamp]:
    if inicio is None or fim is None or pd.isna(inicio) or pd.isna(fim) or fim < inicio:
        return []
    cursor = pd.Timestamp(inicio).normalize()
    ultimo = pd.Timestamp(fim).normalize()
    dias: list[pd.Timestamp] = []
    while cursor <= ultimo and len(dias) < limite:
        dias.append(cursor)
        cursor = cursor + pd.Timedelta(days=1)
    return dias


def _totais_diarios(df: pd.DataFrame, extra_grupo: str | None = None) -> pd.DataFrame:
    if df.empty or "_data" not in df.columns:
        return pd.DataFrame()
    tmp = df.loc[df["_data"].notna()].copy()
    if tmp.empty:
        return pd.DataFrame()
    tmp["_dia"] = pd.to_datetime(tmp["_data"]).dt.normalize()
    if COLUNA_QTD not in tmp.columns:
        tmp[COLUNA_QTD] = 0.0
    if COLUNA_CMV not in tmp.columns:
        tmp[COLUNA_CMV] = 0.0
    grupos = ["_dia"] if extra_grupo is None else [extra_grupo, "_dia"]
    return tmp.groupby(grupos, sort=True).agg(
        receita=(COLUNA_RECEITA, "sum"),
        cmv=(COLUNA_CMV, "sum"),
        qtd=(COLUNA_QTD, "sum"),
    )


def _ler_dia(totais: pd.DataFrame, dia: pd.Timestamp) -> tuple[float, float, float]:
    if totais.empty or dia not in totais.index:
        return 0.0, 0.0, 0.0
    linha = totais.loc[dia]
    if isinstance(linha, pd.DataFrame):
        return float(linha["receita"].sum()), float(linha["cmv"].sum()), float(linha["qtd"].sum())
    return float(linha["receita"]), float(linha["cmv"]), float(linha["qtd"])


def _pontos_serie_diaria(totais: pd.DataFrame, dias: list[pd.Timestamp]) -> list[dict]:
    """Um ponto por dia *com venda* da janela de detalhe.

    Fim de semana e feriado sem movimento não entram — não é dado zero, é
    ausência de loja aberta, e plotar isso quebrava o gráfico em dentes de
    serra. A granularidade já é o dia, então `lucro_dia`/`qtd_dia` são o
    próprio lucro/qtd do dia."""
    pontos = []
    for dia in dias:
        rec, cmv, qtd = _ler_dia(totais, dia)
        if rec == 0 and qtd == 0:
            continue
        lucro = rec - cmv
        pontos.append({
            "periodo": dia.strftime("%Y-%m-%d"),
            "rotulo": dia.strftime("%d/%m"),
            "receita": _json_num(rec),
            "lucro": _json_num(lucro),
            "qtd": _json_num(qtd),
            "margem": _json_opt(_margem_pct(rec, cmv)),
            "dias_venda": 1,
            "lucro_dia": _json_opt(lucro),
            "qtd_dia": _json_opt(qtd),
        })
    return pontos


def _series_por_nome_dia(
    df: pd.DataFrame,
    coluna: str,
    nomes: pd.Series,
    dias: list[pd.Timestamp],
) -> dict[str, list[dict]]:
    unicos: list[str] = []
    vistos: set[str] = set()
    for nome in nomes:
        rotulo = "—" if pd.isna(nome) or str(nome).strip() == "" else str(nome).strip()
        if rotulo in vistos:
            continue
        vistos.add(rotulo)
        unicos.append(rotulo)
    if not unicos:
        return {}
    if df.empty or coluna not in df.columns:
        return {nome: _pontos_serie_diaria(pd.DataFrame(), dias) for nome in unicos}
    tmp = df.copy()
    tmp["_ent"] = _chave_texto(tmp[coluna])
    totais = _totais_diarios(tmp, extra_grupo="_ent")
    nivel0 = set(totais.index.get_level_values(0)) if not totais.empty else set()
    saida: dict[str, list[dict]] = {}
    for nome in unicos:
        chave = nome.casefold()
        if chave not in nivel0:
            saida[nome] = _pontos_serie_diaria(pd.DataFrame(), dias)
            continue
        fatia = totais.loc[totais.index.get_level_values(0) == chave].droplevel(0)
        saida[nome] = _pontos_serie_diaria(fatia, dias)
    return saida


def _series_por_nome(
    df: pd.DataFrame,
    coluna: str,
    nomes: pd.Series,
    meses: list[pd.Timestamp],
) -> dict[str, list[dict]]:
    unicos: list[str] = []
    vistos: set[str] = set()
    for nome in nomes:
        rotulo = "—" if pd.isna(nome) or str(nome).strip() == "" else str(nome).strip()
        if rotulo in vistos:
            continue
        vistos.add(rotulo)
        unicos.append(rotulo)
    if not unicos:
        return {}
    if df.empty or coluna not in df.columns:
        return {nome: _pontos_serie(pd.DataFrame(), meses) for nome in unicos}
    tmp = df.copy()
    tmp["_ent"] = _chave_texto(tmp[coluna])
    totais = _totais_mensais(tmp, extra_grupo="_ent")
    nivel0 = set(totais.index.get_level_values(0)) if not totais.empty else set()
    saida: dict[str, list[dict]] = {}
    for nome in unicos:
        chave = nome.casefold()
        if chave not in nivel0:
            saida[nome] = _pontos_serie(pd.DataFrame(), meses)
            continue
        fatia = totais.loc[totais.index.get_level_values(0) == chave].droplevel(0)
        saida[nome] = _pontos_serie(fatia, meses)
    return saida


def _rollup(
    dump: pd.DataFrame,
    antes: pd.DataFrame,
    depois: pd.DataFrame,
    coluna_dump: str,
    coluna_mov: str,
    series: dict[str, list[dict]],
    series_dia: dict[str, list[dict]],
    mov_pares: pd.DataFrame,
    data_corte: pd.Timestamp | None,
    ultimo_disponivel: pd.Timestamp | None,
) -> list[dict]:
    itens = []
    vazia = series.get("", [])
    vazia_dia = series_dia.get("", [])
    for nome, grupo in dump.groupby(coluna_dump, dropna=False):
        rotulo = str(nome).strip() or "—"
        chave = str(nome).strip().casefold()
        if coluna_mov in antes.columns:
            ant = antes.loc[_chave_texto(antes[coluna_mov]) == chave]
        else:
            ant = antes.iloc[0:0]
        if coluna_mov in depois.columns:
            dep = depois.loc[_chave_texto(depois[coluna_mov]) == chave]
        else:
            dep = depois.iloc[0:0]
        if coluna_mov in mov_pares.columns:
            mov_ent = mov_pares.loc[_chave_texto(mov_pares[coluna_mov]) == chave]
        else:
            mov_ent = mov_pares.iloc[0:0]
        itens.append(_item_entidade(
            rotulo, grupo, ant, dep,
            series.get(rotulo, vazia),
            series_dia.get(rotulo, vazia_dia),
            _janelas_fixas(grupo, mov_ent, data_corte, ultimo_disponivel),
        ))
    itens.sort(key=lambda item: (item["lucro_depois"], item["receita_depois"]), reverse=True)
    return itens


def _contar_situacoes(itens: list[dict]) -> dict[str, int]:
    contagem = Counter(item["situacao"] for item in itens)
    return {chave: int(contagem.get(chave, 0)) for chave in SITUACOES}


def _resumo_vazio() -> dict:
    return {
        "receita_dump": 0.0,
        "margem_anterior_dump": None,
        "margem_alvo": None,
        "receita_antes": 0.0,
        "receita_depois": 0.0,
        "lucro_antes": 0.0,
        "lucro_depois": 0.0,
        "qtd_antes": 0.0,
        "qtd_depois": 0.0,
        "margem_antes": None,
        "margem_depois": None,
        "dias_venda_antes": 0,
        "dias_venda_depois": 0,
        "lucro_dia_antes": None,
        "lucro_dia_depois": None,
        "qtd_dia_antes": None,
        "qtd_dia_depois": None,
        "variacao_receita_pct": None,
        "variacao_lucro_pct": None,
        "variacao_qtd_pct": None,
        "gap_alvo_pp": None,
        "situacoes": {chave: 0 for chave in SITUACOES},
        "janelas": {chave: _janela_fixa_vazia(dias) for chave, dias in JANELAS_FIXAS},
    }


def _resposta_vazia() -> dict:
    return {
        "data_precificacao": None,
        "periodo_corte": None,
        "periodo_antes": {"inicio": None, "fim": None},
        "periodo_depois": {"inicio": None, "fim": None},
        "dias": 0,
        "linhas_dump": 0,
        "familias": 0,
        "fabricantes_qtd": 0,
        "pares": 0,
        "skus_com_preco_sugerido": 0,
        "tem_movimento_depois": False,
        "resumo": _resumo_vazio(),
        "serie_mensal": [],
        "serie_diaria": [],
        "produtos": [],
        "fabricantes": [],
    }
