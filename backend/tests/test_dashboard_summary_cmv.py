"""CMV por linha em `rows` — base do lucro bruto (receita - CMV) que o Dashboard
exibe como valor principal (ver dashboard/src/types/dashboard.ts::margemLinha).
"""

import pandas as pd

from dashboard_summary import aplicar_cortes_no_summary, gerar_summary


def _df():
    return pd.DataFrame({
        "Loja": ["Matriz", "Matriz"],
        "Cliente": ["Alice", "Bob"],
        "NOME_FABRICANTE": ["Wega", "Wega"],
        "descricao": ["Filtro", "Pastilha"],
        "Código de referêcia": ["R1", "R2"],
        "Data_Venda": pd.to_datetime(["2026-01-15", "2026-01-20"]),
        "Receita": [100.0, 50.0],
        "QTD": [1, 2],
        "CMV": [40.0, 20.0],
    })


def test_gerar_summary_inclui_cmv_por_linha():
    summary = gerar_summary(_df())

    assert len(summary["rows"][0]) == 9
    cmv_por_linha = {tuple(row[:6]): row[8] for row in summary["rows"]}
    assert sum(cmv_por_linha.values()) == 60.0
    assert summary["kpis"]["cmv"] == 60.0
    assert summary["monthly"][0]["cmv"] == 60.0


def test_gerar_summary_sem_coluna_cmv_zera():
    df = _df().drop(columns=["CMV"])
    summary = gerar_summary(df)

    assert all(row[8] == 0.0 for row in summary["rows"])
    assert summary["kpis"]["cmv"] == 0.0


def test_aplicar_cortes_recalcula_cmv_exato_por_linha_mantida():
    summary = gerar_summary(_df())

    saida = aplicar_cortes_no_summary(summary, {"clientes_excluidos": ["Alice"]})

    # Só a linha do Bob (CMV=20) sobrevive — nada de aproximação proporcional.
    assert saida["kpis"]["cmv"] == 20.0
    assert saida["monthly"][0]["cmv"] == 20.0
