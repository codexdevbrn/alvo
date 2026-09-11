"""Painel analítico da carteira de clientes.

Mesmo recorte das demais telas: mês de referência = último `Periodo_Mensal` da
base, comparado à média dos 6 meses anteriores (`periodo_mensal`).

Movimento da carteira usa uma única janela de inatividade
(`JANELA_INATIVIDADE_MESES`), e cada evento é contado **uma vez**:

| Evento | Regra |
|---|---|
| Novo | primeira compra da base cai no mês |
| Recuperado | comprou no mês depois de ficar a janela inteira parado |
| Perdido | comprou há exatamente uma janela e não comprou desde então |

Contar "perdido" como "estava ativo na janela e sumiu no mês" repetiria o mesmo
cliente em três meses seguidos — por isso a régua é a última compra, não a
presença na janela.

A curva ABC reaproveita `curva_pareto`/`faixa_por_curva` do motor com os cortes
do `config.json` da empresa: a tela não pode classificar por uma régua
diferente da do Analisador.

Cliente marcado com a tag de balcão fica **fora de todo o painel**. Consumidor
final costuma ser uma linha só, com receita de centenas de clientes: dentro da
curva ele afunda o Pareto, e dentro do movimento vira um "cliente" que nunca
entra nem sai. A contagem excluída volta em `balcao_excluidos` para o número
não sumir sem aviso.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from engine.analise_funil import curva_pareto, faixa_por_curva, nomes_faixas
from periodo_mensal import (
    COLUNA_DATA_DIARIA,
    converter_periodo,
    deslocar_mes,
    dia_corte_mes_aberto,
    filtrar_ate_o_dia,
    inicio_mes,
    modo_periodo_valido,
    numero,
    referencia_efetiva,
    rotulo_periodo,
    variacao,
)


MESES_HISTORICO = 6
JANELA_INATIVIDADE_MESES = 3
MESES_MOVIMENTO = 12
JANELA_ABC_MESES = 12
LIMITE_TOP_CLIENTES = 20
LIMITE_EVENTOS = 20
LIMITE_ALERTA_PCT = 20.0
CORTES_PADRAO = (30.0, 50.0, 60.0)
NOME_SEM_CLIENTE = "Não informado"


class ErroPainelClientes(ValueError):
    """Erro de dados que a API pode mostrar direto."""


def _arredondar(valor: float | None) -> float | None:
    return None if valor is None else round(valor, 2)


def _resposta_vazia(mensagem: str) -> dict:
    return {
        "disponivel": False,
        "mensagem": mensagem,
        "periodo_atual": None,
        "rotulo_periodo": None,
        "meses_media": 0,
        "periodo_media_inicio": None,
        "periodo_media_fim": None,
        "janela_inatividade_meses": JANELA_INATIVIDADE_MESES,
        "janela_abc_meses": JANELA_ABC_MESES,
        "balcao_excluidos": 0,
        "resumo": {
            "clientes_ativos": 0,
            "clientes_media": 0.0,
            "variacao_clientes": None,
            "receita_atual": 0.0,
            "receita_media": 0.0,
            "variacao_receita": None,
            "ticket_medio": 0.0,
            "ticket_medio_media": 0.0,
            "variacao_ticket": None,
            "novos": 0,
            "recuperados": 0,
            "perdidos": 0,
            "saldo": 0,
        },
        "concentracao": {
            "clientes": 0,
            "receita": 0.0,
            "clientes_80": 0,
            "participacao_clientes_80": 0.0,
            "faixas": [],
        },
        "movimento": [],
        "eventos": {"novos": [], "recuperados": [], "perdidos": []},
        "top_clientes": [],
        "tags": [],
    }


def _sem_balcao(dados: pd.DataFrame, clientes_balcao) -> tuple[pd.DataFrame, int]:
    """Remove os clientes de balcão e diz quantos saíram."""
    nomes = {
        str(nome).strip() for nome in (clientes_balcao or []) if str(nome).strip()
    }
    if not nomes:
        return dados, 0
    fora = dados["Cliente"].isin(nomes)
    return dados.loc[~fora], int(dados.loc[fora, "Cliente"].nunique())


def _normalizar_cliente(serie: pd.Series) -> pd.Series:
    textos = serie.fillna("").astype(str).str.strip()
    textos = textos.mask(textos.str.lower().isin(("nan", "none", "<na>")), "")
    return textos.replace("", NOME_SEM_CLIENTE)


def _preparar(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Timestamp]:
    if df is None or df.empty:
        raise ErroPainelClientes("A base está vazia.")
    faltantes = sorted({"Cliente", "Receita"} - set(df.columns))
    if faltantes:
        raise ErroPainelClientes("Base sem colunas necessárias: " + ", ".join(faltantes))

    colunas = [
        coluna for coluna in (
            "Cliente", "Receita", "QTD", "Periodo_Mensal", "Data_Venda", COLUNA_DATA_DIARIA,
        )
        if coluna in df.columns
    ]
    dados = df.loc[:, colunas].copy()
    dados["_periodo"] = converter_periodo(dados)
    cobertura = float(dados["_periodo"].notna().mean() * 100)
    if cobertura < 95:
        raise ErroPainelClientes(
            f"Período mensal incompleto: {cobertura:.1f}% das linhas possuem mês válido."
        )
    dados = dados.dropna(subset=["_periodo"])
    if dados.empty:
        raise ErroPainelClientes("A base não tem nenhum mês válido.")
    dados["Cliente"] = _normalizar_cliente(dados["Cliente"])
    dados["Receita"] = pd.to_numeric(dados["Receita"], errors="coerce").fillna(0.0)
    if "QTD" in dados.columns:
        dados["QTD"] = pd.to_numeric(dados["QTD"], errors="coerce").fillna(0.0)
    else:
        dados["QTD"] = 0.0
    return dados, inicio_mes(dados["_periodo"].max())


def _meses_ate(referencia: pd.Timestamp, quantidade: int) -> list[pd.Timestamp]:
    """Sequência de calendário terminando em `referencia`, do mais antigo ao mês."""
    return [deslocar_mes(referencia, -passo) for passo in range(quantidade - 1, -1, -1)]


def _presenca_por_mes(dados: pd.DataFrame) -> dict[pd.Timestamp, set[str]]:
    pares = dados.loc[:, ["Cliente", "_periodo"]].drop_duplicates()
    return {
        periodo: set(grupo["Cliente"].tolist())
        for periodo, grupo in pares.groupby("_periodo", sort=False)
    }


def _movimento_da_carteira(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
) -> tuple[list[dict], dict[str, set[str]]]:
    """Novos, recuperados e perdidos mês a mês (janela de inatividade fixa).

    Devolve também os nomes por evento do mês de referência — a tela lista quem
    entrou e quem saiu, e recalcular isso no navegador exigiria a base inteira.
    """
    presenca = _presenca_por_mes(dados)
    primeira_compra = dados.groupby("Cliente")["_periodo"].min()
    primeiro_mes_base = inicio_mes(dados["_periodo"].min())
    receita_por_mes = dados.groupby("_periodo")["Receita"].sum()
    janela = JANELA_INATIVIDADE_MESES

    linhas: list[dict] = []
    eventos: dict[str, set[str]] = {"novos": set(), "recuperados": set(), "perdidos": set()}
    for mes in _meses_ate(referencia, MESES_MOVIMENTO):
        if mes < primeiro_mes_base:
            continue
        ativos = presenca.get(mes, set())
        anteriores: set[str] = set()
        for passo in range(1, janela + 1):
            anteriores |= presenca.get(deslocar_mes(mes, -passo), set())

        e_primeiro_mes = mes == primeiro_mes_base
        novos = set() if e_primeiro_mes else {
            cliente for cliente in ativos if primeira_compra.get(cliente) == mes
        }
        recuperados = {
            cliente for cliente in ativos
            if cliente not in anteriores and cliente not in novos
        } if not e_primeiro_mes else set()

        # Perdido = comprou há exatamente uma janela e não voltou desde então.
        desde_o_corte: set[str] = set()
        for passo in range(0, janela):
            desde_o_corte |= presenca.get(deslocar_mes(mes, -passo), set())
        perdidos = presenca.get(deslocar_mes(mes, -janela), set()) - desde_o_corte
        if mes == referencia:
            eventos = {"novos": novos, "recuperados": recuperados, "perdidos": perdidos}

        linhas.append({
            "periodo": mes.strftime("%Y-%m"),
            "rotulo": rotulo_periodo(mes),
            "ativos": len(ativos),
            "novos": len(novos),
            "recuperados": len(recuperados),
            "perdidos": len(perdidos),
            "saldo": len(novos) + len(recuperados) - len(perdidos),
            "receita": round(numero(receita_por_mes.get(mes, 0.0)), 2),
        })
    return linhas, eventos


def _lista_eventos(
    dados: pd.DataFrame,
    nomes: set[str],
    referencia: pd.Timestamp,
    usar_ultima_compra: bool,
) -> list[dict]:
    """Nomes de um evento, do maior valor para o menor.

    `usar_ultima_compra` = perdido: o valor que interessa é o do último mês em
    que ele comprou, não o do mês de referência (onde ele é zero).
    """
    if not nomes:
        return []
    recorte = dados.loc[dados["Cliente"].isin(nomes)]
    if usar_ultima_compra:
        ultimo = recorte.groupby("Cliente")["_periodo"].max()
        chaves = list(zip(ultimo.index, ultimo.to_numpy()))
        por_mes = recorte.groupby(["Cliente", "_periodo"])["Receita"].sum()
        itens = [
            {
                "cliente": str(cliente),
                "receita": round(numero(por_mes.get((cliente, mes), 0.0)), 2),
                "ultimo_mes": rotulo_periodo(inicio_mes(pd.Timestamp(mes))),
            }
            for cliente, mes in chaves
        ]
    else:
        no_mes = recorte.loc[recorte["_periodo"] == referencia].groupby("Cliente")["Receita"].sum()
        itens = [
            {
                "cliente": str(cliente),
                "receita": round(numero(no_mes.get(cliente, 0.0)), 2),
                "ultimo_mes": None,
            }
            for cliente in nomes
        ]
    itens.sort(key=lambda item: item["receita"], reverse=True)
    return itens[:LIMITE_EVENTOS]


def _curva_abc(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
    cortes: tuple[float, ...],
) -> tuple[dict, pd.Series]:
    """Faixas da curva sobre a janela ABC; devolve o resumo e a receita por cliente."""
    meses = set(_meses_ate(referencia, JANELA_ABC_MESES))
    recorte = dados.loc[dados["_periodo"].isin(meses)]
    receita = recorte.groupby("Cliente")["Receita"].sum().sort_values(ascending=False)
    receita = receita[receita > 0]
    total = float(receita.sum())
    vazio = {
        "clientes": 0,
        "receita": 0.0,
        "clientes_80": 0,
        "participacao_clientes_80": 0.0,
        "faixas": [],
    }
    if receita.empty or total <= 0:
        return vazio, receita

    curva = curva_pareto(receita)
    faixa = faixa_por_curva(curva, cortes)
    acumulado = curva["Percentual_Acumulado"].to_numpy(dtype=float)
    clientes_80 = min(int(np.searchsorted(acumulado, 80.0, side="left")) + 1, len(acumulado))

    faixas = []
    for nome in nomes_faixas(cortes):
        recorte_faixa = curva.loc[faixa == nome]
        if recorte_faixa.empty:
            continue
        receita_faixa = float(recorte_faixa["Receita"].sum())
        faixas.append({
            "nome": nome,
            "clientes": int(len(recorte_faixa)),
            "receita": round(receita_faixa, 2),
            "participacao": round(receita_faixa / total * 100, 2),
        })

    return {
        "clientes": int(len(receita)),
        "receita": round(total, 2),
        "clientes_80": clientes_80,
        "participacao_clientes_80": round(clientes_80 / len(receita) * 100, 2),
        "faixas": faixas,
    }, receita


def _top_clientes(
    dados: pd.DataFrame,
    referencia: pd.Timestamp,
    historico: list[pd.Timestamp],
    dia_corte: int | None = None,
) -> list[dict]:
    """Maiores clientes do mês contra a média do histórico, como o ranking de vendedores."""
    divisor = max(len(historico), 1)
    atual = dados.loc[dados["_periodo"] == referencia]
    hist = filtrar_ate_o_dia(dados.loc[dados["_periodo"].isin(historico)], dia_corte)
    receita_atual = atual.groupby("Cliente")["Receita"].sum()
    qtd_atual = atual.groupby("Cliente")["QTD"].sum()
    receita_hist = hist.groupby("Cliente")["Receita"].sum() / divisor

    itens = []
    for nome in receita_atual.sort_values(ascending=False).head(LIMITE_TOP_CLIENTES).index:
        valor_atual = numero(receita_atual.get(nome, 0.0))
        valor_media = numero(receita_hist.get(nome, 0.0))
        var = variacao(valor_atual, valor_media)
        itens.append({
            "cliente": str(nome),
            "receita_atual": round(valor_atual, 2),
            "receita_media": round(valor_media, 2),
            "variacao": _arredondar(var),
            "qtd_atual": round(numero(qtd_atual.get(nome, 0.0)), 2),
            "alerta": var is not None and var <= -LIMITE_ALERTA_PCT,
        })
    return itens


def _resumo_por_tag(
    tags: dict | None,
    catalogo: list | None,
    receita_por_cliente: pd.Series,
    receita_total: float,
) -> list[dict]:
    """Contagem e receita (janela ABC) de cada tag ativa do catálogo."""
    if not catalogo:
        return []
    por_tag: dict[str, list[str]] = {}
    for cliente, marcadas in (tags or {}).items():
        nome = str(cliente or "").strip()
        if not nome:
            continue
        for tag in marcadas or []:
            por_tag.setdefault(str(tag), []).append(nome)

    linhas = []
    for item in catalogo:
        if not isinstance(item, dict) or not item.get("ativa"):
            continue
        tag_id = str(item.get("id") or "").strip()
        if not tag_id:
            continue
        clientes = por_tag.get(tag_id, [])
        receita = float(sum(numero(receita_por_cliente.get(nome, 0.0)) for nome in clientes))
        linhas.append({
            "id": tag_id,
            "rotulo": str(item.get("rotulo") or tag_id),
            "cor": item.get("cor"),
            "clientes": len(clientes),
            "receita": round(receita, 2),
            "participacao": round(receita / receita_total * 100, 2) if receita_total > 0 else 0.0,
        })
    linhas.sort(key=lambda linha: (linha["receita"], linha["clientes"]), reverse=True)
    return linhas


def _cortes_validos(cortes) -> tuple[float, ...]:
    """Cortes crescentes entre 0 e 100; qualquer coisa fora disso vira o padrão."""
    try:
        valores = tuple(float(valor) for valor in cortes)
    except (TypeError, ValueError):
        return CORTES_PADRAO
    if not valores or any(not 0 < valor <= 100 for valor in valores):
        return CORTES_PADRAO
    if list(valores) != sorted(valores):
        return CORTES_PADRAO
    return valores


def montar_painel_clientes(
    df: pd.DataFrame | None,
    tags: dict | None = None,
    catalogo: list | None = None,
    cortes=None,
    clientes_balcao=None,
    modo_periodo: str = "fechados",
) -> dict:
    """Visão geral da carteira: KPIs, curva ABC, movimento mensal, top e tags."""
    modo_periodo = modo_periodo_valido(modo_periodo)
    usar_mes_fechado = modo_periodo == "fechados"
    try:
        dados, referencia = _preparar(df)
    except ErroPainelClientes as exc:
        return _resposta_vazia(str(exc))

    dados, balcao_excluidos = _sem_balcao(dados, clientes_balcao)
    if dados.empty:
        return _resposta_vazia("Todos os clientes da base estão marcados como balcão.")
    referencia = inicio_mes(dados["_periodo"].max())
    referencia = referencia_efetiva(referencia, usar_mes_fechado)

    primeiro_mes_base = inicio_mes(dados["_periodo"].min())
    historico = [
        mes for mes in _meses_ate(deslocar_mes(referencia, -1), MESES_HISTORICO)
        if mes >= primeiro_mes_base
    ]
    divisor = max(len(historico), 1)

    atual = dados.loc[dados["_periodo"] == referencia]
    hist = dados.loc[dados["_periodo"].isin(historico)]
    dia_corte = None
    if modo_periodo == "mesmo_periodo":
        dia_corte = dia_corte_mes_aberto(atual.get(COLUNA_DATA_DIARIA))
        hist = filtrar_ate_o_dia(hist, dia_corte)
    receita_atual = round(float(atual["Receita"].sum()), 2)
    receita_media = round(float(hist["Receita"].sum()) / divisor, 2)
    clientes_ativos = int(atual["Cliente"].nunique())
    clientes_media = (
        float(hist.groupby("_periodo")["Cliente"].nunique().sum()) / divisor
        if not hist.empty else 0.0
    )
    ticket_medio = receita_atual / clientes_ativos if clientes_ativos else 0.0
    ticket_medio_media = receita_media / clientes_media if clientes_media else 0.0

    movimento, eventos = _movimento_da_carteira(dados, referencia)
    ultimo = movimento[-1] if movimento else {
        "novos": 0, "recuperados": 0, "perdidos": 0, "saldo": 0,
    }
    concentracao, receita_por_cliente = _curva_abc(dados, referencia, _cortes_validos(cortes))

    return {
        "disponivel": True,
        "mensagem": None,
        "periodo_atual": referencia.strftime("%Y-%m"),
        "rotulo_periodo": rotulo_periodo(referencia),
        "meses_media": len(historico),
        "periodo_media_inicio": historico[0].strftime("%Y-%m") if historico else None,
        "periodo_media_fim": historico[-1].strftime("%Y-%m") if historico else None,
        "janela_inatividade_meses": JANELA_INATIVIDADE_MESES,
        "janela_abc_meses": JANELA_ABC_MESES,
        "balcao_excluidos": balcao_excluidos,
        "resumo": {
            "clientes_ativos": clientes_ativos,
            "clientes_media": round(clientes_media, 1),
            "variacao_clientes": _arredondar(variacao(clientes_ativos, clientes_media)),
            "receita_atual": receita_atual,
            "receita_media": receita_media,
            "variacao_receita": _arredondar(variacao(receita_atual, receita_media)),
            "ticket_medio": round(ticket_medio, 2),
            "ticket_medio_media": round(ticket_medio_media, 2),
            "variacao_ticket": _arredondar(variacao(ticket_medio, ticket_medio_media)),
            "novos": ultimo["novos"],
            "recuperados": ultimo["recuperados"],
            "perdidos": ultimo["perdidos"],
            "saldo": ultimo["saldo"],
        },
        "concentracao": concentracao,
        "movimento": movimento,
        "eventos": {
            "novos": _lista_eventos(dados, eventos["novos"], referencia, False),
            "recuperados": _lista_eventos(dados, eventos["recuperados"], referencia, False),
            "perdidos": _lista_eventos(dados, eventos["perdidos"], referencia, True),
        },
        "top_clientes": _top_clientes(dados, referencia, historico, dia_corte),
        "tags": _resumo_por_tag(
            tags, catalogo, receita_por_cliente, float(concentracao["receita"]),
        ),
    }
