"""Cálculos do mapa Estoque × velocidade de venda.

O módulo recebe as duas tabelas já normalizadas da Liquidez e devolve somente
dados JSON-safe. Mantê-lo separado da rota facilita testar as regras sem acessar
arquivos da fonte e evita duplicar o tratamento de estoque/vendas no frontend.
"""

from __future__ import annotations

import unicodedata
from typing import Any

import pandas as pd


COLUNA_PRODUTO = "CODIGO_INTERNO_PRODUTO"
MESES_NUMERO = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _primeiro_texto(serie: pd.Series, fallback: str = "") -> str:
    """Primeiro texto não vazio de um grupo, com fallback estável."""
    for valor in serie:
        texto = str(valor or "").strip()
        if texto and texto.lower() != "nan":
            return texto
    return fallback


def _periodo_rotulo(indice: int) -> str:
    ano = indice // 12
    mes = indice % 12 + 1
    return f"{ano:04d}-{mes:02d}"


def _numero(valor: Any, casas: int = 4) -> float:
    numero = float(valor or 0)
    return round(numero, casas)


def _mes_como_numero(valor: Any) -> float | int:
    """Aceita mês numérico ou por extenso, com ou sem acento."""
    try:
        numero = float(valor)
        if numero.is_integer() and 1 <= numero <= 12:
            return int(numero)
    except (TypeError, ValueError):
        pass
    texto = unicodedata.normalize("NFKD", str(valor or "").strip().casefold())
    texto = "".join(caractere for caractere in texto if not unicodedata.combining(caractere))
    return MESES_NUMERO.get(texto, float("nan"))


