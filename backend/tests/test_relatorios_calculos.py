"""Regressões contábeis dos relatórios executivos.

Os valores são pequenos e controlados para que cada resultado possa ser
recalculado sem depender da mesma implementação usada pelo motor.
"""

import pandas as pd

from engine.analise_funil import (
    classificar_faixas,
    comparativo_receita_ano_anterior,
    gerar_analises_completas,
    produtos_alta_e_queda,
    top_fabricantes,
    top_produtos,
)


def _linha(data, cliente, produto, fabricante, receita, qtd):
    data = pd.Timestamp(data)
    return {
        "Data_Venda": data,
        "Cliente": cliente,
        "descricao": produto,
        "NOME_FABRICANTE": fabricante,
        "Receita": float(receita),
        "QTD": float(qtd),
        "Periodo_Mensal": data.strftime("%Y-%m"),
        "Periodo_Trimestral": f"{data.year}-T{(data.month - 1) // 3 + 1}",
        "Periodo_Semestral": f"{data.year}-S{1 if data.month <= 6 else 2}",
        "Periodo_Anual": str(data.year),
    }


def _base_controlada():
    return pd.DataFrame([
        _linha("2025-01-15", "A", "P1", "F1", 100, 10),
        _linha("2025-01-15", "B", "P2", "F2", 80, 8),
        _linha("2025-02-15", "A", "P1", "F1", 120, 12),
        _linha("2025-02-15", "B", "P2", "F2", 40, 4),
        _linha("2026-01-15", "A", "P1", "F1", 200, 20),
        _linha("2026-01-15", "B", "P2", "F2", 50, 5),
        _linha("2026-01-15", "C", "P3", "F3", 90, 9),
        _linha("2026-02-15", "A", "P1", "F1", 100, 10),
        _linha("2026-02-15", "B", "P2", "F2", 150, 15),
    ])


def test_rankings_comparativo_e_boletins_recalculados():
    df = _base_controlada()

    produtos = top_produtos(df).set_index("descricao")
    fabricantes = top_fabricantes(df).set_index("NOME_FABRICANTE")
    assert produtos.loc["P1", ["Receita", "QTD"]].tolist() == [520.0, 52.0]
    assert fabricantes.loc["F2", ["Receita", "QTD"]].tolist() == [320.0, 32.0]
    assert produtos["Receita"].is_monotonic_decreasing
    assert fabricantes["Receita"].is_monotonic_decreasing

    comparativo = comparativo_receita_ano_anterior(df, "Mensal").set_index("descricao")
    assert comparativo.loc["P1", "Receita_Ano_Anterior"] == 120.0
    assert comparativo.loc["P1", "Receita_Ano_Atual"] == 100.0
    assert comparativo.loc["P1", "Ganho_Perda"] == -20.0
    assert round(comparativo.loc["P1", "Desempenho_Pct"], 2) == -16.67
    assert round(comparativo["Participacao_Ano_Atual_Pct"].sum(), 8) == 100.0
    assert round(comparativo["Participacao_Ano_Anterior_Pct"].sum(), 8) == 100.0

    altas, quedas = produtos_alta_e_queda(df, "Mensal")
    assert altas.set_index("descricao").loc["P2", "Variacao_Percentual"] == 200.0
    assert quedas.set_index("descricao").loc["P1", "Variacao_Percentual"] == -50.0
    assert quedas.set_index("descricao").loc["P3", "Variacao_Percentual"] == -100.0


def test_abc_e_orquestrador_fecham_conjunto_completo():
    df = _base_controlada()
    abc = classificar_faixas(df, "Mensal", "Cliente", cortes=(30, 50, 60))

    por_periodo = abc.groupby("Periodo")
    assert por_periodo["Percentual_Individual"].sum().round(8).eq(100.0).all()
    assert por_periodo["Percentual_Acumulado"].max().round(8).eq(100.0).all()
    maiores = abc.sort_values(["Periodo", "Receita"], ascending=[True, False]).groupby("Periodo").first()
    assert maiores["Faixa_ABC"].eq("Grupo 1").all()

    solicitadas = {
        "top_produtos", "top_fabricantes", "comparativo_receita",
        "poder_compra_clientes", "evolucao_produtos", "alertas_queda",
        "erosao_clientes", "sem_venda", "abc", "abc_produtos",
        "migracao_abc", "produtos_em_alta", "produtos_em_queda",
        "clientes_queda_qtd", "correlacao_produto_cliente",
        "impacto_financeiro_churn",
    }
    resultados = gerar_analises_completas(
        df,
        ["Mensal"],
        chaves_solicitadas=solicitadas,
        excluir_periodo_atual=False,
        periodos_queda_consecutiva=1,
        reducao_minima_erosao=0,
        reducao_minima_sem_venda=0,
    )["Mensal"]

    esperadas = solicitadas | {"migracao_resumo", "migracao_score_clientes"}
    assert set(resultados) == esperadas
    for chave, tabela in resultados.items():
        assert isinstance(tabela, pd.DataFrame), chave
        for coluna in tabela.select_dtypes(include="number"):
            assert (~tabela[coluna].isin([float("inf"), float("-inf")])).all(), f"{chave}.{coluna}"
