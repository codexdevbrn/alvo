"""Painel de diagnóstico da carteira: a tensão, o mecanismo e a pauta.

Os relatórios do Analisador respondem "o que aconteceu" um a um, cada um numa
tabela. Esta tela junta os mesmos números na ordem em que a decisão é tomada:
quanto está em risco (tensão), por que mudou (mecanismo) e sobre quem falar
(pauta). Nada aqui recalcula regra de negócio — o motor é o mesmo
`engine.analise_funil` do relatório, para que tela e PDF nunca discordem.

Esta primeira fase entrega os blocos `tensao`, `cascata` e `tornado`.
"""

from __future__ import annotations

import pandas as pd

from analise_clientes import _cortes_validos, _meses_ate, _ordem_faixas
from engine.analise_funil import (
    clientes_queda_quantidade,
    comparativo_receita_ano_anterior,
    correlacao_produto_cliente,
    curva_pareto,
    erosao_clientes_por_produto,
    faixa_por_curva,
    impacto_financeiro_churn,
    nomes_faixas,
    produtos_alta_e_queda,
    sem_venda_clientes,
    tendencia_produtos,
)
from estoque_cobertura import _combinar_estoque_vendas
from periodo_mensal import (
    COLUNA_DATA_DIARIA,
    converter_periodo,
    deslocar_mes,
    dia_corte_mes_aberto,
    filtrar_ate_o_dia,
    inicio_mes,
    modo_periodo_valido,
    referencia_efetiva,
    rotulo_periodo,
)

# Produtos nomeados por lado na cascata; o resto entra agregado como "outros".
# Acima disso a cascata vira um pente de barras finas e perde a leitura.
LIMITE_CASCATA = 6
# Produtos por lado no tornado (alta e queda).
LIMITE_TORNADO = 8
# Produtos por lado no radar de sinais precoces (variação %, ver `_radar_percentual`).
LIMITE_RADAR_PERCENTUAL = 6
# Produtos considerados no KPI de concentração da queda.
TOPO_CONCENTRACAO = 3
# Meses de cada lado do fluxo de faixas. Trimestre móvel, não mês contra mês:
# nesta base a compra é intermitente (o mesmo achado que tirou a "receita sob
# risco" do Ato I), então a faixa mensal de quem compra a cada dois meses
# oscila por ausência de compra, não por mudança de comportamento. Três meses
# de cada lado é o menor corte que absorve isso.
JANELA_FLUXO_MESES = 3
# Meses na matriz de streak. A sequência de quedas é contada dentro dela, então
# o número também é o teto do streak que a tela consegue mostrar.
PERIODOS_STREAK = 6
# Quedas seguidas para o produto virar alerta.
QUEDA_CONSECUTIVA_MINIMA = 2
# Altas seguidas para o produto entrar na pílula "maior ganho" — mesma régua
# da queda, por simetria.
ALTA_CONSECUTIVA_MINIMA = 2
# Linhas da matriz de streak; acima disso a leitura vira parede de células.
LIMITE_STREAK = 10
# Clientes no scatter de risco. Corte é por Top N em R$ perdido, não por
# percentual de queda — cliente grande caindo 5% pesa mais que um pequeno
# caindo 80%, e um piso percentual escondia justo quem mais importa.
LIMITE_RISCO = 40
# Clientes no dumbbell de quantidade.
LIMITE_DUMBBELL = 10
# Colunas/linhas da matriz de erosão cliente x produto.
LIMITE_EROSAO_PRODUTOS = 8
LIMITE_EROSAO_CLIENTES = 10
# Produtos no scatter de margem x giro, cortado pelos maiores em capital parado.
LIMITE_MARGEM_GIRO = 60
# Mesma janela padrão da tela de Estoque (`obterResumoEstoque`) — cobertura
# recalculada aqui precisa bater com a que a tela de Estoque mostra.
MESES_COBERTURA_MARGEM_GIRO = 6
# Mesma régua da tela de Estoque (`EstoqueVisaoGeral`): sem cobertura < 0,5
# mês, alvo 3, excesso acima de 6 — nenhuma régua nova aqui.
COBERTURA_ALVO = 3.0
COBERTURA_EXCESSO = 6.0
COBERTURA_RUPTURA = 0.5
# Ordem de severidade do bullet: ruptura e parado primeiro, porque são os que
# pedem ação — normal por último, porque não pede nada.
ORDEM_STATUS_ESTOQUE = ["rupture", "stalled", "excess", "no_sales", "normal", "out_of_stock", "negative"]


class ErroDiagnostico(ValueError):
    """Erro de dados que a API pode mostrar direto."""


def _arredondar(valor) -> float | None:
    if valor is None:
        return None
    numero = float(valor)
    if pd.isna(numero) or numero in (float("inf"), float("-inf")):
        return None
    return round(numero, 2)


def _resposta_vazia(mensagem: str) -> dict:
    return {
        "disponivel": False,
        "mensagem": mensagem,
        "periodo_atual": None,
        "rotulo_periodo": None,
        "tensao": None,
        "cascata": {"passos": [], "cobertura_pct": None},
        "tornado": [],
        "radar_percentual": {"disponivel": False, "mensagem": mensagem, "alta": [], "queda": []},
        "fluxo_faixas": _fluxo_faixas_vazio(),
        "streak": {"periodos": [], "perda": [], "receita": [], "ganho": []},
        "risco": {"disponivel": False, "mensagem": mensagem, "clientes": [], "composicao": []},
        "queda_quantidade": {"disponivel": False, "mensagem": mensagem, "clientes": []},
        "matriz_erosao": {"disponivel": False, "mensagem": mensagem, "produtos": [], "clientes": []},
        "impacto_churn": {"receita_sob_risco": None, "maior_retracao_pct": None, "variacao_global_pct": None},
        "margem_giro": _margem_giro_vazio(mensagem),
    }


