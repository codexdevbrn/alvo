from datetime import date

import pandas as pd

from alertas_clientes import avaliar_alertas_clientes, normalizar_regras_alerta


def _linha(cliente: str, data: str, receita: float) -> dict:
    return {
        "Cliente": cliente,
        "Data_Venda_Diaria": data,
        "Receita": receita,
    }


def _primeiros_dias_uteis(mes: str, cliente: str, valor_dia: float, quantidade: int = 6) -> list[dict]:
    dias = pd.bdate_range(f"{mes}-01", periods=quantidade)
    return [_linha(cliente, dia.strftime("%Y-%m-%d"), valor_dia) for dia in dias]


def test_semana_flexivel_e_acumulado_por_mesmo_dia_util():
    linhas = []
    linhas += _primeiros_dias_uteis("2026-05", "Cliente A", 100)
    linhas += _primeiros_dias_uteis("2026-06", "Cliente A", 100)
    linhas += _primeiros_dias_uteis("2026-07", "Cliente A", 50)
    linhas += _primeiros_dias_uteis("2026-07", "Sem tag", 10)
    regra = {
        "id": "ritmo_alerta",
        "tag_id": "alerta",
        "ativa": True,
        "direcao": "queda",
        "limite_percentual": 20,
        "limite_valor": 100,
        "meses_historico": 2,
        "min_dias_uteis": 2,
    }

    resultado = avaliar_alertas_clientes(
        pd.DataFrame(linhas),
        {"Cliente A": ["alerta"]},
        [regra],
        data_referencia=date(2026, 7, 8),
    )

    assert resultado["disponivel"] is True
    assert resultado["semana_inicio"] == "2026-07-06"
    assert resultado["semana_fim"] == "2026-07-08"
    assert resultado["dias_uteis_decorridos"] == 6
    assert resultado["resumo"] == {
        "ativos": 1,
        "quedas": 1,
        "altas": 0,
        "clientes_avaliados": 1,
    }
    alerta = resultado["alertas"][0]
    assert alerta["cliente"] == "Cliente A"
    assert alerta["realizado"] == 300
    assert alerta["esperado"] == 600
    assert alerta["variacao_percentual"] == -50
    assert alerta["semana_realizado"] == 150
    assert alerta["semana_esperado"] == 300


def test_base_mensal_informa_que_data_diaria_e_necessaria():
    resultado = avaliar_alertas_clientes(
        pd.DataFrame({"Cliente": ["A"], "Receita": [100]}),
        {"A": ["alerta"]},
        [],
    )

    assert resultado["disponivel"] is False
    assert "DATA_VENDA" in resultado["motivo"]


def test_normalizacao_limita_regras_e_descarta_tag_inexistente():
    regras = normalizar_regras_alerta([
        {
            "tag_id": "alerta",
            "direcao": "inválida",
            "limite_percentual": -10,
            "meses_historico": 50,
            "min_dias_uteis": 0,
        },
        {"tag_id": "apagada"},
    ], {"alerta"})

    assert len(regras) == 1
    assert regras[0]["direcao"] == "queda"
    assert regras[0]["granularidade"] == "mensal"
    assert regras[0]["limite_percentual"] == 0
    assert regras[0]["meses_historico"] == 12
    assert regras[0]["min_dias_uteis"] == 2


def test_multiplas_granularidades_na_mesma_tag():
    linhas = []
    linhas += _primeiros_dias_uteis("2026-05", "Cliente A", 100)
    linhas += _primeiros_dias_uteis("2026-06", "Cliente A", 100)
    linhas += _primeiros_dias_uteis("2026-07", "Cliente A", 50)
    regras = [
        {
            "id": f"ritmo_{granularidade}",
            "tag_id": "alerta",
            "ativa": True,
            "granularidade": granularidade,
            "direcao": "queda",
            "limite_percentual": 20,
            "limite_valor": 20,
            "meses_historico": 2,
            "min_dias_uteis": 1,
        }
        for granularidade in ("diaria", "semanal", "mensal")
    ]

    resultado = avaliar_alertas_clientes(
        pd.DataFrame(linhas),
        {"Cliente A": ["alerta"]},
        regras,
        data_referencia=date(2026, 7, 8),
    )

    por_granularidade = {alerta["granularidade"]: alerta for alerta in resultado["alertas"]}
    assert set(por_granularidade) == {"diaria", "semanal", "mensal"}
    assert por_granularidade["diaria"]["realizado"] == 50
    assert por_granularidade["diaria"]["esperado"] == 100
    assert por_granularidade["semanal"]["realizado"] == 150
    assert por_granularidade["semanal"]["esperado"] == 300
    assert por_granularidade["mensal"]["realizado"] == 300
    assert por_granularidade["mensal"]["esperado"] == 600


def test_normalizacao_nao_quebra_com_numeros_invalidos():
    regras = normalizar_regras_alerta([{
        "tag_id": "alerta",
        "limite_percentual": "NaN",
        "limite_valor": "infinito",
        "meses_historico": "muitos",
        "min_dias_uteis": [],
    }], {"alerta"})

    assert regras[0]["limite_percentual"] == 20
    assert regras[0]["limite_valor"] == 0
    assert regras[0]["meses_historico"] == 6
    assert regras[0]["min_dias_uteis"] == 2
