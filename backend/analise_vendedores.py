"""Ranking e ficha de vendedores.

Recorte igual ao painel de cliente: mês de referência = último Periodo_Mensal
da base inteira, comparado à média dos 6 meses anteriores. Vendedor sem venda
no mês atual entra com zero — o recorte não recua para a última venda dele.

A coluna canônica é opcional (`Vendedor`). Sem ela a tela responde
`disponivel: false` em vez de falhar.
"""

from __future__ import annotations

import zlib

import numpy as np
import pandas as pd

from periodo_mensal import (
    COLUNA_DATA_DIARIA,
    COLUNA_PERIODO,
    MESES_ABREV,
    converter_periodo as _converter_periodo,
    deslocar_mes as _deslocar_mes,
    dia_corte_mes_aberto as _dia_corte_mes_aberto,
    filtrar_ate_o_dia as _filtrar_ate_o_dia,
    inicio_mes as _inicio_mes,
    modo_periodo_valido as _modo_periodo_valido,
    numero as _numero,
    referencia_efetiva as _referencia_efetiva,
    rotulo_periodo as _rotulo_periodo,
    variacao as _variacao,
)

COLUNA_VENDEDOR = "Vendedor"
NOME_SEM_VENDEDOR = "Sem vendedor"
MESES_HISTORICO = 6
LIMITE_ALERTA_PCT = 20.0
LIMITE_FICHA = 80
LIMITE_ALERTAS = 10
VENDEDORES_DEMO = ("Ana Souza", "Bruno Lima", "Carla Dias")


class ErroFichaVendedor(ValueError):
    """Erro de dados que a API pode mostrar direto."""


def tem_coluna_vendedor(df: pd.DataFrame | None) -> bool:
    return df is not None and COLUNA_VENDEDOR in df.columns


def coluna_vendedor_preenchida(df: pd.DataFrame | None) -> bool:
    if not tem_coluna_vendedor(df) or df is None or df.empty:
        return False
    textos = df[COLUNA_VENDEDOR].fillna("").astype(str).str.strip()
    textos = textos.mask(textos.str.lower().isin(("nan", "none", "<na>")), "")
    return bool(textos.ne("").any())


def preencher_vendedores_demo(df: pd.DataFrame) -> pd.DataFrame:
    """Atribui três vendedores fictícios estáveis por cliente.

    Só para a empresa de demonstração, quando a fonte ainda não tem a coluna.
    Consumidor final fica sem vendedor — vira o balde Sem vendedor no ranking.
    """
    if df is None or df.empty or "Cliente" not in df.columns:
        return df
    saida = df.copy()
    nomes = saida["Cliente"].fillna("").astype(str).str.strip()
    marca = (
        nomes.str.normalize("NFKD")
        .str.encode("ascii", "ignore")
        .str.decode("ascii")
        .str.casefold()
    )
    e_consumidor = marca.str.contains("consumidor", na=False)
    indices = nomes.map(lambda nome: zlib.crc32(nome.encode("utf-8")) % len(VENDEDORES_DEMO))
    saida[COLUNA_VENDEDOR] = np.where(e_consumidor, "", np.take(VENDEDORES_DEMO, indices))
    return saida


def _normalizar_vendedor(serie: pd.Series) -> pd.Series:
    textos = serie.fillna("").astype(str).str.strip()
    textos = textos.mask(textos.str.lower().isin(("nan", "none", "<na>")), "")
    return textos.replace("", NOME_SEM_VENDEDOR)


def _resposta_vazia(mensagem: str) -> dict:
    return {
        "disponivel": False,
        "mensagem": mensagem,
        "periodo_atual": None,
        "rotulo_periodo": None,
        "meses_media": 0,
        "periodo_media_inicio": None,
        "periodo_media_fim": None,
        "itens": [],
        "resumo": {
            "vendedores": 0,
            "receita_atual": 0.0,
            "maior_alta": None,
            "maior_queda": None,
        },
    }