def _margem_giro_vazio(mensagem: str) -> dict:
    return {"disponivel": False, "mensagem": mensagem, "produtos": [], "bullet": []}


def _recortar_por_modo(df: pd.DataFrame, modo_periodo: str) -> tuple[pd.DataFrame, pd.Timestamp]:
    """Corta a base conforme o controle global de período.

    O motor sempre olha os dois últimos períodos PRESENTES na base, então o
    modo de período precisa ser aplicado antes de chamá-lo: em "fechados" o
    mês corrente (ainda aberto) sai, senão ele compara dias contra meses
    inteiros e tudo aparece como queda.
    """
    if df is None or df.empty:
        raise ErroDiagnostico("A base está vazia.")
    faltantes = sorted({"Receita", "descricao", "Cliente"} - set(df.columns))
    if faltantes:
        raise ErroDiagnostico("Base sem colunas necessárias: " + ", ".join(faltantes))

    periodo = converter_periodo(df)
    if not periodo.notna().any():
        raise ErroDiagnostico("A base não tem nenhum mês válido.")

    recorte = df.loc[periodo.notna()].copy()
    recorte["_periodo"] = periodo.loc[periodo.notna()]
    referencia = referencia_efetiva(
        inicio_mes(recorte["_periodo"].max()), modo_periodo == "fechados"
    )
    recorte = recorte.loc[recorte["_periodo"] <= referencia]
    if recorte.empty:
        raise ErroDiagnostico("Nenhum movimento até o período de referência.")

    if modo_periodo == "mesmo_periodo" and COLUNA_DATA_DIARIA in recorte.columns:
        no_mes = recorte.loc[recorte["_periodo"] == recorte["_periodo"].max()]
        recorte = filtrar_ate_o_dia(recorte, dia_corte_mes_aberto(no_mes[COLUNA_DATA_DIARIA]))

    return recorte, inicio_mes(recorte["_periodo"].max())


def _dois_ultimos_periodos(recorte: pd.DataFrame) -> tuple[pd.Timestamp | None, pd.Timestamp]:
    """Os mesmos dois períodos que o motor compara — derivados do que existe na
    base, não por aritmética de calendário (um mês sem movimento faria as duas
    contas divergirem)."""
    periodos = sorted(recorte["_periodo"].unique())
    atual = pd.Timestamp(periodos[-1])
    anterior = pd.Timestamp(periodos[-2]) if len(periodos) >= 2 else None
    return anterior, atual


def _delta_por_produto(recorte: pd.DataFrame) -> pd.DataFrame:
    """Receita por produto nos dois últimos períodos, com o delta em R$.

    Serve a dois blocos (a concentração da queda no Ato I e o tornado no Ato
    II), por isso é calculada uma vez só.
    """
    anterior, atual = _dois_ultimos_periodos(recorte)
    if anterior is None:
        return pd.DataFrame(columns=["antes", "depois", "delta"])

    por_produto = (
        recorte.loc[recorte["_periodo"].isin([anterior, atual])]
        .pivot_table(index="descricao", columns="_periodo", values="Receita", aggfunc="sum")
        .reindex(columns=[anterior, atual], fill_value=0.0)
        .fillna(0.0)
    )
    return pd.DataFrame({
        "antes": por_produto[anterior],
        "depois": por_produto[atual],
        "delta": por_produto[atual] - por_produto[anterior],
    })


def _tensao(recorte: pd.DataFrame, delta_produtos: pd.DataFrame) -> dict:
    """ATO I: o tamanho do movimento do mês e o quanto dele está concentrado.

    Deliberadamente NÃO traz "receita sob risco". Nesta base a compra é
    intermitente — a maior parte dos clientes não compra todo mês —, então
    somar as quedas individuais conta como churn quem apenas ainda não
    voltou: na IBAD isso dá 3x a queda real da empresa. Enquanto o negócio
    não definir uma régua de recorrência, o Ato I mostra o que aconteceu, não
    uma projeção.
    """
    anterior, atual = _dois_ultimos_periodos(recorte)
    receita_atual = float(recorte.loc[recorte["_periodo"] == atual, "Receita"].sum())
    receita_anterior = (
        float(recorte.loc[recorte["_periodo"] == anterior, "Receita"].sum())
        if anterior is not None else 0.0
    )
    ano_anterior = deslocar_mes(atual, -12)
    receita_ano_anterior = float(recorte.loc[recorte["_periodo"] == ano_anterior, "Receita"].sum())

    quedas = delta_produtos.loc[delta_produtos["delta"] < 0, "delta"].sort_values()
    queda_total = float(quedas.sum())
    concentracao = (
        float(quedas.head(TOPO_CONCENTRACAO).sum()) / queda_total * 100 if queda_total < 0 else None
    )

    def variacao(base: float) -> float | None:
        return (receita_atual - base) / base * 100 if base > 0 else None

    return {
        "receita_periodo": _arredondar(receita_atual),
        "receita_anterior": _arredondar(receita_anterior),
        "variacao_pct": _arredondar(variacao(receita_anterior)),
        "delta_receita": _arredondar(receita_atual - receita_anterior),
        "receita_ano_anterior": _arredondar(receita_ano_anterior),
        "variacao_ano_pct": _arredondar(variacao(receita_ano_anterior)),
        "produtos_em_queda": int(len(quedas)),
        "concentracao_queda_pct": _arredondar(concentracao),
        "topo_concentracao": TOPO_CONCENTRACAO,
        "rotulo_anterior": rotulo_periodo(anterior) if anterior is not None else None,
        "rotulo_ano_anterior": rotulo_periodo(ano_anterior),
    }


