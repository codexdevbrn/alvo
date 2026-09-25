"""GPS (aba Dispersão) na tela A precificar: perfil, distância, teto e recomendação."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import a_precificar as ap
import gps_dispersao as gd
import gps_logica

PLANILHA = Path.home() / "Downloads" / "Logica do GPS.xlsx"


def test_perfil_pela_taxa_de_retorno_nos_limites_do_dax():
    assert gd.perfil_por_taxa(-3.0) == "muito_conservador"
    assert gd.perfil_por_taxa(1.0) == "muito_conservador"
    assert gd.perfil_por_taxa(1.06) == "conservador"
    assert gd.perfil_por_taxa(3.5) == "conservador"
    assert gd.perfil_por_taxa(5.5) == "moderado"
    assert gd.perfil_por_taxa(7.5) == "agressivo"
    assert gd.perfil_por_taxa(7.51) == "muito_agressivo"


def test_tres_meses_fechados_sem_o_corrente():
    assert gd.meses_fechados(date(2026, 9, 25)) == [(2026, 6), (2026, 7), (2026, 8)]
    assert gd.meses_fechados(date(2026, 2, 1)) == [(2025, 11), (2025, 12), (2026, 1)]


def _descricao(nome, margem, participacao, perfil, margem_geral=31.28):
    receita = participacao * 1000.0
    cmv = receita * (1 - margem / 100)
    return gd.calcular_descricao(nome, receita, cmv, 100_000.0, margem_geral, perfil)


def test_distancia_ate_o_menor_e_cortada_pelo_teto():
    # Kit Embreagem na Gushcar (set/2026): dispersão −9,43, Dentro da Média,
    # faixa Conservador −6,95 a −5,90. MENOR = −5,90 (mais perto de zero).
    d = _descricao("Kit Embreagem", 31.28 - 9.43, 4.21, "conservador")
    assert d["classe"] == "dentro"
    assert d["regra"] == "MENOR"
    assert d["limite_alvo"] == pytest.approx(-5.90)
    assert d["distancia"] == pytest.approx(3.53)
    # Teto = largura da faixa: um degrau de perfil por rodada.
    assert d["teto"] == pytest.approx(1.05)
    assert d["aplicado"] == pytest.approx(1.05)
    assert d["perfil_item"] == "agressivo"


def test_maior_e_o_limite_mais_longe_de_zero_e_o_ajuste_aproxima_da_faixa():
    # Lubrificante Abaixo da Média no Conservador: faixa −4,25 a −3,25 → MAIOR = −4,25.
    d = _descricao("Lubrificante", 31.28 - 4.69, 5.0, "conservador")
    assert d["classe"] == "abaixo"
    assert d["regra"] == "MAIOR"
    assert d["limite_alvo"] == pytest.approx(-4.25)
    # Está abaixo do alvo: sobe, em vez de descer mais (o erro de somar o limite à margem).
    assert d["aplicado"] == pytest.approx(0.44)


def test_acima_da_media_vai_ate_a_borda_com_o_teto_do_cenario():
    # Mola: faixa Conservador +1,00 a +2,30, dispersão −0,20 → distância +1,20, cenário "até +1,00".
    mola = _descricao("Mola Suspensão", 31.28 - 0.20, 1.42, "conservador")
    assert mola["classe"] == "acima"
    assert mola["distancia"] == pytest.approx(1.20)
    assert mola["aplicado"] == pytest.approx(1.00)
    # Retentor acima da faixa (+3,80 a +5,20): desce, limitado pela largura (1,40).
    retentor = _descricao("Retentor", 31.28 + 7.89, 0.80, "conservador")
    assert retentor["aplicado"] == pytest.approx(-1.40)
    # Já dentro da faixa: nada a mexer.
    bomba = _descricao("Bomba D Água", 31.28 + 2.85, 1.83, "conservador")
    assert bomba["aplicado"] == 0.0


def test_muito_agressivo_usa_a_largura_da_faixa_vizinha_como_teto():
    # "Até −6,50" não tem largura; vale a da faixa Agressivo (−6,50 a −5,25).
    d = _descricao("Lubrificante", 31.28 - 2.0, 11.0, "muito_agressivo")
    assert d["faixa"] == [None, -6.5]
    assert d["regra"] == "MAIOR + 0,50"
    assert d["limite_alvo"] == pytest.approx(-6.0)
    assert d["aplicado"] == pytest.approx(-1.25)


@pytest.mark.parametrize(
    ("aplicado", "var_qtd", "sem_repasse", "sinalizado", "esperado"),
    [
        (1.0, -20.0, 0.0, True, "etapas"),
        (1.0, -5.0, 0.0, True, "reajustar"),
        (1.0, -5.0, 2.5, False, "reajustar"),
        (1.0, -5.0, 0.0, False, "oportunidade"),
        (-1.0, -20.0, 2.5, True, "segurar"),
        (-1.0, -20.0, 0.0, True, "reduzir"),
        (-1.0, -5.0, 0.0, True, "divergencia"),
        (-1.0, -5.0, 0.0, False, "manter"),
        (0.0, -50.0, 5.0, True, "manter"),
    ],
)
def test_recomendacao_cruza_gps_com_as_provas(aplicado, var_qtd, sem_repasse, sinalizado, esperado):
    assert gd.recomendar(aplicado, var_qtd, sem_repasse, sinalizado) == esperado


def test_subir_em_etapas_aplica_metade_e_segurar_nao_mexe_na_margem():
    assert gd.ajuste_agora("etapas", 0.70) == pytest.approx(0.35)
    assert gd.ajuste_agora("reajustar", 1.05) == pytest.approx(1.05)
    assert gd.ajuste_agora("segurar", -1.80) == 0.0
    assert gd.ajuste_agora("divergencia", -0.47) == 0.0


def test_taxa_de_retorno_tira_mercadoria_revenda_e_o_mes_corrente(tmp_path):
    movimento = tmp_path / "X_MOVIMENTO_ATUAL.parquet"
    controladoria = tmp_path / "X_CONTROLADORIA.parquet"
    pd.DataFrame({
        "ANO": [2026, 2026, 2026, 2026],
        "MES": [6, 7, 8, 9],
        "TOTAL": [1000.0, 1000.0, 1000.0, 9999.0],
        "CMV": [700.0, 700.0, 700.0, 0.0],
    }).to_parquet(movimento)
    pd.DataFrame({
        "ANO": [2026, 2026, 2026, 2026],
        "MES": [6, 7, 8, 9],
        "DESCRICAO_HARMONIZADA": ["Salários", "Mercadoria Revenda", "Dividendos", "Salários"],
        "VALOR": [600.0, 5000.0, 300.0, 9999.0],
    }).to_parquet(controladoria)
    perfil = gd.taxa_retorno(movimento, controladoria, date(2026, 9, 25))
    assert perfil["meses"] == ["2026-06", "2026-07", "2026-08"]
    assert perfil["margem"] == pytest.approx(30.0)
    assert perfil["despesas"] == pytest.approx(30.0)
    assert perfil["taxa_retorno"] == pytest.approx(0.0)
    assert perfil["perfil"] == "muito_conservador"


def test_sem_controladoria_nao_ha_perfil(tmp_path):
    assert gd.taxa_retorno(tmp_path / "m.parquet", None, date(2026, 9, 25)) is None


FIM = pd.Timestamp("2026-09-23")


def _vendas(codigo, descricao, *, preco_b, custo_b, preco_r, custo_r, qtd=2, fabricante="FAB"):
    linhas = []
    for i in range(120):
        dia = FIM - pd.Timedelta(days=119 - i)
        preco, custo = (preco_r, custo_r) if i >= 90 else (preco_b, custo_b)
        linhas.append({
            "data": dia, "codigo_produto": codigo, "fabricante": fabricante, "descricao": descricao,
            "segmento": "S", "receita": preco * qtd, "cmv": custo * qtd, "quantidade": float(qtd),
        })
    return linhas


def test_lista_por_produto_com_os_fabricantes_embaixo_e_gps_so_nas_descricoes_da_tabela():
    linhas = (
        # Sinalizado (custo subiu), descrição da tabela, dois fabricantes: um sinalizado, outro estável.
        _vendas("K1", "Kit Embreagem", preco_b=100, custo_b=70, preco_r=100, custo_r=80, fabricante="LUK")
        + _vendas("K2", "Kit Embreagem", preco_b=100, custo_b=70, preco_r=100, custo_r=70, fabricante="VALEO")
        # Sinalizado, fora da tabela: sem GPS.
        + _vendas("P1", "Pistão Motor", preco_b=100, custo_b=70, preco_r=100, custo_r=80)
        # Estável (não sinalizado), descrição da tabela: entra só pelo GPS.
        + _vendas("B1", "Bateria", preco_b=100, custo_b=90, preco_r=100, custo_r=90)
    )
    bruto = pd.DataFrame(linhas)
    mov = ap.preparar_movimento(bruto)
    skus, contexto = ap.calcular_skus(mov, ap.alvos_vigentes(None))
    agregado = gd.agregar_descricoes(bruto, contexto["inicio_base"], contexto["fim"])
    perfil = {"meses": ["2026-06", "2026-07", "2026-08"], "margem": 31.0, "despesas": 30.0,
              "taxa_retorno": 1.06, "perfil": "conservador", "rotulo": "Conservador"}
    gps = {**gd.calcular(agregado, "conservador"), "perfil": perfil,
           "receita_total": agregado["receita_total"],
           "receita_descricoes": float(agregado["por_descricao"]["receita"].sum())}
    resp = ap.montar_a_precificar(skus, contexto, gps)

    por_nome = {p["descricao"]: p for p in resp["produtos"]}
    kit = por_nome["Kit Embreagem"]
    assert kit["sinalizado"] is True
    assert kit["gps"] is not None
    assert "fabricante" not in kit
    # Os fabricantes abrem embaixo: o sinalizado primeiro, depois o que só o GPS aponta,
    # os dois com a mesma medida do GPS (a da descrição).
    assert [(f["fabricante"], f["sinalizado"]) for f in kit["fabricantes"]] == [("LUK", True), ("VALEO", False)]
    assert kit["fabricantes"][0]["gps"]["aplicado"] == kit["gps"]["aplicado"]
    assert kit["fabricantes"][1]["gps"]["aplicado"] == kit["gps"]["aplicado"]
    assert por_nome["Pistão Motor"]["gps"] is None
    assert por_nome["Bateria"]["sinalizado"] is False
    assert por_nome["Bateria"]["provas"] == {}
    assert por_nome["Bateria"]["perdido_dia"] == 0.0
    # Os sinalizados vêm antes; total_produtos continua contando só eles.
    assert [p["sinalizado"] for p in resp["produtos"]] == [True, True, False]
    assert resp["total_produtos"] == 2
    assert resp["resumo"]["produtos"] == 2
    bloco = resp["gps"]
    assert bloco["disponivel"] is True
    assert bloco["produtos_fora"] == 1
    assert sum(r["produtos"] for r in bloco["recomendacoes"]) == 2


def test_painel_do_produto_junta_os_fabricantes():
    linhas = (
        _vendas("K1", "Kit Embreagem", preco_b=100, custo_b=70, preco_r=100, custo_r=80, fabricante="LUK")
        + _vendas("K2", "Kit Embreagem", preco_b=100, custo_b=70, preco_r=100, custo_r=80, fabricante="VALEO")
    )
    mov = ap.preparar_movimento(pd.DataFrame(linhas))
    skus, _contexto = ap.calcular_skus(mov, ap.alvos_vigentes(None))
    assert ap.detalhe_par(mov, skus, "Kit Embreagem")["total_skus"] == 2
    assert ap.detalhe_par(mov, skus, "Kit Embreagem", "LUK")["total_skus"] == 1


def test_sem_gps_a_tela_segue_como_antes():
    linhas = _vendas("K1", "Kit Embreagem", preco_b=100, custo_b=70, preco_r=100, custo_r=80)
    mov = ap.preparar_movimento(pd.DataFrame(linhas))
    skus, contexto = ap.calcular_skus(mov, ap.alvos_vigentes(None))
    resp = ap.montar_a_precificar(skus, contexto, {"motivo": "sem Controladoria"})
    assert resp["gps"] == {"disponivel": False, "motivo": "sem Controladoria"}
    assert resp["produtos"][0]["gps"] is None
    assert resp["produtos"][0]["fabricantes"][0]["gps"] is None


@pytest.mark.skipif(not PLANILHA.exists(), reason="planilha do GPS não está nesta máquina")
def test_tabela_embutida_confere_com_a_planilha():
    assert gps_logica.ler_planilha(PLANILHA) == gps_logica.PRODUTOS
