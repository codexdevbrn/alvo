"""Cálculos da tela de Despesas (Controladoria).

Fonte é um CSV por empresa, independente de movimento/produto: uma linha por
lançamento (loja, categoria, competência, valor). Sem join e sem estoque — só
agrupar por mês/categoria/loja. Módulo separado da rota pelo mesmo motivo do
estoque (`estoque_cobertura.py`): testar a regra sem tocar arquivo da fonte.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd

from engine.analise_funil import curva_pareto, faixa_por_curva, nomes_faixas

MESES_ABREV = (
    "jan", "fev", "mar", "abr", "mai", "jun",
    "jul", "ago", "set", "out", "nov", "dez",
)

# Mesma régua usada em Clientes/Produtos (`analise_clientes.CORTES_PADRAO`) —
# reaproveitada aqui para classificar categorias de despesa em Grupo 1/2/3/Demais,
# em vez de inventar uma escala A/B/C só para esta tela.
CORTES_ABC_CATEGORIAS = (30.0, 50.0, 60.0)

# Categorias no gráfico empilhado mês a mês. Poucas o bastante para caber na
# legenda sem virar sopa de cores; o resto entra em "Outras".
LIMITE_SERIE_MENSAL_CATEGORIAS = 6


def _numero(valor: Any, casas: int = 2) -> float:
    numero = float(valor or 0)
    return round(numero, casas)

def _opcional(valor: Any, casas: int = 2) -> float | None:
    if valor is None or pd.isna(valor):
        return None
    return round(float(valor), casas)


def _periodo_rotulo(indice: int) -> str:
    ano = indice // 12
    mes = indice % 12 + 1
    return f"{ano:04d}-{mes:02d}"


def _rotulo_curto(indice: int) -> str:
    ano = indice // 12
    mes = indice % 12
    return f"{MESES_ABREV[mes]}/{ano % 100:02d}"


def _mes_atual_indice(ref: date | None = None) -> int:
    """Mesma codificação (Ano*12 + Mês - 1) usada pelo mapa de Estoque."""
    hoje = ref or date.today()
    return hoje.year * 12 + hoje.month - 1


def _preparar(df: pd.DataFrame) -> pd.DataFrame:
    dados = df.copy()
    dados["Ano"] = pd.to_numeric(dados.get("Ano"), errors="coerce")
    dados["Mês"] = pd.to_numeric(dados.get("Mês"), errors="coerce")
    dados["Valor"] = pd.to_numeric(dados.get("Valor"), errors="coerce").fillna(0.0)
    dados["categoria"] = dados.get("categoria", "").fillna("").astype(str).str.strip()
    dados["categoria"] = dados["categoria"].mask(dados["categoria"] == "", "Sem categoria")
    if "Loja" in dados.columns:
        dados["Loja"] = dados["Loja"].fillna("").astype(str).str.strip()
        dados["Loja"] = dados["Loja"].mask(dados["Loja"] == "", "Sem loja")
    dados = dados.dropna(subset=["Ano", "Mês"])
    return dados[dados["Mês"].between(1, 12)]


def _resposta_vazia(meses: int) -> dict:
    return {
        "periodo_inicio": None,
        "periodo_fim": None,
        "meses": meses,
        "resumo": {
            "total": 0.0,
            "media_mensal": 0.0,
            "mes_atual": 0.0,
            "mes_anterior": 0.0,
            "variacao_pct": None,
            "mes_mesmo_periodo_ano_anterior": None,
            "variacao_anual_pct": None,
        },
        "serie_mensal": [],
        "serie_mensal_categorias": {"categorias": [], "pontos": []},
        "por_categoria": [],
        "por_loja": [],
        "curva_abc_categorias": {"cortes": list(CORTES_ABC_CATEGORIAS), "grupos": []},
    }


def _serie_mensal_por_categoria(
    janela: pd.DataFrame,
    principais: list[str],
    tem_outras: bool,
    periodos: list[int],
) -> dict:
    """Composição mês a mês das categorias principais, para o gráfico empilhado.

    `principais` já vem ordenado pelo total no período; o resto (se houver)
    some numa única série "Outras" — mais categorias que isso vira legenda
    ilegível sem ganhar leitura. `periodos` são só os meses com lançamento
    (o mesmo eixo da série total): mês vazio ou futuro não entra.
    """
    if not periodos:
        return {"categorias": [], "pontos": []}
    pivot = janela.groupby(["_periodo", "categoria"])["Valor"].sum().unstack(fill_value=0.0)
    pivot = pivot.reindex(periodos, fill_value=0.0)
    categorias_legenda = principais + (["Outras"] if tem_outras else [])

    pontos = []
    for indice in periodos:
        linha = pivot.loc[indice]
        valores = {categoria: _numero(float(linha.get(categoria, 0.0))) for categoria in principais}
        if tem_outras:
            resto = [coluna for coluna in linha.index if coluna not in principais]
            valores["Outras"] = _numero(float(linha[resto].sum())) if resto else 0.0
        pontos.append({
            "periodo": _periodo_rotulo(indice),
            "rotulo": _rotulo_curto(indice),
            "valores": valores,
        })
    return {"categorias": categorias_legenda, "pontos": pontos}


def _tendencia_categorias(
    janela: pd.DataFrame, principais: list[str], periodos: list[int],
) -> dict[str, float | None]:
    """Variação % de cada categoria principal entre a 1ª e a 2ª metade da janela.

    Sinaliza categoria subindo/caindo dentro do próprio período selecionado,
    em vez de só o ranking estático por valor total. Janela de 1 mês não tem
    o que comparar. Parte no meio da lista de meses *com* lançamento — senão
    uma cauda de zeros futuros vira −100% em tudo.
    """
    if len(periodos) < 2:
        return {categoria: None for categoria in principais}

    meio = periodos[len(periodos) // 2]
    primeira = janela.loc[janela["_periodo"] < meio].groupby("categoria")["Valor"].sum()
    segunda = janela.loc[janela["_periodo"] >= meio].groupby("categoria")["Valor"].sum()

    tendencias: dict[str, float | None] = {}
    for categoria in principais:
        antes = float(primeira.get(categoria, 0.0))
        depois = float(segunda.get(categoria, 0.0))
        tendencias[categoria] = _numero((depois - antes) / antes * 100) if antes > 0 else None
    return tendencias


def _cortes_validos(cortes) -> tuple[float, ...]:
    """Cortes crescentes entre 0 e 100; qualquer coisa fora disso vira o padrão.

    Mesma regra de `analise_clientes._cortes_validos` — os dois precisam aceitar
    (e rejeitar) exatamente o mesmo `cortes_clientes` do `config.json`.
    """
    try:
        valores = tuple(float(valor) for valor in cortes)
    except (TypeError, ValueError):
        return CORTES_ABC_CATEGORIAS
    if not valores or any(not 0 < valor <= 100 for valor in valores):
        return CORTES_ABC_CATEGORIAS
    if list(valores) != sorted(valores):
        return CORTES_ABC_CATEGORIAS
    return valores


def _curva_abc_categorias(
    por_categoria_serie: pd.Series, cortes: tuple[float, ...] = CORTES_ABC_CATEGORIAS
) -> tuple[dict, dict[str, str]]:
    """Classificação Grupo 1/2/3/Demais das categorias pela régua de `faixa_por_curva`
    (mesmos cortes do Analisador, `cortes_clientes` do `config.json` do escopo).

    Devolve o resumo por grupo e um mapa categoria → grupo, para anotar cada
    linha de `por_categoria` sem recalcular a curva duas vezes.
    """
    cortes = list(cortes)
    if por_categoria_serie.empty or float(por_categoria_serie.sum()) <= 0:
        return {"cortes": cortes, "grupos": []}, {}

    curva = curva_pareto(por_categoria_serie)
    faixa = faixa_por_curva(curva, cortes)
    total = float(curva["Receita"].sum())

    grupos = []
    for nome in nomes_faixas(cortes):
        membros = curva.loc[faixa == nome]
        if membros.empty:
            continue
        valor = float(membros["Receita"].sum())
        grupos.append({
            "grupo": nome,
            "quantidade": int(len(membros)),
            "valor": _numero(valor),
            "pct": _numero(valor / total * 100) if total else 0.0,
        })
    return {"cortes": cortes, "grupos": grupos}, faixa.to_dict()


def montar_resumo_despesas(
    df: pd.DataFrame,
    *,
    meses: int = 12,
    limite_categorias: int = 10,
    usar_mes_fechado: bool = True,
    cortes=None,
) -> dict:
    """Total, série mês a mês e rankings de categoria/loja das despesas.

    Janela corrida de `meses` terminando no último mês com lançamento. Com
    `usar_mes_fechado`, o mês corrente (ainda em andamento, poucos dias de
    lançamento) fica fora da janela — senão ele aparece como queda brusca.

    `cortes` é o `cortes_clientes` do `config.json` do escopo (mesma régua do
    Analisador); `None` ou inválido cai em `CORTES_ABC_CATEGORIAS`.
    """
    meses = max(1, min(int(meses), 36))
    limite_categorias = max(1, min(int(limite_categorias), 50))
    cortes = _cortes_validos(cortes)

    if df is None or df.empty:
        return _resposta_vazia(meses)

    dados = _preparar(df)
    if dados.empty:
        return _resposta_vazia(meses)

    dados["_periodo"] = dados["Ano"].astype(int) * 12 + dados["Mês"].astype(int) - 1
    teto = _mes_atual_indice()
    # Competência futura (planilha com mês à frente) não entra no recorte —
    # senão a série ganha uma cauda de zeros até 2027 e todo mundo “cai 100%”.
    dados = dados[dados["_periodo"] < teto] if usar_mes_fechado else dados[dados["_periodo"] <= teto]
    if dados.empty:
        return _resposta_vazia(meses)

    por_mes_completo = dados.groupby("_periodo")["Valor"].sum()
    meses_com_valor = por_mes_completo[por_mes_completo > 0]
    if meses_com_valor.empty:
        return _resposta_vazia(meses)

    fim = int(meses_com_valor.index.max())
    inicio = fim - meses + 1
    janela = dados[dados["_periodo"].between(inicio, fim)]

    por_mes = janela.groupby("_periodo")["Valor"].sum()
    periodos = [
        int(indice)
        for indice in range(inicio, fim + 1)
        if float(por_mes.get(indice, 0.0)) > 0
    ]
    if not periodos:
        return _resposta_vazia(meses)

    serie_mensal = [
        {
            "periodo": _periodo_rotulo(indice),
            "rotulo": _rotulo_curto(indice),
            "valor": _numero(por_mes.get(indice, 0.0)),
        }
        for indice in periodos
    ]

    total = float(janela["Valor"].sum())
    media_mensal = total / len(periodos)
    mes_atual = float(por_mes.get(periodos[-1], 0.0))
    mes_anterior = float(por_mes.get(periodos[-2], 0.0)) if len(periodos) > 1 else 0.0
    variacao_pct = (
        (mes_atual - mes_anterior) / mes_anterior * 100 if mes_anterior > 0 else None
    )

    por_categoria_serie = janela.groupby("categoria")["Valor"].sum().sort_values(ascending=False)
    principais = por_categoria_serie.head(limite_categorias)
    por_categoria = [
        {
            "categoria": str(categoria),
            "valor": _numero(valor),
            "pct": _numero(valor / total * 100) if total else 0.0,
        }
        for categoria, valor in principais.items()
    ]
    resto = float(por_categoria_serie.iloc[limite_categorias:].sum())
    if resto > 0:
        por_categoria.append({
            "categoria": "Demais",
            "valor": _numero(resto),
            "pct": _numero(resto / total * 100) if total else 0.0,
        })

    curva_abc_categorias, grupo_por_categoria = _curva_abc_categorias(por_categoria_serie, cortes)
    tendencia_por_categoria = _tendencia_categorias(
        janela, list(principais.index), periodos,
    )
    for item in por_categoria:
        item["grupo_abc"] = grupo_por_categoria.get(item["categoria"])
        item["tendencia_pct"] = tendencia_por_categoria.get(item["categoria"])

    serie_mensal_categorias = _serie_mensal_por_categoria(
        janela,
        list(principais.head(LIMITE_SERIE_MENSAL_CATEGORIAS).index),
        len(por_categoria_serie) > LIMITE_SERIE_MENSAL_CATEGORIAS,
        periodos,
    )

    por_loja = []
    if "Loja" in janela.columns:
        agrupado_loja = janela.groupby("Loja")["Valor"].sum().sort_values(ascending=False)
        por_loja = [
            {"loja": str(loja), "valor": _numero(valor)}
            for loja, valor in agrupado_loja.items()
        ]

    por_mes_completo = dados.groupby("_periodo")["Valor"].sum()
    mes_ano_anterior = por_mes_completo.get(fim - 12)
    mes_mesmo_periodo_ano_anterior = _numero(mes_ano_anterior) if mes_ano_anterior is not None else None
    variacao_anual_pct = (
        _numero((mes_atual - mes_ano_anterior) / mes_ano_anterior * 100)
        if mes_ano_anterior is not None and mes_ano_anterior > 0 else None
    )

    return {
        "periodo_inicio": _periodo_rotulo(periodos[0]),
        "periodo_fim": _periodo_rotulo(periodos[-1]),
        "meses": meses,
        "resumo": {
            "total": _numero(total),
            "media_mensal": _numero(media_mensal),
            "mes_atual": _numero(mes_atual),
            "mes_anterior": _numero(mes_anterior),
            "variacao_pct": _opcional(variacao_pct),
            "mes_mesmo_periodo_ano_anterior": mes_mesmo_periodo_ano_anterior,
            "variacao_anual_pct": variacao_anual_pct,
        },
        "serie_mensal": serie_mensal,
        "serie_mensal_categorias": serie_mensal_categorias,
        "por_categoria": por_categoria,
        "por_loja": por_loja,
        "curva_abc_categorias": curva_abc_categorias,
    }


def montar_detalhe_despesas(
    df: pd.DataFrame,
    *,
    periodo: str | None = None,
    categoria: str | None = None,
    limite: int = 500,
) -> dict:
    """Lançamentos individuais para a tabela de detalhe, filtráveis por mês/categoria.

    `periodo` no formato "AAAA-MM" (mesmo rótulo da série mensal). Ordenado do
    maior para o menor valor — é o que mais chama atenção numa lista de despesas.
    """
    limite = max(1, min(int(limite), 5000))
    if df is None or df.empty:
        return {"itens": [], "total_itens": 0, "limitado": False}

    dados = _preparar(df)
    if periodo:
        try:
            ano_str, mes_str = periodo.split("-")
            dados = dados[
                (dados["Ano"].astype(int) == int(ano_str))
                & (dados["Mês"].astype(int) == int(mes_str))
            ]
        except (ValueError, AttributeError):
            dados = dados.iloc[0:0]
    if categoria:
        dados = dados[dados["categoria"] == categoria]

    dados = dados.sort_values("Valor", ascending=False)
    total_itens = int(len(dados))
    dados = dados.head(limite)

    itens = [
        {
            "loja": str(linha.get("Loja") or "Sem loja"),
            "categoria": str(linha.get("categoria") or "Sem categoria"),
            "ano": int(linha["Ano"]),
            "mes": int(linha["Mês"]),
            "valor": _numero(linha.get("Valor")),
        }
        for linha in dados.to_dict(orient="records")
    ]

    return {
        "itens": itens,
        "total_itens": total_itens,
        "limitado": total_itens > len(itens),
    }