def _passo(tipo: str, rotulo: str, delta: float, acumulado_antes: float) -> tuple[dict, float]:
    """Um degrau da cascata, já com a geometria pronta.

    O frontend desenha barra flutuante empilhando um trecho invisível (`base`)
    sob o trecho colorido (`altura`) — calcular isso aqui evita repetir a mesma
    aritmética de acumulado no componente.
    """
    acumulado = acumulado_antes + delta
    return {
        "tipo": tipo,
        "rotulo": rotulo,
        "delta": _arredondar(delta),
        "base": _arredondar(min(acumulado_antes, acumulado)),
        "altura": _arredondar(abs(delta)),
        "acumulado": _arredondar(acumulado),
    }, acumulado


def _cascata(recorte: pd.DataFrame) -> dict:
    """ATO II: por que a receita mudou contra o mesmo período do ano passado.

    Ano contra ano (não contra o mês anterior) porque é o corte que neutraliza
    sazonalidade — a pergunta aqui é "o negócio encolheu?", não "o mês foi
    fraco?".

    Devolve também a `cobertura_pct`: o comparativo descarta produto sem
    descrição harmonizada, então a cascata fecha alguns pontos abaixo da
    receita do KPI. É pouco (1,4% na IBAD), mas dois totais diferentes na
    mesma tela precisam se explicar — o card rotula a própria base.
    """
    _, atual = _dois_ultimos_periodos(recorte)
    # O comparativo só olha o período mais recente e o mesmo do ano anterior;
    # passar a base inteira faz ele varrer 1,4 milhão de linhas para usar duas
    # fatias (4,6s contra 0,3s na IBAD).
    janela = recorte.loc[recorte["_periodo"].isin([atual, deslocar_mes(atual, -12)])]
    comparativo = comparativo_receita_ano_anterior(janela)
    if comparativo.empty:
        return {"passos": [], "cobertura_pct": None}

    inicio = float(comparativo["Receita_Ano_Anterior"].sum())
    ganhos = comparativo.loc[comparativo["Ganho_Perda"] > 0].sort_values("Ganho_Perda", ascending=False)
    perdas = comparativo.loc[comparativo["Ganho_Perda"] < 0].sort_values("Ganho_Perda")

    passos = [{
        "tipo": "inicio",
        "rotulo": str(comparativo["Periodo_Ano_Anterior"].iloc[0]),
        "delta": _arredondar(inicio),
        "base": 0.0,
        "altura": _arredondar(inicio),
        "acumulado": _arredondar(inicio),
    }]

    acumulado = inicio
    for frame, tipo, rotulo_resto in (
        (ganhos, "ganho", "Outros ganhos"),
        (perdas, "perda", "Outras perdas"),
    ):
        for _, linha in frame.head(LIMITE_CASCATA).iterrows():
            passo, acumulado = _passo(tipo, str(linha["descricao"]), float(linha["Ganho_Perda"]), acumulado)
            passos.append(passo)
        resto = float(frame["Ganho_Perda"].iloc[LIMITE_CASCATA:].sum())
        if resto:
            rotulo = f"{rotulo_resto} ({len(frame) - LIMITE_CASCATA})"
            passo, acumulado = _passo(tipo, rotulo, resto, acumulado)
            passos.append(passo)

    passos.append({
        "tipo": "fim",
        "rotulo": str(comparativo["Periodo_Ano_Atual"].iloc[0]),
        "delta": _arredondar(acumulado),
        "base": 0.0,
        "altura": _arredondar(acumulado),
        "acumulado": _arredondar(acumulado),
    })

    receita_periodo = float(recorte.loc[recorte["_periodo"] == atual, "Receita"].sum())
    return {
        "passos": passos,
        "cobertura_pct": _arredondar(acumulado / receita_periodo * 100) if receita_periodo > 0 else None,
    }


def _tornado(delta_produtos: pd.DataFrame) -> list[dict]:
    """ATO II: o que puxou o mês para cima e para baixo, em R$.

    Não usa `produtos_alta_e_queda` de propósito: aquele boletim ranqueia por
    variação PERCENTUAL, então um produto que saiu de R$ 10 para R$ 100 entra
    na frente de um que perdeu R$ 50 mil. Aqui a pergunta é impacto
    financeiro, então o ranking é pelo delta em R$.
    """
    if delta_produtos.empty:
        return []

    ordenado = delta_produtos.sort_values("delta", ascending=False)
    extremos = pd.concat([ordenado.head(LIMITE_TORNADO), ordenado.tail(LIMITE_TORNADO)])
    extremos = extremos[extremos["delta"] != 0]
    extremos = extremos[~extremos.index.duplicated()]

    linhas = [
        {
            "descricao": str(descricao),
            "receita_anterior": _arredondar(linha["antes"]),
            "receita_atual": _arredondar(linha["depois"]),
            "delta_receita": _arredondar(linha["delta"]),
            "variacao_pct": (
                _arredondar((linha["depois"] - linha["antes"]) / linha["antes"] * 100)
                if linha["antes"] > 0 else None
            ),
        }
        for descricao, linha in extremos.iterrows()
    ]
    linhas.sort(key=lambda linha: linha["delta_receita"], reverse=True)
    return linhas


