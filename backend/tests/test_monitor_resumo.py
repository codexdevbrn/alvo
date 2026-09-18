"""Cache do resumo do Monitoramento: quente é leitura de KB, frio é o summary todo.

A tela abre 46 empresas de uma vez. Com o cache fresco isso é ~0,4s; sem ele são
~18s de CPU (mais o download dos ~65 MB de summary, numa máquina em que o
OneDrive ainda não baixou). Estes testes travam as duas pontas: o que valida o
cache e o que o invalida.
"""

import gzip
import json
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import monitor_empresas as mon


def _gravar_summary(pasta, receita=1000.0, cmv=None, dias_com_venda=None):
    """Summary mínimo no formato que `_resumo_de_summary` consome."""
    mes = {"pid": 202601, "name": "jan/26", "rev": receita}
    if cmv is not None:
        mes["cmv"] = cmv
    if dias_com_venda is not None:
        mes["dias_com_venda"] = dias_com_venda
    summary = {
        "monthly": [mes],
        "maps": {"p": [202601], "s": ["Loja 1"], "c": [], "m": [], "d": []},
        "rows": [[0, 0, 0, 0, 0, 0, receita, 10]],
        "kpis": {"rev": receita, "qty": 10, "cmv": cmv or 0.0},
    }
    caminho = mon.caminho_summary_dashboard_gz(pasta)
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(summary, arquivo)
    return caminho


def test_sem_summary_nao_inventa_resumo(tmp_path):
    assert mon.obter_resumo_monitor(tmp_path) is None
    assert not mon.caminho_resumo_monitor(tmp_path).exists()


def test_grava_o_cache_na_primeira_leitura(tmp_path):
    _gravar_summary(tmp_path)

    resumo = mon.obter_resumo_monitor(tmp_path)

    assert resumo is not None
    assert mon.caminho_resumo_monitor(tmp_path).is_file()
    gravado = json.loads(mon.caminho_resumo_monitor(tmp_path).read_text(encoding="utf-8"))
    assert gravado["versao"] == mon.VERSAO_RESUMO


def test_cache_fresco_nao_abre_o_summary(tmp_path, monkeypatch):
    # É o ganho todo: com o cache válido, o summary (dezenas de MB) não é lido.
    _gravar_summary(tmp_path)
    mon.obter_resumo_monitor(tmp_path)

    def explodir(_caminho):
        raise AssertionError("o summary não deveria ser lido com cache fresco")

    monkeypatch.setattr(mon, "_ler_summary", explodir)
    assert mon.obter_resumo_monitor(tmp_path) is not None


def test_summary_reescrito_invalida_o_cache(tmp_path):
    # O lote noturno reescreve o summary toda madrugada; o resumo precisa
    # acompanhar, senão a tela mostra o mês anterior.
    caminho = _gravar_summary(tmp_path, receita=1000.0)
    mon.obter_resumo_monitor(tmp_path)

    _gravar_summary(tmp_path, receita=2000.0)
    os.utime(caminho, (caminho.stat().st_mtime + 60, caminho.stat().st_mtime + 60))

    resumo = mon.obter_resumo_monitor(tmp_path)

    assert resumo["serie"][0]["rev"] == 2000.0


def test_versao_antiga_do_cache_e_descartada(tmp_path):
    _gravar_summary(tmp_path)
    caminho_cache = mon.caminho_resumo_monitor(tmp_path)
    caminho_cache.write_text(json.dumps({"versao": 0, "serie": []}), encoding="utf-8")

    resumo = mon.obter_resumo_monitor(tmp_path)

    assert resumo["versao"] == mon.VERSAO_RESUMO
    assert resumo["serie"]


def test_cache_corrompido_nao_derruba_a_tela(tmp_path):
    _gravar_summary(tmp_path)
    mon.caminho_resumo_monitor(tmp_path).write_text("{ nao é json", encoding="utf-8")

    assert mon.obter_resumo_monitor(tmp_path) is not None


def test_lucro_bruto_e_receita_menos_cmv(tmp_path):
    _gravar_summary(tmp_path, receita=1000.0, cmv=400.0)

    resumo = mon.obter_resumo_monitor(tmp_path)

    assert resumo["tem_cmv"] is True
    assert resumo["serie"][0]["cmv"] == 400.0
    assert resumo["serie"][0]["lucro"] == 600.0
    assert resumo["totais"]["cmv"] == 400.0
    assert resumo["totais"]["lucro"] == 600.0


def test_sem_cmv_na_fonte_marca_tem_cmv_falso(tmp_path):
    _gravar_summary(tmp_path, receita=1000.0)

    resumo = mon.obter_resumo_monitor(tmp_path)

    assert resumo["tem_cmv"] is False
    assert resumo["serie"][0]["lucro"] == 1000.0


def test_montar_card_lucro_dia_usa_lucro_nao_receita(tmp_path):
    _gravar_summary(tmp_path, receita=1000.0, cmv=400.0)
    resumo = mon.obter_resumo_monitor(tmp_path)

    card = mon.montar_card("Empresa", resumo, metrica="lucro_dia", meses=1)

    dias_uteis = mon._dias_uteis_do_periodo(202601)
    assert card["valores"][0] == round(600.0 / dias_uteis, 2)


