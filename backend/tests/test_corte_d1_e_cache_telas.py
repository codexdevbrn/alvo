"""Corte D-1 da base e cache em disco das telas (preparado pelo lote da manhã)."""

from datetime import date, timedelta

import pandas as pd
import pytest

import main  # noqa: F401  (insere a raiz do projeto no sys.path)
import cache_telas
import dashboard_summary as ds
from engine import analise_funil as af


def _df(datas):
    return pd.DataFrame({
        "Data_Venda_Diaria": pd.to_datetime(datas, format="mixed"),
        "Receita Acumulada 11 Meses": [1.0] * len(datas),
    })


def test_corte_padrao_e_ontem(monkeypatch):
    monkeypatch.delenv(af.VAR_DATA_CORTE, raising=False)
    assert af.data_corte_padrao() == date.today() - timedelta(days=1)


def test_corte_pode_ser_forcado_por_variavel(monkeypatch):
    monkeypatch.setenv(af.VAR_DATA_CORTE, "2026-09-10")
    assert af.data_corte_padrao() == date(2026, 9, 10)


def test_cortar_ate_mantem_o_dia_do_corte_e_tira_os_seguintes():
    df = _df(["2026-09-22", "2026-09-23 18:30", "2026-09-24 08:00", None])
    cortado = af.cortar_ate(df, date(2026, 9, 23))
    # O dia inteiro do corte fica (inclusive 18h30); o dia seguinte sai; sem data fica.
    assert cortado["Data_Venda_Diaria"].dt.strftime("%Y-%m-%d").fillna("-").tolist() == [
        "2026-09-22", "2026-09-23", "-",
    ]


def test_cortar_ate_sem_coluna_de_data_nao_mexe():
    df = pd.DataFrame({"Ano": [2026], "Mês": [9]})
    assert af.cortar_ate(df, date(2026, 9, 23)) is df


def test_summary_de_outro_corte_nao_vale(tmp_path):
    fonte = tmp_path / "fonte.parquet"
    fonte.write_text("x", encoding="utf-8")
    trabalho = tmp_path / "trab"
    trabalho.mkdir()
    ds.gravar_summary_dashboard(trabalho, {"rows": []})
    (trabalho / ds.NOME_VERSAO_SUMMARY).write_text(str(ds.VERSAO_SUMMARY), encoding="utf-8")
    (trabalho / ds.NOME_CORTE_SUMMARY).write_text("2026-09-22", encoding="utf-8")

    assert ds.summary_dashboard_atualizado(trabalho, fonte, data_corte=date(2026, 9, 22))
    # Virou o dia: mesma fonte, mas o summary não traz o dia que fechou.
    assert not ds.summary_dashboard_atualizado(trabalho, fonte, data_corte=date(2026, 9, 23))


# --- cache em disco das telas --------------------------------------------------


def test_cache_de_tela_grava_e_le_pela_mesma_chave(tmp_path):
    chave = ("IBAD", "", "fechados", ((1.5, 10), (2.25, 20)), date(2026, 9, 24), frozenset({"b", "a"}))
    cache_telas.gravar(tmp_path, "clientes-painel", chave, {"total": 1})
    assert cache_telas.ler(tmp_path, "clientes-painel", chave) == {"total": 1}
    # set em outra ordem é a mesma chave (outro processo pode montar diferente)
    mesma = ("IBAD", "", "fechados", ((1.5, 10), (2.25, 20)), date(2026, 9, 24), frozenset({"a", "b"}))
    assert cache_telas.ler(tmp_path, "clientes-painel", mesma) == {"total": 1}


@pytest.mark.parametrize("mudanca", [
    ("IBAD", "", "completo", ((1.5, 10),), date(2026, 9, 24)),     # outro modo
    ("IBAD", "", "fechados", ((1.6, 10),), date(2026, 9, 24)),     # base nova
    ("IBAD", "", "fechados", ((1.5, 10),), date(2026, 9, 25)),     # outro dia
])
def test_qualquer_mudanca_na_chave_nao_acha_o_arquivo(tmp_path, mudanca):
    cache_telas.gravar(tmp_path, "diagnostico", ("IBAD", "", "fechados", ((1.5, 10),), date(2026, 9, 24)), {"a": 1})
    assert cache_telas.ler(tmp_path, "diagnostico", mudanca) is None


def test_arquivo_corrompido_vira_cache_vazio(tmp_path):
    chave = ("GAP",)
    cache_telas.gravar(tmp_path, "vendedores", chave, {"a": 1})
    cache_telas.caminho(tmp_path, "vendedores", chave).write_bytes(b"lixo")
    assert cache_telas.ler(tmp_path, "vendedores", chave) is None


def test_limpeza_so_apaga_antigos(tmp_path):
    import os
    import time

    cache_telas.gravar(tmp_path, "estoque", ("novo",), {"a": 1})
    cache_telas.gravar(tmp_path, "estoque", ("velho",), {"a": 1})
    velho = cache_telas.caminho(tmp_path, "estoque", ("velho",))
    antigo = time.time() - 5 * 86400
    os.utime(velho, (antigo, antigo))
    assert cache_telas.limpar_antigos(tmp_path) == 1
    assert cache_telas.ler(tmp_path, "estoque", ("novo",)) == {"a": 1}