def _radar_percentual(recorte: pd.DataFrame, tornado: list[dict]) -> dict:
    """ATO II: sinal de tendência nascente que o Tornado ainda não vê — produto
    pequeno mudando de patamar rápido, antes de virar dinheiro suficiente pra
    entrar no ranking por delta em R$.

    `_tornado` rejeita ranquear por variação percentual pura de propósito
    (ver o docstring dela): R$10 → R$100 é +900% e não significa nada. Aqui a
    régua é o oposto — só entra quem já tem receita relevante (piso = mediana
    da receita anterior entre os produtos que se moveram) — e quem o Tornado
    já mostrou sai daqui, porque o radar existe pra cobrir só o que o
    ranking por R$ ainda não pegou.
    """
    vazio = {"disponivel": False, "mensagem": "Sem período suficiente para comparar.", "alta": [], "queda": []}
    em_alta, em_queda = produtos_alta_e_queda(recorte, granularidade="Mensal", top_n=40)
    combinado = pd.concat([em_alta, em_queda])
    if combinado.empty:
        return vazio

    piso = float(combinado["Receita_Periodo_Anterior"].median())
    ja_no_tornado = {linha["descricao"] for linha in tornado}

    def _linhas(tabela: pd.DataFrame, ascendente: bool) -> list[dict]:
        filtrado = tabela[
            (tabela["Receita_Periodo_Anterior"] >= piso)
            # Devolução maior que a venda do período deixa a receita atual
            # negativa — não é sinal de tendência, é anomalia de estorno, e
            # "R$ 449 → -R$ 1.052" lê como conta quebrada, não como alerta.
            & (tabela["Receita_Periodo_Atual"] >= 0)
            & (~tabela["descricao"].isin(ja_no_tornado))
        ]
        # Empate no percentual (vários produtos zerados = -100%) é comum —
        # desempata por quem tinha mais receita antes, senão a ordem dentro do
        # empate é arbitrária e o card pode abrir com o produto menos relevante.
        filtrado = filtrado.sort_values(
            ["Variacao_Percentual", "Receita_Periodo_Anterior"], ascending=[ascendente, False],
        ).head(LIMITE_RADAR_PERCENTUAL)
        return [
            {
                "descricao": str(linha.descricao),
                "receita_anterior": _arredondar(linha.Receita_Periodo_Anterior),
                "receita_atual": _arredondar(linha.Receita_Periodo_Atual),
                "variacao_pct": _arredondar(linha.Variacao_Percentual),
            }
            for linha in filtrado.itertuples()
        ]

    alta, queda = _linhas(em_alta, ascendente=False), _linhas(em_queda, ascendente=True)
    if not alta and not queda:
        return {
            "disponivel": False,
            "mensagem": "Nenhum sinal relevante fora do que o Tornado já mostra.",
            "alta": [], "queda": [],
        }
    return {"disponivel": True, "mensagem": None, "alta": alta, "queda": queda}


def _fluxo_faixas_vazio(mensagem: str | None = None) -> dict:
    return {
        "disponivel": False,
        "mensagem": mensagem,
        "rotulo_atual": None,
        "rotulo_anterior": None,
        "faixas": [],
        "fluxos": [],
        "resumo": None,
    }


def _faixa_por_cliente(recorte: pd.DataFrame, meses, cortes: tuple[float, ...]) -> pd.Series:
    """Faixa ABC de cada cliente na janela, pela régua única do projeto.

    Usa `curva_pareto` + `faixa_por_curva` em vez de `classificar_abc` porque a
    classificação precisa ser de uma janela de três meses agregada, e o motor
    classifica período a período. A régua é a mesma — é a função que a prévia,
    o relatório e a curva da tela de Clientes já usam.
    """
    receita = recorte.loc[recorte["_periodo"].isin(meses)].groupby("Cliente")["Receita"].sum()
    receita = receita[receita > 0].sort_values(ascending=False)
    if receita.empty:
        return pd.Series(dtype=object)
    curva = curva_pareto(receita)
    return pd.Series(faixa_por_curva(curva, cortes), index=curva.index)


