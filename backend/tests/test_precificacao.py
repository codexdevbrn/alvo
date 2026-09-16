"""Pós precificação: dump × movimento na janela depois da data."""

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

import main  # noqa: F401
from engine import analise_funil as af
from normalizar_base import resolver_caminho_precificacao
from precificacao import montar_pos_precificacao


def _dump(**overrides) -> dict:
    base = {
        "cnpj": "01709513000139",
        "descricao": "Filtro Lubrificante",
        "fabricante": "TECFIL",
        "margem_anterior": 30.0,
        "margem_alvo": 32.0,
        "receita": 5000.0,
        "cmv": 3500.0,
        "data_exportacao": "2026-05-12 12:00:00",
        "markup_alvo": None,
        "preco_atual": None,
        "preco_sugerido": None,
        "variacao_pct": None,
    }
    base.update(overrides)
    return base


def _mov(
    descricao: str,
    fabricante: str,
    data: str,
    receita: float,
    cmv: float,
    qtd: float = 1.0,
) -> dict:
    dia = pd.Timestamp(data)
    return {
        "descricao": descricao,
        "NOME_FABRICANTE": fabricante,
        "Receita": receita,
        "CMV": cmv,
        "QTD": qtd,
        "Data_Venda_Diaria": dia,
        "Data_Venda": dia.replace(day=1),
        "Periodo_Mensal": dia.strftime("%Y-%m"),
    }


def test_resolver_caminho_precificacao_opcional(tmp_path):
    pasta = tmp_path / "IBAD"
    pasta.mkdir()
    assert resolver_caminho_precificacao(pasta) is None
    (pasta / "IBAD_PRECIFICACAO.csv").write_text("cnpj,descricao\n", encoding="utf-8-sig")
    achado = resolver_caminho_precificacao(pasta)
    assert achado is not None
    assert achado.name == "IBAD_PRECIFICACAO.csv"


def test_carregar_csv_precificacao_virgula_e_cnpj(tmp_path):
    caminho = tmp_path / "IBAD_PRECIFICACAO.csv"
    pd.DataFrame([_dump()]).to_csv(caminho, index=False, encoding="utf-8-sig")
    df = af.carregar_csv_precificacao(caminho)
    assert df["cnpj"].iloc[0] == "01709513000139"
    assert df["descricao"].iloc[0] == "Filtro Lubrificante"
    assert df["margem_alvo"].iloc[0] == pytest.approx(32.0)
    assert pd.isna(df["preco_sugerido"].iloc[0])


def test_montar_compara_janela_igual_e_ignora_par_fora_do_dump():
    dump = pd.DataFrame([_dump()])
    # Corte 12/mai. Último movimento 12/jul → 61 dias. Antes = 12/mar..12/mai.
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-04-20", 100.0, 70.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-12", 140.0, 84.0),
        _mov("Filtro Lubrificante", "OUTRO", "2026-06-12", 999.0, 1.0),
        _mov("Outra Familia", "TECFIL", "2026-06-12", 888.0, 1.0),
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 7, 20),
    )

    assert resultado["data_precificacao"] == "2026-05-12"
    assert resultado["familias"] == 1
    assert resultado["pares"] == 1
    assert resultado["tem_movimento_depois"] is True
    assert resultado["resumo"]["receita_antes"] == pytest.approx(100.0)
    assert resultado["resumo"]["receita_depois"] == pytest.approx(140.0)
    assert resultado["resumo"]["margem_depois"] == pytest.approx((140 - 84) / 140 * 100)
    assert resultado["resumo"]["margem_alvo"] == pytest.approx(32.0)
    assert resultado["resumo"]["variacao_receita_pct"] == pytest.approx(40.0)
    nomes = {item["nome"] for item in resultado["produtos"]}
    assert nomes == {"Filtro Lubrificante"}
    assert resultado["produtos"][0]["situacao"] == "acima"
    assert resultado["resumo"]["lucro_depois"] == pytest.approx(56.0)
    assert resultado["resumo"]["qtd_depois"] == pytest.approx(1.0)
    assert resultado["resumo"]["lucro_dia_depois"] == pytest.approx(56.0)
    assert resultado["resumo"]["qtd_dia_depois"] == pytest.approx(1.0)
    rotulos = [ponto["rotulo"] for ponto in resultado["serie_mensal"]]
    assert "abr/26" in rotulos
    assert "jun/26" in rotulos
    junho = next(p for p in resultado["serie_mensal"] if p["periodo"] == "2026-06")
    assert junho["lucro_dia"] == pytest.approx(56.0)
    assert junho["qtd_dia"] == pytest.approx(1.0)
    serie_prod = resultado["produtos"][0]["serie_mensal"]
    junho_prod = next(p for p in serie_prod if p["periodo"] == "2026-06")
    assert junho_prod["lucro"] == pytest.approx(56.0)
    assert junho_prod["receita"] == pytest.approx(140.0)


