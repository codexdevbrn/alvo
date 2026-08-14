"""Alertas de ritmo diário, semanal ou mensal por cliente.

Cada regra compara a mesma janela de dias úteis dos meses históricos. A semana
começa na segunda-feira e é cortada pelos limites do mês, evitando comparar uma
semana parcial com uma completa.
"""

from __future__ import annotations

from datetime import date
import math
from typing import Any

import pandas as pd


COLUNA_DATA_DIARIA = "Data_Venda_Diaria"
DIRECOES = {"queda", "alta", "ambos"}
GRANULARIDADES = {"diaria", "semanal", "mensal"}


def _float_seguro(valor: Any, padrao: float) -> float:
    """Converte entrada externa sem permitir NaN, infinito ou exceção."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return padrao
    return numero if math.isfinite(numero) else padrao


def _int_seguro(valor: Any, padrao: int) -> int:
    try:
        return int(valor)
    except (TypeError, ValueError, OverflowError):
        return padrao


def normalizar_regras_alerta(regras_brutas: Any, tags_validas: set[str]) -> list[dict]:
    """Valida regras persistidas e limita valores a faixas operacionais."""
    if not isinstance(regras_brutas, list):
        return []
    saida: list[dict] = []
    vistos: set[str] = set()
    for indice, item in enumerate(regras_brutas):
        if not isinstance(item, dict):
            continue
        tag_id = str(item.get("tag_id") or "").strip().lower()
        if tag_id not in tags_validas:
            continue
        regra_id = str(item.get("id") or f"ritmo_{tag_id}").strip().lower()
        if not regra_id or regra_id in vistos:
            regra_id = f"ritmo_{tag_id}_{indice + 1}"
        vistos.add(regra_id)
        direcao = str(item.get("direcao") or "queda").strip().lower()
        if direcao not in DIRECOES:
            direcao = "queda"
        granularidade = str(item.get("granularidade") or "mensal").strip().lower()
        if granularidade not in GRANULARIDADES:
            granularidade = "mensal"
        saida.append({
            "id": regra_id,
            "tag_id": tag_id,
            "ativa": bool(item.get("ativa", True)),
            "metrica": "receita",
            "granularidade": granularidade,
            "direcao": direcao,
            "limite_percentual": max(0.0, min(_float_seguro(item.get("limite_percentual"), 20), 1000.0)),
            "limite_valor": max(0.0, _float_seguro(item.get("limite_valor"), 0)),
            "meses_historico": max(2, min(_int_seguro(item.get("meses_historico") or 6, 6), 12)),
            "min_dias_uteis": max(1, min(_int_seguro(item.get("min_dias_uteis") or 2, 2), 10)),
        })
    return saida


def _inicio_mes(valor: pd.Timestamp) -> pd.Timestamp:
    return valor.normalize().replace(day=1)


def _mes_anterior(inicio: pd.Timestamp, quantidade: int) -> pd.Timestamp:
    return (inicio - pd.DateOffset(months=quantidade)).normalize().replace(day=1)


def _fim_mes(inicio: pd.Timestamp) -> pd.Timestamp:
    return inicio + pd.offsets.MonthEnd(0)


def _dias_uteis_ate(inicio: pd.Timestamp, fim: pd.Timestamp) -> pd.DatetimeIndex:
    if fim < inicio:
        return pd.DatetimeIndex([])
    return pd.bdate_range(inicio, fim, normalize=True)


def _corte_por_dias_uteis(inicio: pd.Timestamp, ordinal: int) -> pd.Timestamp:
    dias = pd.bdate_range(inicio, _fim_mes(inicio), normalize=True)
    if len(dias) == 0:
        return inicio
    return dias[min(max(ordinal, 1), len(dias)) - 1]


def _numero(valor: Any, casas: int = 2) -> float:
    return round(float(valor or 0), casas)


def _converter_datas_diarias(valores: pd.Series) -> pd.Series:
    """Aceita datetime, ISO e formato brasileiro sem inverter mês/dia."""
    if pd.api.types.is_datetime64_any_dtype(valores):
        return pd.to_datetime(valores, errors="coerce")
    textos = valores.astype("string").str.strip()
    mascara_iso = textos.str.match(r"^\d{4}-\d{2}-\d{2}(?:[ T].*)?$", na=False)
    convertidas = pd.Series(pd.NaT, index=valores.index, dtype="datetime64[ns]")
    convertidas.loc[mascara_iso] = pd.to_datetime(textos.loc[mascara_iso], errors="coerce", yearfirst=True)
    convertidas.loc[~mascara_iso] = pd.to_datetime(textos.loc[~mascara_iso], errors="coerce", dayfirst=True)
    return convertidas


def avaliar_alertas_clientes(
    df: pd.DataFrame,
    tags_por_cliente: dict[str, list[str]],
    regras: list[dict],
    *,
    data_referencia: date | pd.Timestamp | None = None,
) -> dict:
    """Avalia regras ativas sobre clientes marcados com a tag da regra."""
    base_resposta = {
        "disponivel": False,
        "motivo": "A base precisa ter uma coluna diária, como DATA_VENDA ou DATA_PEDIDO.",
        "data_referencia": None,
        "dia_referencia": None,
        "semana_inicio": None,
        "semana_fim": None,
        "dias_uteis_decorridos": 0,
        "alertas": [],
        "resumo": {"ativos": 0, "quedas": 0, "altas": 0, "clientes_avaliados": 0},
    }
    if df is None or df.empty or COLUNA_DATA_DIARIA not in df.columns:
        return base_resposta

    dados = df.copy()
    dados[COLUNA_DATA_DIARIA] = _converter_datas_diarias(dados[COLUNA_DATA_DIARIA])
    cobertura = float(dados[COLUNA_DATA_DIARIA].notna().mean() * 100)
    if cobertura < 95:
        return {
            **base_resposta,
            "motivo": f"Coluna diária incompleta: {cobertura:.1f}% das linhas possuem data válida.",
        }
    dados = dados.dropna(subset=[COLUNA_DATA_DIARIA]).copy()
    dados[COLUNA_DATA_DIARIA] = dados[COLUNA_DATA_DIARIA].dt.normalize()
    dados["Cliente"] = dados["Cliente"].fillna("").astype(str).str.strip()
    dados["Receita"] = pd.to_numeric(dados["Receita"], errors="coerce").fillna(0.0)
    dados = dados[dados["Cliente"] != ""]
    if dados.empty:
        return base_resposta

    referencia = pd.Timestamp(data_referencia).normalize() if data_referencia is not None else dados[COLUNA_DATA_DIARIA].max()
    inicio_atual = _inicio_mes(referencia)
    dias_uteis = _dias_uteis_ate(inicio_atual, referencia)
    ordinal_atual = len(dias_uteis)
    if ordinal_atual == 0:
        return {**base_resposta, "motivo": "Ainda não há dia útil transcorrido no mês."}
    dia_referencia = dias_uteis[-1]

    inicio_semana = referencia - pd.Timedelta(days=referencia.weekday())
    inicio_semana = max(inicio_semana, inicio_atual)
    fim_semana = min(referencia, inicio_semana + pd.Timedelta(days=6), _fim_mes(inicio_atual))
    ordinal_inicio_semana = max(1, len(_dias_uteis_ate(inicio_atual, inicio_semana - pd.Timedelta(days=1))) + 1)

    regras_ativas = [regra for regra in regras if regra.get("ativa")]
    clientes_regras = {
        cliente.strip()
        for cliente, tags in tags_por_cliente.items()
        if cliente.strip() and any(regra.get("tag_id") in tags for regra in regras_ativas)
    }
    if not clientes_regras:
        return {
            **base_resposta,
            "disponivel": True,
            "motivo": None,
            "data_referencia": referencia.strftime("%Y-%m-%d"),
            "dia_referencia": dia_referencia.strftime("%Y-%m-%d"),
            "semana_inicio": inicio_semana.strftime("%Y-%m-%d"),
            "semana_fim": fim_semana.strftime("%Y-%m-%d"),
            "dias_uteis_decorridos": ordinal_atual,
        }

    atual = dados[
        dados[COLUNA_DATA_DIARIA].between(inicio_atual, referencia)
        & dados["Cliente"].isin(clientes_regras)
    ].groupby("Cliente")["Receita"].sum()
    semana_atual = dados[
        dados[COLUNA_DATA_DIARIA].between(inicio_semana, fim_semana)
        & dados["Cliente"].isin(clientes_regras)
    ].groupby("Cliente")["Receita"].sum()
    dia_atual = dados[
        (dados[COLUNA_DATA_DIARIA] == dia_referencia)
        & dados["Cliente"].isin(clientes_regras)
    ].groupby("Cliente")["Receita"].sum()

    max_historico = max((int(regra.get("meses_historico", 6)) for regra in regras_ativas), default=6)
    inicio_cobertura = _inicio_mes(dados[COLUNA_DATA_DIARIA].min())
    acumulados_historicos: dict[int, pd.Series] = {}
    semanas_historicas: dict[int, pd.Series] = {}
    dias_historicos: dict[int, pd.Series] = {}
    for deslocamento in range(1, max_historico + 1):
        inicio_hist = _mes_anterior(inicio_atual, deslocamento)
        corte_hist = _corte_por_dias_uteis(inicio_hist, ordinal_atual)
        corte_semana_inicio = _corte_por_dias_uteis(inicio_hist, ordinal_inicio_semana)
        recorte = dados[
            dados[COLUNA_DATA_DIARIA].between(inicio_hist, corte_hist)
            & dados["Cliente"].isin(clientes_regras)
        ]
        acumulados_historicos[deslocamento] = recorte.groupby("Cliente")["Receita"].sum()
        dias_historicos[deslocamento] = recorte[
            recorte[COLUNA_DATA_DIARIA] == corte_hist
        ].groupby("Cliente")["Receita"].sum()
        recorte_semana = recorte[recorte[COLUNA_DATA_DIARIA] >= corte_semana_inicio]
        semanas_historicas[deslocamento] = recorte_semana.groupby("Cliente")["Receita"].sum()

    alertas: list[dict] = []
    avaliados: set[str] = set()
    for regra in regras_ativas:
        if ordinal_atual < int(regra.get("min_dias_uteis", 2)):
            continue
        tag_id = str(regra.get("tag_id") or "")
        clientes_tag = sorted(
            cliente for cliente in clientes_regras if tag_id in tags_por_cliente.get(cliente, [])
        )
        meses = int(regra.get("meses_historico", 6))
        # Não dilui a média com meses anteriores ao começo real da base.
        meses_com_cobertura = [
            indice for indice in range(1, meses + 1)
            if _mes_anterior(inicio_atual, indice) >= inicio_cobertura
        ]
        if len(meses_com_cobertura) < 2:
            continue
        for cliente in clientes_tag:
            granularidade = str(regra.get("granularidade") or "mensal")
            if granularidade == "diaria":
                serie_atual = dia_atual
                series_historicas = dias_historicos
            elif granularidade == "semanal":
                serie_atual = semana_atual
                series_historicas = semanas_historicas
            else:
                granularidade = "mensal"
                serie_atual = atual
                series_historicas = acumulados_historicos
            historico = [float(series_historicas[i].get(cliente, 0)) for i in meses_com_cobertura]
            esperado = sum(historico) / len(meses_com_cobertura)
            if esperado <= 0:
                continue
            avaliados.add(cliente)
            realizado = float(serie_atual.get(cliente, 0))
            diferenca = realizado - esperado
            variacao = diferenca / esperado * 100
            direcao = str(regra.get("direcao") or "queda")
            sentido = "queda" if variacao < 0 else "alta"
            atende_direcao = direcao == "ambos" or direcao == sentido
            if not atende_direcao:
                continue
            if abs(variacao) < float(regra.get("limite_percentual", 20)):
                continue
            if abs(diferenca) < float(regra.get("limite_valor", 0)):
                continue
            hist_semana = [float(semanas_historicas[i].get(cliente, 0)) for i in meses_com_cobertura]
            esperado_semana = sum(hist_semana) / len(meses_com_cobertura)
            realizado_semana = float(semana_atual.get(cliente, 0))
            hist_dia = [float(dias_historicos[i].get(cliente, 0)) for i in meses_com_cobertura]
            esperado_dia = sum(hist_dia) / len(meses_com_cobertura)
            realizado_dia = float(dia_atual.get(cliente, 0))
            hist_mes = [float(acumulados_historicos[i].get(cliente, 0)) for i in meses_com_cobertura]
            esperado_mes = sum(hist_mes) / len(meses_com_cobertura)
            realizado_mes = float(atual.get(cliente, 0))
            alertas.append({
                "id": f"{regra['id']}::{cliente}",
                "regra_id": regra["id"],
                "tag_id": tag_id,
                "cliente": cliente,
                "granularidade": granularidade,
                "sentido": sentido,
                "realizado": _numero(realizado),
                "esperado": _numero(esperado),
                "diferenca": _numero(diferenca),
                "variacao_percentual": _numero(variacao),
                "media_diaria_atual": _numero(realizado_mes / ordinal_atual),
                "media_diaria_esperada": _numero(esperado_mes / ordinal_atual),
                "dia_realizado": _numero(realizado_dia),
                "dia_esperado": _numero(esperado_dia),
                "semana_realizado": _numero(realizado_semana),
                "semana_esperado": _numero(esperado_semana),
                "mes_realizado": _numero(realizado_mes),
                "mes_esperado": _numero(esperado_mes),
            })

    alertas.sort(key=lambda item: abs(item["diferenca"]), reverse=True)
    return {
        "disponivel": True,
        "motivo": None,
        "data_referencia": referencia.strftime("%Y-%m-%d"),
        "dia_referencia": dia_referencia.strftime("%Y-%m-%d"),
        "semana_inicio": inicio_semana.strftime("%Y-%m-%d"),
        "semana_fim": fim_semana.strftime("%Y-%m-%d"),
        "dias_uteis_decorridos": ordinal_atual,
        "alertas": alertas,
        "resumo": {
            "ativos": len(alertas),
            "quedas": sum(item["sentido"] == "queda" for item in alertas),
            "altas": sum(item["sentido"] == "alta" for item in alertas),
            "clientes_avaliados": len(avaliados),
        },
    }