def _fluxo_faixas(recorte: pd.DataFrame, referencia: pd.Timestamp, cortes) -> dict:
    """ATO II: para onde os clientes se moveram entre as faixas ABC.

    Só entra quem comprou nos DOIS lados: quem entrou ou saiu da carteira é
    contado no resumo, mas não vira fluxo. Misturar as duas coisas faria a
    banda "Demais → sem compra" dominar o desenho e repetir, pior, o gráfico de
    entrada e saída que a tela de Clientes já tem.
    """
    cortes = _cortes_validos(cortes)
    meses_atual = _meses_ate(referencia, JANELA_FLUXO_MESES)
    meses_anterior = _meses_ate(deslocar_mes(referencia, -JANELA_FLUXO_MESES), JANELA_FLUXO_MESES)
    disponiveis = set(recorte["_periodo"].unique())
    if not set(meses_anterior) & disponiveis:
        return _fluxo_faixas_vazio("A base não cobre os dois trimestres da comparação.")

    faixa_atual = _faixa_por_cliente(recorte, meses_atual, cortes)
    faixa_anterior = _faixa_por_cliente(recorte, meses_anterior, cortes)
    if faixa_atual.empty or faixa_anterior.empty:
        return _fluxo_faixas_vazio("Sem receita em um dos trimestres.")

    faixas = nomes_faixas(cortes)
    ordem = _ordem_faixas(faixas)
    comuns = faixa_atual.index.intersection(faixa_anterior.index)
    entraram = int(len(faixa_atual.index.difference(faixa_anterior.index)))
    sairam = int(len(faixa_anterior.index.difference(faixa_atual.index)))
    if len(comuns) == 0:
        return _fluxo_faixas_vazio("Nenhum cliente comprou nos dois trimestres.")

    receita_atual = (
        recorte.loc[recorte["_periodo"].isin(meses_atual)].groupby("Cliente")["Receita"].sum()
    )
    movimento = pd.DataFrame({
        "de": faixa_anterior.loc[comuns],
        "para": faixa_atual.loc[comuns],
        "receita": receita_atual.reindex(comuns).fillna(0.0),
    })
    movimento["passo"] = movimento["para"].map(ordem) - movimento["de"].map(ordem)

    agregado = movimento.groupby(["de", "para"], sort=False).agg(
        clientes=("receita", "size"), receita=("receita", "sum"),
    ).reset_index()
    fluxos = [
        {
            "de": str(linha.de),
            "para": str(linha.para),
            "clientes": int(linha.clientes),
            "receita": _arredondar(linha.receita),
            # Sinal do movimento, para a tela colorir sem reimplementar a ordem
            # das faixas (que não é alfabética: "Demais" é a última, não a
            # quarta letra).
            "passo": int(ordem[str(linha.para)] - ordem[str(linha.de)]),
        }
        for linha in agregado.itertuples()
    ]
    fluxos.sort(key=lambda fluxo: fluxo["clientes"], reverse=True)

    subiram = movimento.loc[movimento["passo"] > 0]
    desceram = movimento.loc[movimento["passo"] < 0]
    return {
        "disponivel": True,
        "mensagem": None,
        "rotulo_atual": f"{rotulo_periodo(meses_atual[0])}–{rotulo_periodo(meses_atual[-1])}",
        "rotulo_anterior": f"{rotulo_periodo(meses_anterior[0])}–{rotulo_periodo(meses_anterior[-1])}",
        "faixas": faixas,
        "fluxos": fluxos,
        "resumo": {
            "subiram": int(len(subiram)),
            "desceram": int(len(desceram)),
            "mantiveram": int(len(movimento) - len(subiram) - len(desceram)),
            "entraram": entraram,
            "sairam": sairam,
            "receita_subiram": _arredondar(subiram["receita"].sum()),
            "receita_desceram": _arredondar(desceram["receita"].sum()),
        },
    }


def _sequencia_alta_final(receita: pd.Series, receita_anterior: pd.Series) -> tuple[int, float, float]:
    """Tamanho da sequência de altas terminando no período mais recente, e a
    receita nas duas pontas dessa sequência (não do histórico inteiro) — o
    espelho do streak de queda do motor, que só existe para o lado da queda
    porque nasceu para alertar churn, não para ranquear alta. `receita` e
    `receita_anterior` já vêm com os buracos zerados (mesma série que o motor
    devolve em `evolucao`), então a comparação simples já é segura."""
    em_alta = (receita.to_numpy() > receita_anterior.to_numpy())
    tamanho = 0
    for valor in em_alta:
        tamanho = tamanho + 1 if valor else 0
    if tamanho == 0:
        return 0, 0.0, 0.0
    valores = receita.to_numpy()
    primeiro = valores[len(valores) - tamanho - 1]
    return tamanho, float(primeiro), float(valores[-1])


