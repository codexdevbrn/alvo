import pytest
import pandas as pd
import numpy as np

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from engine.analise_funil import (
    _tendencia_percentual,
    poder_compra_agregado,
    classificar_clientes_agregado,
    tendencia_produtos,
    produtos_alta_e_queda,
    clientes_queda_quantidade,
    erosao_clientes_por_produto,
    sem_venda_clientes,
    impacto_financeiro_churn,
    calcular_frequencia,
    calcular_renuncia,
    classificar_faixas
)

def test_tendencia_percentual():
    assert _tendencia_percentual(pd.Series([100])) == 0.0
    assert _tendencia_percentual(pd.Series([100, 200])) == 100.0
    assert _tendencia_percentual(pd.Series([100, 100, 300, 300])) == 200.0
    assert _tendencia_percentual(pd.Series([100, 100, 100, 200, 200, 200])) == 100.0
    assert _tendencia_percentual(pd.Series([0, 0, 0, 100, 100, 100])) == 0.0
    # Um pico na primeira janela não pode inverter a direção visível: o último
    # período está acima do primeiro, portanto a tendência precisa ser positiva.
    serie_com_pico = pd.Series([638, 590, 710, 560, 600, 575, 615, 530, 570, 615, 667])
    assert round(_tendencia_percentual(serie_com_pico), 2) == 4.55

def test_poder_compra_agregado(mocker):
    df_mock = pd.DataFrame({
        "Cliente": ["A", "A", "A", "A", "A", "B", "B"],
        "Periodo_Mensal": ["2025-01", "2025-02", "2025-03", "2025-04", "2025-05", "2025-01", "2025-02"],
        "Receita": [100, 50, 200, 10, 300, 1000, 2000]
    })
    
    df_classificacao = pd.DataFrame({
        "Cliente": ["A", "B"],
        "Percentual_Acumulado": [10.0, 90.0],
        "Faixa": ["A", "C"]
    })
    mocker.patch("engine.analise_funil.classificar_clientes_agregado", return_value=df_classificacao)
    
    resultado = poder_compra_agregado(df_mock)
    
    poder_a = resultado.loc[resultado["Cliente"] == "A", "Poder_De_Compra"].iloc[0]
    assert poder_a == 200.0
    
    poder_b = resultado.loc[resultado["Cliente"] == "B", "Poder_De_Compra"].iloc[0]
    assert poder_b == 1500.0

def test_tendencia_produtos():
    df = pd.DataFrame({
        "descricao": ["Prod A", "Prod A", "Prod A", "Prod B", "Prod B", "Prod B"],
        "Periodo_Mensal": ["2025-01", "2025-02", "2025-03", "2025-01", "2025-02", "2025-03"],
        "Receita": [100.0, 90.0, 80.0, 10.0, 20.0, 30.0],
        "QTD": [10, 9, 8, 1, 2, 3]
    })
    
    evolucao, alertas = tendencia_produtos(df, granularidade="Mensal", periodos_queda_consecutiva=2)
    
    evol_a = evolucao[evolucao["descricao"] == "Prod A"]
    tendencia_a = evol_a["Tendencia_Pct"].iloc[0]
    assert round(tendencia_a, 2) == -20.0
    
    assert len(alertas) == 1
    assert alertas["descricao"].iloc[0] == "Prod A"
    assert alertas["Periodos_Consecutivos_Em_Queda"].iloc[0] == 2
    assert alertas["Receita_Primeiro_Periodo"].iloc[0] == 100.0
    assert alertas["Receita_Ultimo_Periodo"].iloc[0] == 80.0

