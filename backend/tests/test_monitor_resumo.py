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
