"""Tela Precificação (a precificar): provas, referência, lucro perdido, ordem e
agrupamento por descrição × fabricante."""

from __future__ import annotations

import pandas as pd
import pytest

import a_precificar as ap

FIM = pd.Timestamp("2026-09-23")


def _vendas(codigo, *, preco_b, custo_b, qtd_b, preco_r, custo_r, qtd_r,
            fabricante="FAB", segmento="S", descricao=None):
    """Uma venda por dia: 90 dias de base e 30 de recente, terminando em FIM.

    Sem `descricao`, cada SKU vira o próprio par (`Item <codigo>`)."""
    linhas = []
    for i in range(120):
        dia = FIM - pd.Timedelta(days=119 - i)
        recente = i >= 90
        preco, custo, qtd = (preco_r, custo_r, qtd_r) if recente else (preco_b, custo_b, qtd_b)
        linhas.append({
            "data": dia, "codigo_produto": codigo, "fabricante": fabricante,
            "descricao": descricao or f"Item {codigo}", "segmento": segmento,
            "receita": preco * qtd, "cmv": custo * qtd, "quantidade": float(qtd),
        })
    return linhas


def _calcular(linhas, dump=None):
    mov = ap.preparar_movimento(pd.DataFrame(linhas))
    skus, contexto = ap.calcular_skus(mov, ap.alvos_vigentes(dump))
    return mov, skus, ap.montar_a_precificar(skus, contexto)


def test_custo_sem_repasse_derruba_margem_e_entra_com_duas_provas():
    linhas = _vendas("A1", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2)
    mov, skus, resp = _calcular(linhas)
    par = resp["pares"][0]
    assert (par["descricao"], par["fabricante"]) == ("Item A1", "FAB")
    assert par["provas"] == {"margem": 1, "custo": 1}
    assert par["margem_base"] == pytest.approx(30.0)
    assert par["margem_recente"] == pytest.approx(20.0)
    # Sem alvo, a referência é a margem da base.
    assert par["referencia"] == pytest.approx(30.0)
    # 2 un/dia × (114,29 − 100): preço que devolve 30% com custo 80.
    assert par["perdido_dia"] == pytest.approx(2 * (80 / 0.7 - 100), abs=0.01)
    sku = ap.detalhe_par(mov, skus, "Item A1", "FAB")["skus"][0]
    assert sku["codigo"] == "A1"
    assert sku["provas"] == ["margem", "custo"]
    assert sku["preco_sugerido"] == pytest.approx(80 / 0.7, abs=0.01)


def test_item_estavel_nao_entra():
    linhas = _vendas("OK", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=70, qtd_r=2)
    _mov, _skus, resp = _calcular(linhas)
    assert resp["pares"] == []
    assert resp["resumo"]["skus"] == 0


def test_alvo_do_dump_vira_referencia_e_prova():
    linhas = _vendas("A1", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=70, qtd_r=2)
    dump = pd.DataFrame({
        "codigo": ["A1", "A1"],
        "margem_alvo": [40.0, 35.0],
        "data_exportacao": ["2026-05-01 10:00", "2026-06-01 10:00"],
    })
    _mov, _skus, resp = _calcular(linhas, dump)
    par = resp["pares"][0]
    # Vale o alvo mais recente.
    assert par["alvo"] == pytest.approx(35.0)
    assert par["dia_alvo"] == "2026-06-01"
    assert par["provas"] == {"alvo": 1}
    assert par["gap"] == pytest.approx(-5.0)


def test_queda_de_volume_e_prova_mas_sozinha_nao_basta_sem_lucro_perdido():
    # Volume caiu à metade, margem igual e sem alvo: nada a ganhar mudando preço.
    linhas = _vendas("V", preco_b=100, custo_b=70, qtd_b=4, preco_r=100, custo_r=70, qtd_r=2)
    _mov, skus, resp = _calcular(linhas)
    assert bool(skus.loc["V", "p_volume"])
    assert resp["pares"] == []


def test_venda_esparsa_fica_fora():
    linhas = _vendas("R", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=90, qtd_r=2)
    # Só um dia de venda na janela recente: menos que o mínimo.
    linhas = [l for l in linhas if l["data"] < FIM - pd.Timedelta(days=29) or l["data"] == FIM]
    for l in linhas:
        if l["data"] == FIM:
            l["quantidade"], l["receita"], l["cmv"] = 1.0, 100.0, 90.0
    _mov, _skus, resp = _calcular(linhas)
    assert resp["pares"] == []