def test_produtos_alta_e_queda():
    df = pd.DataFrame({
        "descricao": ["Prod A", "Prod A", "Prod B", "Prod B", "Prod C"],
        "Periodo_Mensal": ["2025-01", "2025-02", "2025-01", "2025-02", "2025-01"],
        "Receita": [100.0, 50.0, 10.0, 100.0, 200.0],
        "QTD": [2, 1, 1, 10, 5],
        "Data_Venda": pd.to_datetime(["2025-01-01", "2025-02-01", "2025-01-01", "2025-02-01", "2025-01-01"])
    })
    
    em_alta, em_queda = produtos_alta_e_queda(df, granularidade="Mensal")
    
    assert len(em_alta) == 1
    assert em_alta["descricao"].iloc[0] == "Prod B"
    assert em_alta["Variacao_Percentual"].iloc[0] == 900.0
    
    assert len(em_queda) == 2
    assert em_queda["descricao"].iloc[0] == "Prod C"
    assert em_queda["Variacao_Percentual"].iloc[0] == -100.0
    
    assert em_queda["descricao"].iloc[1] == "Prod A"
    assert em_queda["Variacao_Percentual"].iloc[1] == -50.0


def test_clientes_queda_quantidade_exibe_diferenca_antes_depois():
    df = pd.DataFrame({
        "Cliente": ["Cliente A", "Cliente A", "Cliente B", "Cliente B"],
        "descricao": ["Produto", "Produto", "Produto", "Produto"],
        "Periodo_Trimestral": ["2025-T1", "2025-T2", "2025-T1", "2025-T2"],
        "Receita": [1000.0, 600.0, 500.0, 750.0],
        "QTD": [10, 6, 5, 7],
    })

    resultado = clientes_queda_quantidade(df, granularidade="Trimestral")

    assert len(resultado) == 1
    assert resultado["Cliente"].iloc[0] == "Cliente A"
    assert resultado["QTD_Periodo_Anterior"].iloc[0] == 10
    assert resultado["QTD_Periodo_Atual"].iloc[0] == 6
    assert resultado["Diferenca_QTD"].iloc[0] == -4

def test_erosao_clientes_por_produto():
    df = pd.DataFrame({
        "Cliente": ["Cli 1", "Cli 1", "Cli 2", "Cli 2"],
        "descricao": ["Prod A", "Prod A", "Prod A", "Prod B"],
        "Periodo_Mensal": ["2025-01", "2025-02", "2025-01", "2025-01"],
        "Receita": [100.0, 40.0, 200.0, 50.0],
        "QTD": [2, 1, 4, 1]
    })
    
    erosao = erosao_clientes_por_produto(df, granularidade="Mensal", reducao_minima_percentual=50.0)
    
    assert len(erosao) == 3
    assert erosao["Cliente"].iloc[0] == "Cli 2"
    assert erosao["descricao"].iloc[0] == "Prod A"
    assert erosao["Reducao_Receita"].iloc[0] == 200.0
    assert erosao["Reducao_Percentual"].iloc[0] == 100.0
    assert erosao["Parou_De_Comprar"].iloc[0] == True
    
    cli_1 = erosao[erosao["Cliente"] == "Cli 1"].iloc[0]
    assert cli_1["Reducao_Receita"] == 60.0
    assert cli_1["Reducao_Percentual"] == 60.0
    assert cli_1["Parou_De_Comprar"] == False

def test_sem_venda_clientes():
    df = pd.DataFrame({
        "Cliente": ["Cli A", "Cli A", "Cli B"],
        "Periodo_Mensal": ["2025-01", "2025-02", "2025-01"],
        "Receita": [1000.0, 50.0, 500.0]
    })
    
    resultado = sem_venda_clientes(df, granularidade="Mensal", reducao_minima_percentual=90.0)
    
    assert len(resultado) == 2
    assert resultado["Cliente"].iloc[0] == "Cli A"
    assert resultado["Reducao_Receita"].iloc[0] == 950.0
    assert resultado["Reducao_Percentual"].iloc[0] == 95.0
    
    assert resultado["Cliente"].iloc[1] == "Cli B"
    assert resultado["Reducao_Receita"].iloc[1] == 500.0
    assert resultado["Reducao_Percentual"].iloc[1] == 100.0
    assert resultado["Parou_De_Comprar"].iloc[1] == True