def _streak(recorte: pd.DataFrame, referencia: pd.Timestamp) -> dict:
    """ATO II: como cada produto andou nos últimos meses — a mesma matriz,
    três jeitos de escolher quem entra nela: quem mais perdeu, quem mais
    ganhou, ou quem mais pesa na receita agora, independente de tendência.
    As três já vêm prontas juntas, para a pílula de classificação trocar a
    lista na tela sem voltar ao servidor.
    """
    vazio = {"periodos": [], "perda": [], "receita": [], "ganho": []}
    meses = _meses_ate(referencia, PERIODOS_STREAK)
    janela = recorte.loc[recorte["_periodo"].isin(meses)]
    if janela.empty:
        return vazio

    evolucao, alertas = tendencia_produtos(
        janela, granularidade="Mensal", periodos_queda_consecutiva=QUEDA_CONSECUTIVA_MINIMA,
    )
    if evolucao.empty:
        return vazio

    rotulos = [rotulo_periodo(mes) for mes in meses]
    presentes = [rotulo for rotulo in rotulos if rotulo in set(evolucao["Periodo"])]
    if not presentes:
        return vazio

    por_produto = {
        descricao: grupo.set_index("Periodo").reindex(presentes)
        for descricao, grupo in evolucao.groupby("descricao", sort=False)
    }

    def celulas(descricao: str) -> list[dict]:
        serie = por_produto[descricao]
        return [
            {
                "periodo": rotulo,
                "receita": _arredondar(serie.at[rotulo, "Receita"]) if pd.notna(serie.at[rotulo, "Receita"]) else None,
                "variacao_pct": (
                    _arredondar(serie.at[rotulo, "Variacao_Percentual"])
                    if pd.notna(serie.at[rotulo, "Variacao_Percentual"]) else None
                ),
            }
            for rotulo in presentes
        ]

    def linha(descricao, valor, receita_atual, periodos_consecutivos=None, participacao_pct=None) -> dict:
        return {
            "descricao": str(descricao),
            "valor": _arredondar(valor),
            "receita_atual": _arredondar(receita_atual),
            "periodos_consecutivos": int(periodos_consecutivos) if periodos_consecutivos is not None else None,
            "participacao_pct": _arredondar(participacao_pct) if participacao_pct is not None else None,
            "celulas": celulas(descricao),
        }

    # --- Maior perda: mesma régua de antes, do alerta de queda do motor —
    # queda tem de estar acontecendo AGORA (terminando no período mais
    # recente), não ser um histórico já recuperado.
    perda_linhas = []
    if not alertas.empty:
        alertas = alertas.copy()
        alertas["Perda"] = alertas["Receita_Primeiro_Periodo"] - alertas["Receita_Ultimo_Periodo"]
        # Ordena por R$ perdido, não por número de períodos: três meses caindo
        # R$ 200 não é a mesma notícia que dois meses caindo R$ 80 mil.
        alertas = alertas.sort_values("Perda", ascending=False).head(LIMITE_STREAK)
        perda_linhas = [
            linha(
                a.descricao, a.Perda, a.Receita_Ultimo_Periodo,
                periodos_consecutivos=a.Periodos_Consecutivos_Em_Queda,
            )
            for a in alertas.itertuples()
            if a.descricao in por_produto
        ]

    # --- Maior ganho: o espelho, calculado aqui porque o motor só alerta
    # queda (é uma função de churn, não de ranking de alta).
    candidatos_ganho = []
    for descricao, serie in por_produto.items():
        tamanho, primeiro, ultimo = _sequencia_alta_final(serie["Receita"], serie["Receita_Periodo_Anterior"])
        if tamanho >= ALTA_CONSECUTIVA_MINIMA:
            candidatos_ganho.append((descricao, ultimo - primeiro, tamanho, ultimo))
    candidatos_ganho.sort(key=lambda item: item[1], reverse=True)
    ganho_linhas = [
        linha(descricao, ganho, receita_atual, periodos_consecutivos=tamanho)
        for descricao, ganho, tamanho, receita_atual in candidatos_ganho[:LIMITE_STREAK]
    ]

    # --- Maior participação: quem mais pesa na receita agora, sem olhar
    # tendência — inclusive produto estável ou em queda pode liderar aqui.
    ultimo_rotulo = presentes[-1]
    candidatos_receita = [
        (descricao, serie.at[ultimo_rotulo, "Receita"])
        for descricao, serie in por_produto.items()
        if pd.notna(serie.at[ultimo_rotulo, "Receita"]) and serie.at[ultimo_rotulo, "Receita"] > 0
    ]
    receita_total_atual = sum(valor for _, valor in candidatos_receita)
    candidatos_receita.sort(key=lambda item: item[1], reverse=True)
    receita_linhas = [
        linha(
            descricao, valor, valor,
            participacao_pct=(valor / receita_total_atual * 100) if receita_total_atual else None,
        )
        for descricao, valor in candidatos_receita[:LIMITE_STREAK]
    ]

    return {"periodos": presentes, "perda": perda_linhas, "receita": receita_linhas, "ganho": ganho_linhas}


def _risco_clientes(recorte: pd.DataFrame, referencia: pd.Timestamp, cortes) -> dict:
    """ATO III: quem está com receita em queda agora — base do scatter (quanto
    valia × quanto caiu) e do resumo de onde a perda se concentra por faixa.

    Sem piso percentual (`sem_venda_clientes` com `reducao_minima_percentual=0`):
    quem entra na pauta é o Top N por perda em R$, não por um corte arbitrário
    de queda — um piso percentual escondia justo o cliente grande que caiu só
    5%, mas em valor absoluto pesa mais que um pequeno que caiu 80%.
    """
    quedas = sem_venda_clientes(recorte, granularidade="Mensal", reducao_minima_percentual=0.0)
    if quedas.empty:
        return {"disponivel": False, "mensagem": "Nenhum cliente em queda no período.", "clientes": [], "composicao": []}

    cortes = _cortes_validos(cortes)
    meses_atual = _meses_ate(referencia, JANELA_FLUXO_MESES)
    faixa_atual = _faixa_por_cliente(recorte, meses_atual, cortes)

    quedas = quedas.sort_values("Reducao_Receita", ascending=False).head(LIMITE_RISCO).copy()
    quedas["Faixa"] = quedas["Cliente"].map(faixa_atual).fillna("Sem faixa").astype(str)

    clientes = [
        {
            "cliente": str(linha.Cliente),
            "receita_anterior": _arredondar(linha.Receita_Periodo_Anterior),
            "receita_atual": _arredondar(linha.Receita),
            "perda_rs": _arredondar(linha.Reducao_Receita),
            "variacao_pct": _arredondar(-linha.Reducao_Percentual),
            "parou_de_comprar": bool(linha.Parou_De_Comprar),
            "faixa": linha.Faixa,
        }
        for linha in quedas.itertuples()
    ]

    composicao_agrupada = quedas.groupby("Faixa").agg(
        perda_rs=("Reducao_Receita", "sum"), clientes=("Cliente", "size"),
    )
    composicao = sorted(
        (
            {"faixa": faixa, "perda_rs": _arredondar(linha.perda_rs), "clientes": int(linha.clientes)}
            for faixa, linha in composicao_agrupada.iterrows()
        ),
        key=lambda item: item["perda_rs"] or 0,
        reverse=True,
    )

    return {"disponivel": True, "mensagem": None, "clientes": clientes, "composicao": composicao}