def test_montar_card_media_diaria_usa_dias_com_venda_quando_disponivel(tmp_path):
    """Empresa com data diária na fonte divide pelos dias com venda real, não pelo calendário."""
    _gravar_summary(tmp_path, receita=1000.0, dias_com_venda=10)
    resumo = mon.obter_resumo_monitor(tmp_path)

    assert resumo["serie"][0]["dias_venda"] == 10

    card = mon.montar_card("Empresa", resumo, metrica="receita_dia", meses=1)

    assert card["valores"][0] == round(1000.0 / 10, 2)
    assert card["media"] == round(1000.0 / 10, 2)
    assert card["dias_venda_janela"] == 10


# ---------------------------------------------------------------------------
# "% receita não harmonizada" e filtro por loja
# ---------------------------------------------------------------------------

def _gravar_summary_multiloja(pasta):
    """Duas lojas, dois produtos (um harmonizado, um não) e dois anos (jan/25,
    jan/26) — o mínimo pra testar não-harmonizado, variação anual e filtro de
    loja no mesmo fixture. `Loja 2` só vende em jan/26, de propósito: cobre o
    caso de loja sem ponto em todos os períodos da janela.
    """
    monthly = [
        {"pid": 202501, "name": "jan/25", "rev": 1000.0, "cmv": 0.0},
        {"pid": 202601, "name": "jan/26", "rev": 1500.0, "cmv": 0.0},
    ]
    rows = [
        # [p, s, c, m, d, r, rev, qty] — d=0 harmonizado, d=1 "Não harmonizados"
        [0, 0, 0, 0, 0, 0, 600.0, 5],   # jan/25, Loja 1, harmonizado
        [0, 0, 0, 0, 1, 0, 400.0, 3],   # jan/25, Loja 1, não harmonizado
        [1, 0, 0, 0, 0, 0, 800.0, 6],   # jan/26, Loja 1, harmonizado
        [1, 0, 0, 0, 1, 0, 200.0, 1],   # jan/26, Loja 1, não harmonizado
        [1, 1, 0, 0, 1, 0, 500.0, 2],   # jan/26, Loja 2, não harmonizado
    ]
    summary = {
        "monthly": monthly,
        "maps": {
            "p": [202501, 202601],
            "s": ["Loja 1", "Loja 2"],
            "c": ["Cliente A"],
            "m": ["Fabricante"],
            "d": ["Parafuso 10mm", "Não harmonizados"],
        },
        "rows": rows,
        "kpis": {"rev": 2500.0, "qty": 17, "cmv": 0.0},
    }
    caminho = mon.caminho_summary_dashboard_gz(pasta)
    with gzip.open(caminho, "wt", encoding="utf-8") as arquivo:
        json.dump(summary, arquivo)
    return caminho


def test_nao_harmonizado_totais_por_produto_e_receita(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    nh = resumo["nao_harmonizado"]
    assert nh["produtos_total"] == 2
    assert nh["produtos_nao_harmonizados"] == 1
    assert nh["receita_total"] == 2500.0
    assert nh["receita_nao_harmonizada"] == 1100.0  # 400 + 200 + 500


def test_nao_harmonizado_por_loja_isola_cada_loja(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    por_loja = resumo["nao_harmonizado_por_loja"]
    assert por_loja["Loja 1"]["receita_total"] == 2000.0
    assert por_loja["Loja 1"]["receita_nao_harmonizada"] == 600.0
    assert por_loja["Loja 2"]["receita_total"] == 500.0
    assert por_loja["Loja 2"]["receita_nao_harmonizada"] == 500.0
    assert por_loja["Loja 2"]["produtos_total"] == 1


def test_montar_card_nao_harmonizado_total_e_variacao_em_pontos(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    card = mon.montar_card("Empresa", resumo, metrica="nao_harmonizado", meses=2)

    assert card["total"] == round(1100.0 / 2500.0 * 100, 2)
    assert card["produtos_total"] == 2
    assert card["produtos_nao_harmonizados"] == 1
    assert card["receita_nao_harmonizada"] == 1100.0
    # jan/26 (46,67%) contra jan/25 (40,00%): +6,67 PONTOS percentuais, não +28%.
    assert card["variacao_pct"] == round(700.0 / 1500.0 * 100 - 40.0, 2)


def test_montar_card_nao_harmonizado_filtra_por_loja(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    card = mon.montar_card("Empresa", resumo, metrica="nao_harmonizado", meses=2, loja="Loja 1")

    assert card["total"] == round(600.0 / 2000.0 * 100, 2)
    assert card["receita_total"] == 2000.0
    assert card["receita_nao_harmonizada"] == 600.0


def test_montar_card_receita_filtra_por_loja(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    card_loja1 = mon.montar_card("Empresa", resumo, metrica="receita", meses=2, loja="Loja 1")
    card_loja2 = mon.montar_card("Empresa", resumo, metrica="receita", meses=2, loja="Loja 2")

    assert card_loja1["total"] == 2000.0
    # Loja 2 só vende no 2º período: 1 ponto na série, não 2.
    assert card_loja2["total"] == 500.0
    assert len(card_loja2["valores"]) == 1


def test_montar_card_loja_desconhecida_fica_vazio_sem_quebrar(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    card = mon.montar_card("Empresa", resumo, metrica="receita", meses=2, loja="Loja Fantasma")

    assert card["estado"] == "ok"
    assert card["valores"] == []
    assert card["total"] == 0.0


def test_montar_card_lucro_por_loja_fica_indisponivel(tmp_path):
    _gravar_summary_multiloja(tmp_path)
    resumo = mon.obter_resumo_monitor(tmp_path)

    card = mon.montar_card("Empresa", resumo, metrica="lucro", meses=2, loja="Loja 1")

    assert card.get("indisponivel_por_loja") is True
    assert "total" not in card