def test_impacto_financeiro_churn():
    df = pd.DataFrame({
        "Periodo_Mensal": ["2025-01", "2025-02"],
        "Receita": [1000.0, 500.0] # Total do mês 1 e 2
    })
    
    erosao_df = pd.DataFrame({
        "Reducao_Percentual": [100.0, 50.0],
        "Reducao_Receita": [200.0, 100.0]
    })
    
    resultado = impacto_financeiro_churn(df, erosao_df, granularidade="Mensal")
    assert resultado["Maior_Retracao_Individual_Pct"].iloc[0] == 100.0
    assert resultado["Receita_Sob_Risco"].iloc[0] == 300.0 # 200 + 100
    assert resultado["Variacao_Global_Periodo_Pct"].iloc[0] == -50.0 # 1000 pra 500

def test_frequencia_e_renuncia():
    df = pd.DataFrame({
        "Cliente": ["A", "A", "A", "A"],
        "Periodo_Mensal": ["2025-01", "2025-02", "2025-03", "2025-04"],
        "Receita": [100.0, 0.0, 50.0, 20.0]
    })
    
    freq = calcular_frequencia(df, granularidade="Mensal")
    # Cliente A:
    # 01: receita 100 -> simples = 1, ac = 1
    # 03: receita 50 -> simples = 1, ac = 2
    # 04: receita 20 -> simples = 1, ac = 3
    # Mês 02 não entra na tabela de frequencia (porque vendas_positivas o exclui).
    assert freq["Frequencia_Simples"].tolist() == [1, 1, 1]
    assert freq["Frequencia_Acumulada"].tolist() == [1, 2, 3]
    
    renuncia = calcular_renuncia(df, granularidade="Mensal")
    # 01: sem anterior -> renuncia = 0
    # 02: anterior 100, atual 0 -> renuncia = 100. Pct = 100%
    # 03: anterior 0, atual 50 -> renuncia = 0 (aumentou)
    # 04: anterior 50, atual 20 -> renuncia = 30. Pct = 60%
    assert renuncia["Renuncia"].tolist() == [0.0, 100.0, 0.0, 30.0]
    assert renuncia["Renuncia_Percentual"].tolist() == [0.0, 100.0, 0.0, 60.0]
    assert renuncia["Renuncia_Acumulada"].tolist() == [0.0, 100.0, 100.0, 130.0]

def test_classificar_faixas():
    df = pd.DataFrame({
        "Cliente": ["A", "B", "C"],
        "Periodo_Mensal": ["2025-01", "2025-01", "2025-01"],
        "Receita": [700.0, 200.0, 100.0]
    })
    # Total = 1000
    # A = 70%
    # B = 20%
    # C = 10%
    # Acumulados: A(70%), B(90%), C(100%). A faixa usa o acumulado ANTES
    # da entidade, garantindo que o maior cliente ocupe o primeiro grupo
    # mesmo quando sozinho ultrapassa o primeiro corte.
    
    res = classificar_faixas(df, cortes=(30.0, 50.0, 60.0), nomes_grupos=["Grupo 1", "Grupo 2", "Grupo 3"])
    
    faixa_a = res.loc[res["Cliente"] == "A", "Faixa_ABC"].iloc[0]
    assert faixa_a == "Grupo 1"
    
    faixa_b = res.loc[res["Cliente"] == "B", "Faixa_ABC"].iloc[0]
    assert faixa_b == "Demais" # Pq 90% > 60
    
    faixa_c = res.loc[res["Cliente"] == "C", "Faixa_ABC"].iloc[0]
    assert faixa_c == "Demais" # Pq 100% > 60
    
    # Se os cortes forem 70, 95, 100:
    res2 = classificar_faixas(df, cortes=(70.0, 95.0, 100.0), nomes_grupos=["G1", "G2", "G3"])
    assert res2.loc[res2["Cliente"] == "A", "Faixa_ABC"].iloc[0] == "G1"
    assert res2.loc[res2["Cliente"] == "B", "Faixa_ABC"].iloc[0] == "G2"
    # C começa em 90% acumulado, ainda dentro do corte de 95% de G2.
    assert res2.loc[res2["Cliente"] == "C", "Faixa_ABC"].iloc[0] == "G2"
