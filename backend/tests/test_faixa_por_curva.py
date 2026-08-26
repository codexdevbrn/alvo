"""Régua de corte: o número que a tela mostra é o que classifica.

A prévia exibe o acumulado INCLUSIVO. A régua anterior decidia pelo acumulado
antes da entidade, então um produto com acumulado 80,23% aparecia no Grupo 1 com
corte em 80% — certo pela regra, defeito aos olhos de quem lê a tabela.
"""

import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import engine.analise_funil as af


# Caso relatado na tela: o item que leva o acumulado a 80,23% com corte em 80%.
# A cauda é fatiada em pedaços menores que 0,63 para a curva_pareto não reordenar
# os três primeiros, e soma 100 para receita e percentual coincidirem.
RECEITAS_CASO_80 = [79.47, 0.76, 0.63] + [0.3828] * 50


def _curva(receitas):
    return af.curva_pareto(
        pd.Series(receitas, index=[f"E{i:03d}" for i in range(len(receitas))])
    )


def test_acumulado_igual_ao_corte_entra_na_faixa():
    # Quatro entidades de 25%: acumulados 25, 50, 75, 100.
    curva = _curva([25.0, 25.0, 25.0, 25.0])

    faixa = af.faixa_por_curva(curva, (50.0,))

    assert list(faixa) == ["Grupo 1", "Grupo 1", "Demais", "Demais"]


def test_quem_passa_do_corte_fica_em_demais():
    # Reproduz o caso relatado: com corte em 80%, o item que leva o acumulado a
    # 80,23% não pode aparecer no Grupo 1.
    curva = _curva(RECEITAS_CASO_80)

    faixa = af.faixa_por_curva(curva, (80.0,))
    acumulado = curva["Percentual_Acumulado"].round(2).tolist()

    assert acumulado[:3] == [79.47, 80.23, 80.86]
    assert faixa.iloc[0] == "Grupo 1"
    assert faixa.iloc[1] == "Demais"
    assert faixa.iloc[2] == "Demais"


def test_faixa_nunca_fica_vazia():
    # Uma entidade sozinha passa dos dois primeiros cortes. Nenhum grupo pode
    # nascer vazio: grupo em branco vira seção vazia no relatório.
    curva = _curva([60.0] + [0.1] * 400)

    contagens = af.contar_por_faixa(curva, (30.0, 50.0, 60.0))

    assert all(quantidade > 0 for quantidade in contagens[:3])
    assert contagens[0] == 1  # a dominante, forçada na primeira faixa
    assert sum(contagens) == 401


def test_acumulado_nan_fica_em_demais_sem_ocupar_faixa():
    # Balcão entra na tabela com acumulado NaN: está fora da segmentação e não
    # pode roubar a vaga que a garantia de faixa não-vazia reserva.
    curva = _curva([50.0, 30.0, 20.0])
    curva.loc["E000", "Percentual_Acumulado"] = float("nan")

    faixa = af.faixa_por_curva(curva, (60.0,))

    assert faixa.loc["E000"] == "Demais"
    assert faixa.loc["E001"] == "Grupo 1"


def test_curva_desordenada_classifica_igual():
    # faixa_por_curva não pode depender de o chamador entregar a curva ordenada.
    curva = _curva([50.0, 30.0, 15.0, 5.0])
    embaralhada = curva.iloc[[2, 0, 3, 1]]

    faixa = af.faixa_por_curva(embaralhada, (80.0,))

    assert faixa.loc["E000"] == "Grupo 1"
    assert faixa.loc["E001"] == "Grupo 1"
    assert faixa.loc["E002"] == "Demais"
    assert faixa.loc["E003"] == "Demais"


def test_previa_e_relatorio_usam_a_mesma_regua():
    # classificar_produtos_agregado (prévia) e classificar_faixas (relatório)
    # passam pela mesma função; o teste trava a concordância dos dois caminhos.
    df = pd.DataFrame(
        {
            "descricao": [f"P{i:03d}" for i in range(len(RECEITAS_CASO_80))],
            "Cliente": "X",
            "Receita": RECEITAS_CASO_80,
            "Periodo_Mensal": "2026-01",
        }
    )

    previa = af.classificar_produtos_agregado(df, 80.0).set_index("descricao")["Faixa"]
    relatorio = af.classificar_faixas(
        df, campo="descricao", cortes=(80.0,),
    ).set_index("descricao")["Faixa_ABC"]

    assert previa.to_dict() == relatorio.to_dict()
    # P000 leva 79,47%; P001 fecha em 80,23% e fica fora.
    assert previa["P000"] == "Grupo 1"
    assert previa["P001"] == "Demais"
