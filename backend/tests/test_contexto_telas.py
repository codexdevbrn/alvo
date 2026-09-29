"""Recortes das telas para a análise diária (``contexto_telas``)."""

from __future__ import annotations

from datetime import date

import contexto_telas
from contexto_telas import (
    montar_blocos_telas,
    recortar_clientes,
    recortar_estoque,
    recortar_precificacao,
    recortar_rentabilidade,
    recortar_vendedores,
)

HOJE = date(2026, 9, 29)


def _summary() -> dict:
    return {"monthly": [
        {"name": "jul/26", "pid": 202607, "rev": 1000.0, "cmv": 700.0},
        {"name": "ago/26", "pid": 202608, "rev": 2000.0, "cmv": 1500.0},
        {"name": "set/26", "pid": 202609, "rev": 500.0, "cmv": 300.0},  # mês corrente: fora
    ]}


def test_rentabilidade_so_meses_fechados_e_resultado_apos_despesas():
    bloco = recortar_rentabilidade(_summary(), {"2026-07": 100.0, "2026-08": 400.0}, hoje=HOJE)

    assert bloco["janela"] == "jul/26 a ago/26"
    assert bloco["lucro_bruto_periodo"] == 800.0
    assert bloco["margem_bruta_periodo_pct"] == 26.67
    ultimo = bloco["ultimo_mes"]
    assert (ultimo["mes"], ultimo["margem_bruta_pct"], ultimo["resultado_apos_despesas"]) == ("ago/26", 25.0, 100.0)
    assert bloco["margem_ultimo_mes_vs_periodo_pp"] == -1.67
    assert bloco["resultado_apos_despesas_periodo"] == 300.0
    assert bloco["margem_apos_despesas_periodo_pct"] == 10.0
    assert bloco["meses_sem_lancamento_de_despesa"] == []


def test_rentabilidade_sem_controladoria_nao_inventa_despesa():
    bloco = recortar_rentabilidade(_summary(), None, hoje=HOJE)

    assert bloco["despesas_disponiveis"] is False
    assert "resultado_apos_despesas_periodo" not in bloco
    assert bloco["serie_mensal"][0]["despesas"] is None


def test_rentabilidade_mes_sem_lancamento_fica_de_fora_da_soma():
    bloco = recortar_rentabilidade(_summary(), {"2026-07": 100.0}, hoje=HOJE)

    assert bloco["meses_com_despesa"] == 1
    assert bloco["resultado_apos_despesas_periodo"] == 200.0
    assert bloco["meses_sem_lancamento_de_despesa"] == ["ago/26"]


def test_rentabilidade_sem_cmv_fica_indisponivel():
    summary = {"monthly": [{"name": "ago/26", "pid": 202608, "rev": 10.0, "cmv": 0}]}
    assert recortar_rentabilidade(summary, None, hoje=HOJE) == {"disponivel": False, "motivo": "sem_cmv"}


def test_clientes_recorta_topo_e_junta_risco_do_diagnostico():
    painel = {
        "rotulo_periodo": "ago/26", "meses_media": 6,
        "resumo": {"clientes_ativos": 10.0, "perdidos": 3, "novos": 2, "saldo": -1},
        "concentracao": {"clientes_80": 4, "participacao_clientes_80": 40.0},
        "eventos": {"perdidos": [{"cliente": f"C{i}", "receita": 10 - i} for i in range(8)]},
        "top_clientes": [{"cliente": "A", "receita_atual": 5, "variacao": -30, "alerta": True},
                         {"cliente": "B", "receita_atual": 9, "variacao": 5, "alerta": False}],
        "score_migracao": {"disponivel": False},
        "potencial_compra": {"disponivel": True, "potencial_total": 100, "atual_total": 40, "variacao_total": -60,
                             "ranking": [{"cliente": "X", "potencial": 50, "atual": 45},
                                         {"cliente": "Y", "potencial": 40, "atual": 5}]},
    }
    diagnostico = {"impacto_churn": {"receita_sob_risco": 77.0},
                   "risco": {"disponivel": True, "clientes": [{"cliente": "Z", "perda_rs": 9, "parou_de_comprar": True}]}}

    bloco = recortar_clientes(painel, diagnostico)

    assert bloco["clientes_ativos"] == 10
    assert len(bloco["maiores_perdidos"]) == contexto_telas.TOPO
    assert [c["cliente"] for c in bloco["maiores_clientes_em_queda"]] == ["A"]
    assert [c["cliente"] for c in bloco["potencial_de_compra"]["maiores_lacunas"]] == ["Y", "X"]
    assert "migracao_de_faixa" not in bloco
    assert bloco["risco_de_churn"]["receita_sob_risco"] == 77.0
    assert bloco["risco_de_churn"]["clientes_com_maior_perda"][0]["parou_de_comprar"] is True