def test_ordem_pesa_curva_e_provas():
    grande = _vendas("GRANDE", preco_b=100, custo_b=70, qtd_b=50, preco_r=100, custo_r=70, qtd_r=50)
    # Mesmo lucro perdido nos dois pequenos; o de mais provas vem antes.
    uma = _vendas("UMA", preco_b=100, custo_b=70, qtd_b=2, preco_r=97, custo_r=70, qtd_r=2)
    duas = _vendas("DUAS", preco_b=100, custo_b=70, qtd_b=2, preco_r=97, custo_r=70, qtd_r=2)
    dump = pd.DataFrame({"codigo": ["DUAS"], "margem_alvo": [30.0], "data_exportacao": ["2026-06-01"]})
    _mov, _skus, resp = _calcular(grande + uma + duas, dump)
    assert [p["descricao"] for p in resp["pares"]] == ["Item DUAS", "Item UMA"]


def test_linha_sem_segmento_fica_fora_como_no_price():
    linhas = _vendas("X", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2, segmento=None)
    _mov, _skus, resp = _calcular(linhas)
    assert resp["pares"] == []


def test_skus_do_mesmo_par_viram_uma_linha():
    # Dois SKUs sinalizados e um estável na mesma descrição × fabricante.
    a = _vendas("A", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2, descricao="Filtro")
    b = _vendas("B", preco_b=50, custo_b=35, qtd_b=4, preco_r=50, custo_r=40, qtd_r=4, descricao="Filtro")
    c = _vendas("C", preco_b=10, custo_b=7, qtd_b=2, preco_r=10, custo_r=7, qtd_r=2, descricao="Filtro")
    mov, skus, resp = _calcular(a + b + c)
    assert len(resp["pares"]) == 1
    par = resp["pares"][0]
    assert (par["descricao"], par["skus"], par["skus_total"]) == ("Filtro", 2, 3)
    assert par["provas"] == {"margem": 2, "custo": 2}
    # Margem pela soma: (400 − 320) / 400 nos 30 dias recentes dos dois sinalizados.
    assert par["margem_recente"] == pytest.approx(20.0)
    assert par["perdido_dia"] == pytest.approx(
        2 * (80 / 0.7 - 100) + 4 * (40 / 0.7 - 50), abs=0.02,
    )
    detalhe = ap.detalhe_par(mov, skus, "Filtro", "FAB")
    assert [s["codigo"] for s in detalhe["skus"]] == ["A", "B"]
    assert detalhe["total_skus"] == 2


def test_fabricantes_somam_lucro_perdido_e_participacao():
    a = _vendas("A", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2, fabricante="F1")
    b = _vendas("B", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2, fabricante="F1")
    c = _vendas("C", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=70, qtd_r=2, fabricante="F2")
    _mov, _skus, resp = _calcular(a + b + c)
    assert [f["nome"] for f in resp["fabricantes"]] == ["F1"]
    f1 = resp["fabricantes"][0]
    assert (f1["pares"], f1["skus"]) == (2, 2)
    assert f1["part_receita"] == pytest.approx(200 / 3, abs=0.01)
    assert resp["resumo"]["perdido_dia"] == pytest.approx(f1["perdido_dia"], abs=0.02)


def test_corte_d1_tira_dias_posteriores():
    linhas = _vendas("A1", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2)
    mov = ap.preparar_movimento(pd.DataFrame(linhas), data_corte=FIM - pd.Timedelta(days=5))
    assert mov["dia"].max() == FIM - pd.Timedelta(days=5)


def test_serie_semanal_e_margem_do_conjunto():
    a = _vendas("A", preco_b=100, custo_b=70, qtd_b=2, preco_r=100, custo_r=80, qtd_r=2)
    b = _vendas("B", preco_b=10, custo_b=5, qtd_b=2, preco_r=10, custo_r=5, qtd_r=2)
    mov = ap.preparar_movimento(pd.DataFrame(a + b))
    semanas = ap.serie_semanal(mov, {"A", "B"})
    assert len(semanas) <= ap.SEMANAS_ITEM + 1
    # Última semana: receita 220/dia, CMV 170/dia.
    assert semanas[-1]["margem"] == pytest.approx(50 / 220 * 100, abs=0.01)
    assert ap.serie_semanal(mov, {"NAO_EXISTE"}) == []