def test_lucro_e_qtd_dia_dividem_por_dias_com_venda():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-10", 100.0, 40.0, qtd=8),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-11", 100.0, 40.0, qtd=2),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-11", 50.0, 20.0, qtd=1),
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 6, 20),
    )
    # 2 dias com venda, lucro 150, qtd 11 → 75 / dia e 5,5 / dia.
    assert resultado["resumo"]["dias_venda_depois"] == 2
    assert resultado["resumo"]["lucro_depois"] == pytest.approx(150.0)
    assert resultado["resumo"]["qtd_depois"] == pytest.approx(11.0)
    assert resultado["resumo"]["lucro_dia_depois"] == pytest.approx(75.0)
    assert resultado["resumo"]["qtd_dia_depois"] == pytest.approx(5.5)
    junho = next(p for p in resultado["serie_mensal"] if p["periodo"] == "2026-06")
    assert junho["dias_venda"] == 2
    assert junho["lucro_dia"] == pytest.approx(75.0)
    assert junho["qtd_dia"] == pytest.approx(5.5)


def test_serie_do_produto_nao_traz_familia_fora_do_dump():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-12", 140.0, 84.0, qtd=4),
        _mov("Outra Familia", "TECFIL", "2026-06-12", 888.0, 1.0, qtd=90),
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 6, 20),
    )
    junho = next(p for p in resultado["serie_mensal"] if p["periodo"] == "2026-06")
    assert junho["qtd"] == pytest.approx(4.0)
    assert junho["lucro"] == pytest.approx(56.0)


def test_montar_sem_venda_depois_marca_sem_venda():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-04-01", 100.0, 70.0),
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 5, 20),
    )
    assert resultado["tem_movimento_depois"] is False
    assert resultado["produtos"][0]["situacao"] == "sem_venda"
    assert resultado["resumo"]["receita_depois"] == 0.0


def test_serie_diaria_cobre_janela_curta_ao_redor_do_corte():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-10", 100.0, 70.0, qtd=2),
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-12", 140.0, 84.0, qtd=3),
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-14", 90.0, 60.0, qtd=1),
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 5, 20),
    )
    periodos = [ponto["periodo"] for ponto in resultado["serie_diaria"]]
    assert "2026-05-10" in periodos
    assert "2026-05-12" in periodos
    assert "2026-05-14" in periodos
    dia_12 = next(p for p in resultado["serie_diaria"] if p["periodo"] == "2026-05-12")
    assert dia_12["rotulo"] == "12/05"
    assert dia_12["lucro"] == pytest.approx(56.0)
    assert dia_12["lucro_dia"] == pytest.approx(56.0)
    # Dia sem venda não entra na série — não é dado zero, é ausência de movimento.
    assert not any(p["periodo"] == "2026-05-11" for p in resultado["serie_diaria"])
    serie_prod_dia = resultado["produtos"][0]["serie_diaria"]
    assert any(p["periodo"] == "2026-05-14" and p["qtd"] == pytest.approx(1.0) for p in serie_prod_dia)


def test_janelas_fixas_semana_quinzena_mes():
    dump = pd.DataFrame([_dump()])
    # Corte 12/mai. Semana (7d): compara 05/mai-12/mai vs 12/mai-19/mai.
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-08", 100.0, 70.0, qtd=2),  # antes da semana
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-15", 200.0, 100.0, qtd=4),  # depois da semana
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-20", 50.0, 40.0, qtd=1),  # depois da quinzena, dentro do mês
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 6, 20),
    )
    semana = resultado["resumo"]["janelas"]["semana"]
    assert semana["dias"] == 7
    assert semana["receita_antes"] == pytest.approx(100.0)
    assert semana["receita_depois"] == pytest.approx(200.0)
    assert semana["variacao_receita_pct"] == pytest.approx(100.0)
    assert semana["completa"] is True

    quinzena = resultado["resumo"]["janelas"]["quinzena"]
    assert quinzena["receita_depois"] == pytest.approx(250.0)  # 15 e 20 entram nos 15 dias (12..27/mai)

    mes = resultado["resumo"]["janelas"]["mes"]
    assert mes["receita_depois"] == pytest.approx(250.0)  # 15 e 20 também entram nos 30 dias

    produto = resultado["produtos"][0]
    assert produto["janelas"]["semana"]["receita_depois"] == pytest.approx(200.0)


def test_janela_fixa_incompleta_quando_falta_dado_recente():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-14", 100.0, 70.0),
    ])
    # "Hoje" 3 dias depois do corte: a janela de 1 semana ainda não fechou.
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=False, hoje=date(2026, 5, 15),
    )
    semana = resultado["resumo"]["janelas"]["semana"]
    assert semana["completa"] is False


def test_mes_aberto_nao_entra_na_janela_depois():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-04-01", 100.0, 70.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-10", 50.0, 30.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-07-02", 400.0, 10.0),
    ])
    resultado = montar_pos_precificacao(
        dump, movimento, usar_mes_fechado=True, hoje=date(2026, 7, 15),
    )
    # Julho está aberto: a venda de 400 não entra.
    assert resultado["resumo"]["receita_depois"] == pytest.approx(50.0)
    assert resultado["periodo_depois"]["fim"] == "2026-06-30"
    periodos = [ponto["periodo"] for ponto in resultado["serie_mensal"]]
    assert "2026-07" not in periodos
    assert "2026-06" in periodos
