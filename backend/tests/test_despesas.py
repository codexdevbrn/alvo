import pandas as pd

from despesas import montar_detalhe_despesas, montar_resumo_despesas


def _despesas() -> pd.DataFrame:
    linhas = [
        {"Loja": "Matriz", "categoria": "FROTA / TAXAS", "Ano": 2023, "Mês": 1, "Valor": 1000.0},
        {"Loja": "Matriz", "categoria": "ALUGUEL", "Ano": 2023, "Mês": 1, "Valor": 500.0},
        {"Loja": "Filial", "categoria": "FROTA / TAXAS", "Ano": 2023, "Mês": 2, "Valor": 800.0},
        {"Loja": "Matriz", "categoria": "ALUGUEL", "Ano": 2023, "Mês": 2, "Valor": 500.0},
        {"Loja": "Matriz", "categoria": "FROTA / TAXAS", "Ano": 2023, "Mês": 3, "Valor": 200.0},
    ]
    return pd.DataFrame(linhas)


def test_totais_serie_mensal_e_categorias():
    resultado = montar_resumo_despesas(_despesas(), meses=3, usar_mes_fechado=False)

    assert resultado["periodo_inicio"] == "2023-01"
    assert resultado["periodo_fim"] == "2023-03"
    assert resultado["resumo"]["total"] == 3000.0
    assert resultado["resumo"]["media_mensal"] == 1000.0
    assert [ponto["valor"] for ponto in resultado["serie_mensal"]] == [1500.0, 1300.0, 200.0]

    categorias = {item["categoria"]: item["valor"] for item in resultado["por_categoria"]}
    assert categorias["FROTA / TAXAS"] == 2000.0
    assert categorias["ALUGUEL"] == 1000.0


def test_variacao_pct_compara_ultimo_mes_com_o_anterior():
    resultado = montar_resumo_despesas(_despesas(), meses=3, usar_mes_fechado=False)

    # Último mês (março, 200) contra o anterior (fevereiro, 1300).
    assert resultado["resumo"]["mes_atual"] == 200.0
    assert resultado["resumo"]["mes_anterior"] == 1300.0
    assert round(resultado["resumo"]["variacao_pct"], 2) == round((200 - 1300) / 1300 * 100, 2)


def test_agrupa_por_loja():
    resultado = montar_resumo_despesas(_despesas(), meses=3, usar_mes_fechado=False)

    por_loja = {item["loja"]: item["valor"] for item in resultado["por_loja"]}
    assert por_loja["Matriz"] == 2200.0
    assert por_loja["Filial"] == 800.0


def test_limite_categorias_agrupa_o_resto_em_demais():
    dados = pd.DataFrame([
        {"Loja": "Matriz", "categoria": f"CAT {i}", "Ano": 2023, "Mês": 1, "Valor": 100.0}
        for i in range(5)
    ])
    resultado = montar_resumo_despesas(dados, meses=1, limite_categorias=2, usar_mes_fechado=False)

    categorias = [item["categoria"] for item in resultado["por_categoria"]]
    assert categorias[-1] == "Demais"
    assert len(categorias) == 3
    demais = next(item for item in resultado["por_categoria"] if item["categoria"] == "Demais")
    assert demais["valor"] == 300.0


def test_resposta_vazia_sem_dados():
    resultado = montar_resumo_despesas(pd.DataFrame(), meses=6)
    assert resultado["serie_mensal"] == []
    assert resultado["resumo"]["total"] == 0.0
    assert resultado["resumo"]["variacao_pct"] is None


def test_detalhe_filtra_por_periodo_e_categoria():
    resultado = montar_detalhe_despesas(_despesas(), periodo="2023-01", categoria="ALUGUEL")

    assert resultado["total_itens"] == 1
    assert resultado["itens"][0]["valor"] == 500.0
    assert resultado["itens"][0]["loja"] == "Matriz"


def test_detalhe_ordena_do_maior_para_o_menor():
    resultado = montar_detalhe_despesas(_despesas())

    valores = [item["valor"] for item in resultado["itens"]]
    assert valores == sorted(valores, reverse=True)