def _preparar(
    df: pd.DataFrame, usar_mes_fechado: bool = True,
) -> tuple[pd.DataFrame, pd.Timestamp, list[pd.Timestamp]]:
    if df is None or df.empty:
        raise ErroFichaVendedor("A base está vazia.")
    if not tem_coluna_vendedor(df):
        raise ErroFichaVendedor("A base ainda não tem a coluna de vendedor.")
    obrigatorias = {"Receita", "QTD", "Cliente"}
    faltantes = sorted(obrigatorias - set(df.columns))
    if faltantes:
        raise ErroFichaVendedor("Base sem colunas necessárias: " + ", ".join(faltantes))

    colunas = [
        coluna for coluna in (
            COLUNA_VENDEDOR, "Cliente", "Receita", "QTD", "descricao",
            "NOME_FABRICANTE", COLUNA_PERIODO, "Data_Venda", COLUNA_DATA_DIARIA,
        ) if coluna in df.columns
    ]
    dados = df.loc[:, colunas].copy()
    dados["_periodo"] = _converter_periodo(dados)
    cobertura = float(dados["_periodo"].notna().mean() * 100)
    if cobertura < 95:
        raise ErroFichaVendedor(
            f"Período mensal incompleto: {cobertura:.1f}% das linhas possuem mês válido."
        )
    dados = dados.dropna(subset=["_periodo"])
    dados[COLUNA_VENDEDOR] = _normalizar_vendedor(dados[COLUNA_VENDEDOR])
    dados["Cliente"] = dados["Cliente"].fillna("").astype(str).str.strip()
    dados["Receita"] = pd.to_numeric(dados["Receita"], errors="coerce").fillna(0.0)
    dados["QTD"] = pd.to_numeric(dados["QTD"], errors="coerce").fillna(0.0)
    if "descricao" in dados.columns:
        dados["descricao"] = (
            dados["descricao"].fillna("Não informado").astype(str).str.strip()
            .replace("", "Não informado")
        )
    if "NOME_FABRICANTE" in dados.columns:
        dados["NOME_FABRICANTE"] = (
            dados["NOME_FABRICANTE"].fillna("Não informado").astype(str).str.strip()
            .replace("", "Não informado")
        )

    referencia = _inicio_mes(dados["_periodo"].max())
    referencia = _referencia_efetiva(referencia, usar_mes_fechado)
    inicio_minimo = _inicio_mes(dados["_periodo"].min())
    historico = [
        _deslocar_mes(referencia, -deslocamento)
        for deslocamento in range(1, MESES_HISTORICO + 1)
        if _deslocar_mes(referencia, -deslocamento) >= inicio_minimo
    ]
    historico.sort()
    return dados, referencia, historico


def _agregar(frame: pd.DataFrame, chave: str) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[chave, "receita", "qtd", "clientes"])
    return (
        frame.groupby(chave, dropna=False, as_index=False)
        .agg(receita=("Receita", "sum"), qtd=("QTD", "sum"), clientes=("Cliente", "nunique"))
    )


def _item_comparado(
    nome: str,
    atual: pd.Series | None,
    media_receita: float,
    media_qtd: float,
    media_clientes: float,
) -> dict:
    receita_atual = _numero(0 if atual is None else atual.get("receita"))
    qtd_atual = _numero(0 if atual is None else atual.get("qtd"))
    clientes_atual = int(_numero(0 if atual is None else atual.get("clientes")))
    variacao = _variacao(receita_atual, media_receita)
    return {
        "nome": nome,
        "receita_atual": round(receita_atual, 2),
        "receita_media": round(media_receita, 2),
        "variacao": None if variacao is None else round(variacao, 2),
        "qtd_atual": round(qtd_atual, 2),
        "clientes_atual": clientes_atual,
        "alerta": variacao is not None and variacao <= -LIMITE_ALERTA_PCT,
    }


def _comparar_entidades(
    atual_df: pd.DataFrame,
    hist_df: pd.DataFrame,
    chave: str,
    meses_media: int,
    limite: int | None = None,
) -> list[dict]:
    atual = _agregar(atual_df, chave).set_index(chave)
    hist = _agregar(hist_df, chave).set_index(chave)
    nomes = sorted(set(atual.index.astype(str)) | set(hist.index.astype(str)))
    divisor = max(meses_media, 1)
    itens = []
    for nome in nomes:
        linha_atual = atual.loc[nome] if nome in atual.index else None
        linha_hist = hist.loc[nome] if nome in hist.index else None
        receita_hist = _numero(0 if linha_hist is None else linha_hist.get("receita"))
        qtd_hist = _numero(0 if linha_hist is None else linha_hist.get("qtd"))
        clientes_hist = _numero(0 if linha_hist is None else linha_hist.get("clientes"))
        item = _item_comparado(
            nome,
            linha_atual,
            receita_hist / divisor,
            qtd_hist / divisor,
            clientes_hist / divisor,
        )
        if item["receita_atual"] == 0 and item["receita_media"] == 0:
            continue
        itens.append(item)
    itens.sort(
        key=lambda item: (item["receita_atual"], item["receita_media"]),
        reverse=True,
    )
    if limite is not None:
        return itens[:limite]
    return itens