def montar_cobertura_estoque(
    estoque: pd.DataFrame,
    vendas: pd.DataFrame,
    *,
    meses: int = 6,
    limite: int = 800,
    cobertura_alvo: float = 3.0,
    cobertura_excesso: float = 6.0,
    cobertura_ruptura: float = 0.5,
) -> dict:
    """Combina estoque atual com venda média mensal por produto.

    Venda média usa janela corrida encerrada no último mês disponível na base;
    meses sem movimento contam como zero. Valor do estoque usa último custo,
    depois CMV e, por fim, preço médio de venda como fallback.
    """
    meses = max(1, min(int(meses), 24))
    limite = max(1, min(int(limite), 2000))

    if estoque is None or estoque.empty:
        return {
            "periodo_inicio": None,
            "periodo_fim": None,
            "meses": meses,
            "itens": [],
            "resumo": {
                "produtos": 0,
                "valor_estoque": 0.0,
                "ruptura": 0,
                "excesso": 0,
                "sem_giro": 0,
            },
        }

    est = estoque.copy()
    for coluna in (
        "Qtd_estoque",
        "Preço_médio_de_venda",
        "Preço_médio_cmv",
        "Último_custo",
    ):
        est[coluna] = pd.to_numeric(est.get(coluna, 0), errors="coerce").fillna(0.0)

    est[COLUNA_PRODUTO] = est.get(COLUNA_PRODUTO, "").fillna("").astype(str).str.strip()
    est = est[est[COLUNA_PRODUTO] != ""].copy()
    custo = est["Último_custo"].where(est["Último_custo"] > 0, est["Preço_médio_cmv"])
    custo = custo.where(custo > 0, est["Preço_médio_de_venda"])
    est["_valor_estoque"] = est["Qtd_estoque"].clip(lower=0) * custo.clip(lower=0)

    agrupado_estoque = (
        est.groupby(COLUNA_PRODUTO, as_index=False, dropna=False)
        .agg(
            sku=("CODIGO_REFERENCIA_PRODUTO", _primeiro_texto),
            nome=("descricao", _primeiro_texto),
            fabricante=("NOME_FABRICANTE", _primeiro_texto),
            estoque=("Qtd_estoque", "sum"),
            valor_estoque=("_valor_estoque", "sum"),
        )
    )

    vendas_produto = pd.DataFrame(columns=[COLUNA_PRODUTO, "venda_media", "variacao_pct"])
    periodo_inicio = None
    periodo_fim = None
    if vendas is not None and not vendas.empty:
        ven = vendas.copy()
        ven[COLUNA_PRODUTO] = ven.get(COLUNA_PRODUTO, "").fillna("").astype(str).str.strip()
        ven["Ano"] = pd.to_numeric(ven.get("Ano"), errors="coerce")
        meses_origem = ven.get("Mês", pd.Series(index=ven.index, dtype=object))
        ven["Mês"] = meses_origem.map(_mes_como_numero)
        ven["QTD"] = pd.to_numeric(ven.get("QTD", 0), errors="coerce").fillna(0.0)
        ven = ven.dropna(subset=["Ano", "Mês"])
        ven = ven[(ven[COLUNA_PRODUTO] != "") & ven["Mês"].between(1, 12)].copy()

        if not ven.empty:
            ven["_periodo"] = ven["Ano"].astype(int) * 12 + ven["Mês"].astype(int) - 1
            fim = int(ven["_periodo"].max())
            inicio = fim - meses + 1
            periodo_inicio = _periodo_rotulo(inicio)
            periodo_fim = _periodo_rotulo(fim)

            janela = ven[ven["_periodo"].between(inicio, fim)]
            totais = janela.groupby(COLUNA_PRODUTO)["QTD"].sum().rename("_qtd_janela")

            # Tendência curta para tooltip/status: últimos 3 meses contra os 3
            # anteriores. Quando a base anterior é zero, percentual fica nulo.
            largura_tendencia = min(3, max(1, meses // 2))
            inicio_recente = fim - largura_tendencia + 1
            inicio_anterior = inicio_recente - largura_tendencia
            recente = (
                ven[ven["_periodo"].between(inicio_recente, fim)]
                .groupby(COLUNA_PRODUTO)["QTD"].sum()
                .rename("_qtd_recente")
            )
            anterior = (
                ven[ven["_periodo"].between(inicio_anterior, inicio_recente - 1)]
                .groupby(COLUNA_PRODUTO)["QTD"].sum()
                .rename("_qtd_anterior")
            )
            vendas_produto = pd.concat([totais, recente, anterior], axis=1).fillna(0).reset_index()
            vendas_produto["venda_media"] = vendas_produto["_qtd_janela"] / meses
            base_anterior = vendas_produto["_qtd_anterior"]
            vendas_produto["variacao_pct"] = (
                (vendas_produto["_qtd_recente"] - base_anterior) / base_anterior * 100
            ).where(base_anterior > 0)

    combinado = agrupado_estoque.merge(vendas_produto, on=COLUNA_PRODUTO, how="left")
    combinado["venda_media"] = pd.to_numeric(combinado.get("venda_media"), errors="coerce").fillna(0.0)
    combinado["variacao_pct"] = pd.to_numeric(combinado.get("variacao_pct"), errors="coerce")
    combinado["cobertura"] = combinado["estoque"] / combinado["venda_media"].where(
        combinado["venda_media"] > 0
    )

    def classificar(linha: pd.Series) -> str:
        estoque_atual = float(linha["estoque"])
        venda_media = float(linha["venda_media"])
        cobertura = linha["cobertura"]
        variacao = linha["variacao_pct"]
        if estoque_atual < 0:
            return "negative"
        if estoque_atual == 0:
            return "out_of_stock"
        if venda_media <= 0 or pd.isna(cobertura):
            return "no_sales"
        if cobertura < cobertura_ruptura:
            return "rupture"
        if cobertura > cobertura_excesso:
            return "excess"
        if pd.notna(variacao) and variacao <= -30 and cobertura > cobertura_alvo:
            return "stalled"
        return "normal"

    combinado["status"] = combinado.apply(classificar, axis=1)
    resumo = {
        "produtos": int(len(combinado)),
        "valor_estoque": _numero(combinado["valor_estoque"].sum(), 2),
        "ruptura": int(combinado["status"].isin(["rupture", "out_of_stock", "negative"]).sum()),
        "excesso": int(combinado["status"].isin(["excess", "stalled"]).sum()),
        "sem_giro": int((combinado["status"] == "no_sales").sum()),
    }

    combinado = combinado.sort_values(
        ["valor_estoque", "venda_media"], ascending=[False, False], kind="stable"
    ).head(limite)
    itens = []
    for linha in combinado.to_dict(orient="records"):
        cobertura = linha.get("cobertura")
        variacao = linha.get("variacao_pct")
        itens.append({
            "sku": linha.get("sku") or linha[COLUNA_PRODUTO],
            "codigo_interno": linha[COLUNA_PRODUTO],
            "nome": linha.get("nome") or "Produto sem descrição",
            "fabricante": linha.get("fabricante") or "Sem fabricante",
            "estoque": _numero(linha.get("estoque"), 2),
            "venda_media": _numero(linha.get("venda_media"), 4),
            "cobertura": None if pd.isna(cobertura) else _numero(cobertura, 4),
            "valor_estoque": _numero(linha.get("valor_estoque"), 2),
            "variacao_pct": None if pd.isna(variacao) else _numero(variacao, 2),
            "status": linha["status"],
        })

    return {
        "periodo_inicio": periodo_inicio,
        "periodo_fim": periodo_fim,
        "meses": meses,
        "itens": itens,
        "resumo": resumo,
    }