def test_serie_mensal_categorias_soma_bate_com_o_total_do_mes():
    resultado = montar_resumo_despesas(_despesas(), meses=3, usar_mes_fechado=False)

    serie = resultado["serie_mensal_categorias"]
    assert set(serie["categorias"]) == {"FROTA / TAXAS", "ALUGUEL"}
    por_periodo = {ponto["periodo"]: ponto["valores"] for ponto in serie["pontos"]}
    assert sum(por_periodo["2023-01"].values()) == 1500.0
    assert sum(por_periodo["2023-02"].values()) == 1300.0
    assert sum(por_periodo["2023-03"].values()) == 200.0


def test_serie_mensal_categorias_agrupa_resto_em_outras():
    dados = pd.DataFrame([
        {"Loja": "Matriz", "categoria": f"CAT {i}", "Ano": 2023, "Mês": 1, "Valor": 100.0}
        for i in range(8)
    ])
    resultado = montar_resumo_despesas(dados, meses=1, usar_mes_fechado=False)

    serie = resultado["serie_mensal_categorias"]
    assert serie["categorias"][-1] == "Outras"
    assert len(serie["categorias"]) == 7  # 6 principais + Outras
    valores = serie["pontos"][0]["valores"]
    assert valores["Outras"] == 200.0  # 2 categorias fora das 6 principais


def test_curva_abc_categorias_classifica_por_grupo():
    resultado = montar_resumo_despesas(_despesas(), meses=3, usar_mes_fechado=False)

    curva = resultado["curva_abc_categorias"]
    assert curva["cortes"] == [30.0, 50.0, 60.0]
    grupos = {item["grupo"]: item for item in curva["grupos"]}
    assert sum(item["quantidade"] for item in curva["grupos"]) == 2  # 2 categorias no total
    assert sum(item["valor"] for item in curva["grupos"]) == 3000.0

    por_categoria = {item["categoria"]: item["grupo_abc"] for item in resultado["por_categoria"]}
    assert por_categoria["FROTA / TAXAS"] is not None
    assert por_categoria["FROTA / TAXAS"] in grupos


def test_tendencia_pct_positiva_quando_categoria_cresce_na_janela():
    dados = pd.DataFrame([
        {"Loja": "Matriz", "categoria": "ALUGUEL", "Ano": 2023, "Mês": 1, "Valor": 100.0},
        {"Loja": "Matriz", "categoria": "ALUGUEL", "Ano": 2023, "Mês": 2, "Valor": 300.0},
    ])
    resultado = montar_resumo_despesas(dados, meses=2, usar_mes_fechado=False)

    item = next(i for i in resultado["por_categoria"] if i["categoria"] == "ALUGUEL")
    assert item["tendencia_pct"] == 200.0  # de 100 para 300: +200%


def test_tendencia_pct_none_com_janela_de_um_mes():
    resultado = montar_resumo_despesas(_despesas(), meses=1, usar_mes_fechado=False)

    assert all(item["tendencia_pct"] is None for item in resultado["por_categoria"])


def test_variacao_anual_compara_com_mesmo_mes_do_ano_anterior():
    dados = pd.DataFrame([
        {"Loja": "Matriz", "categoria": "ALUGUEL", "Ano": 2022, "Mês": 3, "Valor": 400.0},
        {"Loja": "Matriz", "categoria": "ALUGUEL", "Ano": 2023, "Mês": 3, "Valor": 500.0},
    ])
    # Janela de 1 mês: o ano anterior fica fora dela, mas a variação anual
    # ainda precisa achá-lo no DataFrame completo.
    resultado = montar_resumo_despesas(dados, meses=1, usar_mes_fechado=False)

    assert resultado["resumo"]["mes_mesmo_periodo_ano_anterior"] == 400.0
    assert round(resultado["resumo"]["variacao_anual_pct"], 2) == 25.0


def test_variacao_anual_none_sem_dado_no_ano_anterior():
    resultado = montar_resumo_despesas(_despesas(), meses=3, usar_mes_fechado=False)

    assert resultado["resumo"]["mes_mesmo_periodo_ano_anterior"] is None
    assert resultado["resumo"]["variacao_anual_pct"] is None