def _queda_quantidade(recorte: pd.DataFrame) -> dict:
    """ATO III: quem compra o de sempre, mas em menos quantidade — dumbbell de
    unidades por cliente, período anterior contra o atual, com o produto que
    mais pesou na queda de cada um."""
    dados = clientes_queda_quantidade(recorte, granularidade="Mensal", top_n=LIMITE_DUMBBELL)
    if dados.empty:
        return {"disponivel": False, "mensagem": "Nenhuma queda de quantidade no período.", "clientes": []}

    clientes = [
        {
            "cliente": str(linha.Cliente),
            "qtd_anterior": _arredondar(linha.QTD_Periodo_Anterior),
            "qtd_atual": _arredondar(linha.QTD_Periodo_Atual),
            "variacao_pct": _arredondar(linha.Variacao_Percentual),
            "perda_receita": _arredondar(linha.Perda_Receita),
            "produto_critico": str(linha.Produto_Critico),
        }
        for linha in dados.itertuples()
    ]
    return {"disponivel": True, "mensagem": None, "clientes": clientes}


def _status_causa_erosao(recorte: pd.DataFrame, erosao: pd.DataFrame) -> dict[tuple[str, str], str]:
    """Classifica CADA evento de erosão (não só o Top 15 do boletim) com o
    mesmo motor de `correlacao_produto_cliente` — a matriz mostra até
    `LIMITE_EROSAO_PRODUTOS` × `LIMITE_EROSAO_CLIENTES` células, e uma célula
    visível sem causa classificada leria como buraco no dado, não como corte
    de ranking."""
    if erosao.empty:
        return {}
    _, alertas = tendencia_produtos(recorte, granularidade="Mensal", periodos_queda_consecutiva=QUEDA_CONSECUTIVA_MINIMA)
    classificado = correlacao_produto_cliente(recorte, erosao, alertas, granularidade="Mensal", top_n=len(erosao))
    return {(str(linha.Cliente), str(linha.descricao)): str(linha.Status) for linha in classificado.itertuples()}


def _matriz_erosao(recorte: pd.DataFrame) -> dict:
    """ATO III: cruzamento cliente × produto de quem caiu, e em quê — mesma
    régua do relatório de erosão do Analisador (`erosao_clientes_por_produto`),
    só sem piso de queda mínima: o corte de ruído aqui é o Top N por perda em
    R$ (produtos e clientes), não um percentual.
    """
    erosao = erosao_clientes_por_produto(recorte, granularidade="Mensal", reducao_minima_percentual=0.0)
    if erosao.empty:
        return {"disponivel": False, "mensagem": "Nenhuma erosão de produto no período.", "produtos": [], "clientes": []}

    top_produtos = (
        erosao.groupby("descricao")["Reducao_Receita"].sum()
        .sort_values(ascending=False).head(LIMITE_EROSAO_PRODUTOS).index.tolist()
    )
    filtrado = erosao[erosao["descricao"].isin(top_produtos)]
    perda_por_cliente = filtrado.groupby("Cliente")["Reducao_Receita"].sum().sort_values(ascending=False)
    top_clientes = perda_por_cliente.head(LIMITE_EROSAO_CLIENTES).index.tolist()
    if not top_clientes:
        return {"disponivel": False, "mensagem": "Nenhuma erosão de produto no período.", "produtos": [], "clientes": []}

    tabela = filtrado[filtrado["Cliente"].isin(top_clientes)]
    por_par = {(linha.Cliente, linha.descricao): linha for linha in tabela.itertuples()}
    status_por_par = _status_causa_erosao(recorte, erosao)

    def _celula(cliente: str, produto: str) -> dict:
        linha = por_par.get((cliente, produto))
        if linha is None:
            return {"produto": produto, "perda_rs": None, "receita_anterior": None, "variacao_pct": None, "status": None}
        return {
            "produto": produto,
            "perda_rs": _arredondar(linha.Reducao_Receita),
            "receita_anterior": _arredondar(linha.Receita_Periodo_Anterior),
            # Negativo = caiu, mesma convenção do resto do payload (ver
            # `ClienteRisco.variacao_pct` em client.ts) — `Reducao_Percentual`
            # sai positiva do motor de análise.
            "variacao_pct": _arredondar(-linha.Reducao_Percentual),
            "status": status_por_par.get((cliente, produto)),
        }

    clientes = [
        {
            "cliente": str(cliente),
            "perda_total": _arredondar(perda_por_cliente.get(cliente, 0.0)),
            "celulas": [_celula(cliente, produto) for produto in top_produtos],
        }
        for cliente in top_clientes
    ]

    return {"disponivel": True, "mensagem": None, "produtos": top_produtos, "clientes": clientes}


def _impacto_churn(recorte: pd.DataFrame) -> dict:
    """ATO III: tamanho do risco em R$ — o número que a Tensão (Ato I) deixa
    de fora de propósito por causa do padrão de compra intermitente (ver
    `_tensao`). Aqui é exposição — soma de toda queda individual cliente x
    produto —, não perda confirmada: mora na pauta, junto de quem está em
    risco, não no resumo do topo.
    """
    erosao = erosao_clientes_por_produto(recorte, granularidade="Mensal", reducao_minima_percentual=0.0)
    resultado = impacto_financeiro_churn(recorte, erosao, granularidade="Mensal").iloc[0]
    variacao = resultado["Variacao_Global_Periodo_Pct"]
    return {
        "receita_sob_risco": _arredondar(resultado["Receita_Sob_Risco"]),
        "maior_retracao_pct": _arredondar(resultado["Maior_Retracao_Individual_Pct"]),
        "variacao_global_pct": _arredondar(variacao) if variacao is not None else None,
    }