def montar_ranking_vendedores(
    df: pd.DataFrame | None, modo_periodo: str = "fechados",
) -> dict:
    modo_periodo = _modo_periodo_valido(modo_periodo)
    if not tem_coluna_vendedor(df):
        return _resposta_vazia(
            "A base desta empresa ainda não tem a coluna de vendedor."
        )
    try:
        dados, referencia, historico = _preparar(df, modo_periodo == "fechados")
    except ErroFichaVendedor as exc:
        return _resposta_vazia(str(exc))

    atual_df = dados.loc[dados["_periodo"] == referencia]
    hist_df = dados.loc[dados["_periodo"].isin(historico)]
    if modo_periodo == "mesmo_periodo":
        dia_corte = _dia_corte_mes_aberto(atual_df.get(COLUNA_DATA_DIARIA))
        hist_df = _filtrar_ate_o_dia(hist_df, dia_corte)
    meses_media = len(historico)
    itens = _comparar_entidades(atual_df, hist_df, COLUNA_VENDEDOR, meses_media)
    for item in itens:
        item["vendedor"] = item.pop("nome")

    com_variacao = [item for item in itens if item["variacao"] is not None]
    maior_alta = max(com_variacao, key=lambda item: item["variacao"]) if com_variacao else None
    maior_queda = min(com_variacao, key=lambda item: item["variacao"]) if com_variacao else None
    if maior_alta and maior_alta["variacao"] <= 0:
        maior_alta = None
    if maior_queda and maior_queda["variacao"] >= 0:
        maior_queda = None

    return {
        "disponivel": True,
        "mensagem": None,
        "periodo_atual": referencia.strftime("%Y-%m"),
        "rotulo_periodo": _rotulo_periodo(referencia),
        "meses_media": meses_media,
        "periodo_media_inicio": historico[0].strftime("%Y-%m") if historico else None,
        "periodo_media_fim": historico[-1].strftime("%Y-%m") if historico else None,
        "itens": itens,
        "resumo": {
            "vendedores": len(itens),
            "receita_atual": round(sum(item["receita_atual"] for item in itens), 2),
            "maior_alta": None if maior_alta is None else {
                "vendedor": maior_alta["vendedor"],
                "variacao": maior_alta["variacao"],
            },
            "maior_queda": None if maior_queda is None else {
                "vendedor": maior_queda["vendedor"],
                "variacao": maior_queda["variacao"],
            },
        },
    }


def montar_ficha_vendedor(
    df: pd.DataFrame | None, vendedor: str, modo_periodo: str = "fechados",
) -> dict:
    modo_periodo = _modo_periodo_valido(modo_periodo)
    nome = str(vendedor or "").strip()
    if not nome:
        raise ErroFichaVendedor("Informe o vendedor.")
    if not tem_coluna_vendedor(df):
        raise ErroFichaVendedor("A base desta empresa ainda não tem a coluna de vendedor.")

    dados, referencia, historico = _preparar(df, modo_periodo == "fechados")
    if nome not in set(dados[COLUNA_VENDEDOR].unique().tolist()):
        raise ErroFichaVendedor(f"Vendedor '{nome}' não encontrado na base.")

    recorte = dados.loc[dados[COLUNA_VENDEDOR] == nome]
    atual_df = recorte.loc[recorte["_periodo"] == referencia]
    hist_df = recorte.loc[recorte["_periodo"].isin(historico)]
    if modo_periodo == "mesmo_periodo":
        dia_corte = _dia_corte_mes_aberto(atual_df.get(COLUNA_DATA_DIARIA))
        hist_df = _filtrar_ate_o_dia(hist_df, dia_corte)
    meses_media = len(historico)
    divisor = max(meses_media, 1)

    receita_atual = round(float(atual_df["Receita"].sum()), 2)
    receita_media = round(float(hist_df["Receita"].sum()) / divisor, 2)
    qtd_atual = round(float(atual_df["QTD"].sum()), 2)
    clientes_atual = int(atual_df["Cliente"].nunique()) if not atual_df.empty else 0
    variacao = _variacao(receita_atual, receita_media)

    clientes = _comparar_entidades(atual_df, hist_df, "Cliente", meses_media, LIMITE_FICHA)
    for item in clientes:
        item["cliente"] = item.pop("nome")

    produtos: list[dict] = []
    if "descricao" in recorte.columns:
        produtos = _comparar_entidades(atual_df, hist_df, "descricao", meses_media, LIMITE_FICHA)
        for item in produtos:
            item["produto"] = item.pop("nome")

    fabricantes: list[dict] = []
    if "NOME_FABRICANTE" in recorte.columns:
        fabricantes = _comparar_entidades(
            atual_df, hist_df, "NOME_FABRICANTE", meses_media, LIMITE_FICHA,
        )
        for item in fabricantes:
            item["fabricante"] = item.pop("nome")

    alertas_clientes = [item for item in clientes if item["alerta"]]
    alertas_produtos = [item for item in produtos if item["alerta"]]
    alertas_clientes.sort(key=lambda item: item["receita_media"] - item["receita_atual"], reverse=True)
    alertas_produtos.sort(key=lambda item: item["receita_media"] - item["receita_atual"], reverse=True)

    return {
        "disponivel": True,
        "vendedor": nome,
        "periodo_atual": referencia.strftime("%Y-%m"),
        "rotulo_periodo": _rotulo_periodo(referencia),
        "meses_media": meses_media,
        "periodo_media_inicio": historico[0].strftime("%Y-%m") if historico else None,
        "periodo_media_fim": historico[-1].strftime("%Y-%m") if historico else None,
        "receita_atual": receita_atual,
        "receita_media": receita_media,
        "variacao": None if variacao is None else round(variacao, 2),
        "qtd_atual": qtd_atual,
        "clientes_atual": clientes_atual,
        "clientes": clientes,
        "produtos": produtos,
        "fabricantes": fabricantes,
        "alertas": {
            "clientes": alertas_clientes[:LIMITE_ALERTAS],
            "produtos": alertas_produtos[:LIMITE_ALERTAS],
            "clientes_total": len(alertas_clientes),
            "produtos_total": len(alertas_produtos),
        },
    }