def test_telas_ausentes_viram_blocos_indisponiveis():
    assert recortar_clientes(None, None)["disponivel"] is False
    assert recortar_vendedores({"disponivel": True, "itens": []})["disponivel"] is False
    assert recortar_estoque(None, None)["disponivel"] is False
    assert recortar_precificacao(None, None)["disponivel"] is False


def test_estoque_com_quantidades_inteiras_e_compras():
    tela = {
        "periodo_inicio": "2026-03", "periodo_fim": "2026-08",
        "resumo": {"produtos": 3, "valor_estoque": 1000.0, "valor_parado": 250.0, "ruptura": 1},
        "ruptura_iminente": [{"sku": "S1", "nome": "Cera", "estoque": 24.0, "venda_media": 94.6667, "status": "rupture"}],
    }
    compras = {"total_compra": 321.0, "produtos_a_comprar": 2, "itens": [{"descricao": "Cera", "sugestao": 70.0}]}

    bloco = recortar_estoque(tela, compras)

    assert bloco["parcela_parada_pct"] == 25.0
    item = bloco["ruptura_iminente"][0]
    assert (item["estoque"], item["venda_media_mes"], item["situacao"]) == (24, 95, "Ruptura")
    assert bloco["compras_sugeridas"]["valor_total"] == 321.0
    assert bloco["compras_sugeridas"]["maiores_itens"][0]["sugestao_unidades"] == 70


def test_precificacao_ordena_por_lucro_perdido_e_so_familias_abaixo_do_alvo():
    a_precificar = {
        "resumo": {"produtos": 2, "perdido_dia": 30.0},
        "produtos": [
            {"descricao": "B", "perdido_dia": 10, "sinalizado": True},
            {"descricao": "A", "perdido_dia": 20, "sinalizado": True},
            {"descricao": "Só GPS", "perdido_dia": 99, "sinalizado": False},
        ],
        "gps": {"disponivel": True, "perfil": {"rotulo": "Moderado", "taxa_retorno": 4.2},
                "recomendacoes": [{"rotulo": "Reajustar", "produtos": 3}, {"rotulo": "Manter", "produtos": 0}]},
    }
    pos = {"kpis": {"rodadas": 2, "margem_antes": 30.0, "margem_depois": 29.0},
           "linhas": [{"nome": "F1", "gap_pp": -5}, {"nome": "F2", "gap_pp": 3}, {"nome": "F3", "gap_pp": -9}]}

    bloco = recortar_precificacao(a_precificar, pos)

    assert [p["produto"] for p in bloco["a_precificar"]["maiores_perdas"]] == ["A", "B"]
    assert bloco["gps"]["perfil"] == "Moderado"
    assert [r["recomendacao"] for r in bloco["gps"]["recomendacoes"]] == ["Reajustar"]
    assert [f["familia"] for f in bloco["pos_precificacao"]["familias_mais_abaixo_do_alvo"]] == ["F3", "F1"]


def test_montar_blocos_isola_falha_de_despesas():
    def despesas_quebradas(_empresa, _meses):
        raise OSError("OneDrive travado")

    blocos = montar_blocos_telas(
        "Empresa", _summary(), hoje=HOJE, buscar=lambda _e: {}, despesas=despesas_quebradas,
    )

    assert blocos["rentabilidade"]["disponivel"] is True
    assert blocos["rentabilidade"]["despesas_disponiveis"] is False
    assert blocos["clientes"]["disponivel"] is False