def _margem_giro(
    recorte: pd.DataFrame, estoque: pd.DataFrame | None, vendas: pd.DataFrame | None,
) -> dict:
    """ATO III: cruza margem % (quanto cada produto deixa) com a cobertura de
    estoque em meses (a velocidade de giro). Baixa margem parada é candidato a
    descontinuar; baixa margem girando rápido pede reajuste de preço, não
    corte — a distinção só existe cruzando as duas, nenhuma das duas telas
    (Estoque, Precificação) mostra as duas juntas.

    Cobertura e status vêm de `_combinar_estoque_vendas`, a mesma conta da
    tela de Estoque — nenhuma régua nova aqui, para as duas telas nunca
    discordarem sobre o que está parado. Margem usa o CMV do próprio
    movimento (`recorte`), no último período, cruzado por código de produto —
    não por descrição harmonizada: duas variações do mesmo harmonizado têm
    códigos e coberturas diferentes, e agregar por texto misturaria as duas.
    """
    if (
        estoque is None or estoque.empty
        or "CMV" not in recorte.columns or "Código Interno" not in recorte.columns
    ):
        return _margem_giro_vazio("Estoque não disponível para esta empresa.")

    combinado, _inicio, _fim = _combinar_estoque_vendas(
        estoque,
        vendas if vendas is not None else pd.DataFrame(),
        meses=MESES_COBERTURA_MARGEM_GIRO,
        cobertura_alvo=COBERTURA_ALVO,
        cobertura_excesso=COBERTURA_EXCESSO,
        cobertura_ruptura=COBERTURA_RUPTURA,
    )
    if combinado.empty:
        return _margem_giro_vazio("Estoque não disponível para esta empresa.")
    combinado["_codigo"] = combinado["CODIGO_INTERNO_PRODUTO"].astype(str).str.strip()

    _, atual = _dois_ultimos_periodos(recorte)
    janela = recorte.loc[recorte["_periodo"] == atual].copy()
    janela["_codigo"] = janela["Código Interno"].astype(str).str.strip()
    margem_produto = janela.groupby("_codigo").agg(
        receita=("Receita", "sum"), cmv=("CMV", "sum"), descricao=("descricao", "first"),
    )
    margem_produto = margem_produto.loc[margem_produto["receita"] > 0].copy()
    if margem_produto.empty:
        return _margem_giro_vazio("Nenhum produto com receita no período para calcular margem.")
    margem_produto["margem_pct"] = (
        (margem_produto["receita"] - margem_produto["cmv"]) / margem_produto["receita"] * 100
    )

    cruzado = combinado.merge(margem_produto, left_on="_codigo", right_index=True, how="inner")
    cruzado = cruzado.loc[cruzado["valor_estoque"] > 0]
    if cruzado.empty:
        return _margem_giro_vazio("Nenhum produto com estoque e receita no período para cruzar.")
    cruzado = cruzado.sort_values("valor_estoque", ascending=False).head(LIMITE_MARGEM_GIRO)

    produtos = [
        {
            "descricao": str(linha.descricao),
            "margem_pct": _arredondar(linha.margem_pct),
            "cobertura_meses": _arredondar(linha.cobertura) if pd.notna(linha.cobertura) else None,
            "valor_estoque": _arredondar(linha.valor_estoque),
            "receita": _arredondar(linha.receita),
            "status": str(linha.status),
        }
        for linha in cruzado.itertuples()
    ]

    agrupado_bullet = combinado.groupby("status").agg(
        produtos=("_codigo", "size"), valor_estoque=("valor_estoque", "sum"),
    )
    bullet = sorted(
        (
            {"status": str(status), "produtos": int(linha.produtos), "valor_estoque": _arredondar(linha.valor_estoque)}
            for status, linha in agrupado_bullet.iterrows()
        ),
        key=lambda item: ORDEM_STATUS_ESTOQUE.index(item["status"]) if item["status"] in ORDEM_STATUS_ESTOQUE else 99,
    )

    return {"disponivel": True, "mensagem": None, "produtos": produtos, "bullet": bullet}


def montar_painel_diagnostico(
    df: pd.DataFrame | None, modo_periodo: str = "fechados", cortes=None,
    estoque: pd.DataFrame | None = None, vendas: pd.DataFrame | None = None,
) -> dict:
    """Tensão, mecanismo e pauta da carteira no período de referência.

    `cortes` são os mesmos do `config.json` do escopo que a tela de Clientes e o
    relatório usam — o cliente precisa cair na mesma faixa nas três telas.
    """
    modo_periodo = modo_periodo_valido(modo_periodo)
    try:
        recorte, referencia = _recortar_por_modo(df, modo_periodo)
    except ErroDiagnostico as erro:
        return _resposta_vazia(str(erro))

    delta_produtos = _delta_por_produto(recorte)
    tornado = _tornado(delta_produtos)

    return {
        "disponivel": True,
        "mensagem": None,
        "periodo_atual": referencia.strftime("%Y-%m"),
        "rotulo_periodo": rotulo_periodo(referencia),
        "tensao": _tensao(recorte, delta_produtos),
        "cascata": _cascata(recorte),
        "tornado": tornado,
        "radar_percentual": _radar_percentual(recorte, tornado),
        "fluxo_faixas": _fluxo_faixas(recorte, referencia, cortes),
        "streak": _streak(recorte, referencia),
        "risco": _risco_clientes(recorte, referencia, cortes),
        "queda_quantidade": _queda_quantidade(recorte),
        "matriz_erosao": _matriz_erosao(recorte),
        "impacto_churn": _impacto_churn(recorte),
        "margem_giro": _margem_giro(recorte, estoque, vendas),
    }
