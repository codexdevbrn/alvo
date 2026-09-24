"""Pós precificação: dump × movimento na janela depois da data."""

from pathlib import Path

import pandas as pd
import pytest

import main  # noqa: F401
from engine import analise_funil as af
from normalizar_base import resolver_caminho_precificacao
from precificacao import filtrar_rodada, listar_rodadas_dump, montar_pos_precificacao


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
    trabalho = tmp_path / "IBAD"
    trabalho.mkdir()
    assert resolver_caminho_precificacao(trabalho) is None
    assert resolver_caminho_precificacao(None) is None
    # CSV que tenha sobrado da versão anterior não conta mais.
    (trabalho / "IBAD_PRECIFICACAO.csv").write_text("cnpj,descricao\n", encoding="utf-8-sig")
    assert resolver_caminho_precificacao(trabalho) is None
    pd.DataFrame([_dump()]).to_parquet(trabalho / "IBAD_PRECIFICACAO.parquet", index=False)
    assert resolver_caminho_precificacao(trabalho).name == "IBAD_PRECIFICACAO.parquet"


def test_carregar_csv_precificacao_parquet_e_cnpj(tmp_path):
    caminho = tmp_path / "IBAD_PRECIFICACAO.parquet"
    pd.DataFrame([_dump()]).to_parquet(caminho, index=False)
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
    resultado = montar_pos_precificacao(dump, movimento)

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
    resultado = montar_pos_precificacao(dump, movimento)
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
    resultado = montar_pos_precificacao(dump, movimento)
    junho = next(p for p in resultado["serie_mensal"] if p["periodo"] == "2026-06")
    assert junho["qtd"] == pytest.approx(4.0)
    assert junho["lucro"] == pytest.approx(56.0)


def test_montar_sem_venda_depois_marca_sem_venda():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-04-01", 100.0, 70.0),
    ])
    resultado = montar_pos_precificacao(dump, movimento)
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
    resultado = montar_pos_precificacao(dump, movimento)
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
    resultado = montar_pos_precificacao(dump, movimento)
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
    # Só há dado 2 dias depois do corte: a janela de 1 semana ainda não fechou.
    resultado = montar_pos_precificacao(dump, movimento)
    semana = resultado["resumo"]["janelas"]["semana"]
    assert semana["completa"] is False


def test_janela_usa_todo_movimento_sem_teto_de_mes_fechado():
    """Sem toggle de mês fechado/completo: a janela é sempre ponta a ponta,
    do primeiro ao último dado real — mesmo que o último mês ainda esteja
    em curso."""
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-04-01", 100.0, 70.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-10", 50.0, 30.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-07-02", 400.0, 10.0),
    ])
    resultado = montar_pos_precificacao(dump, movimento)
    # Julho entra inteiro, mesmo "em aberto".
    assert resultado["resumo"]["receita_depois"] == pytest.approx(450.0)
    assert resultado["periodo_depois"]["fim"] == "2026-07-02"
    periodos = [ponto["periodo"] for ponto in resultado["serie_mensal"]]
    assert "2026-07" in periodos
    assert "2026-06" in periodos
    # "Antes" cobre do primeiro dado real (abr) até o corte, não uma janela
    # espelhada na duração do "depois".
    assert resultado["periodo_antes"]["inicio"] == "2026-04-01"


def _dump_multi_rodada() -> pd.DataFrame:
    """Três rodadas, tamanhos diferentes, timestamp por linha como no banco."""
    linhas = [
        _dump(descricao="Filtro Lubrificante", data_exportacao="2026-05-05 08:00:00.000001"),
        _dump(descricao="Pastilha Freio", data_exportacao="2026-05-05 08:00:00.000002"),
        _dump(descricao="Filtro Lubrificante", data_exportacao="2026-05-12 12:48:14.167000"),
        _dump(descricao="Filtro Lubrificante", data_exportacao="2026-05-12 12:48:14.490000"),
        _dump(descricao="Correia", data_exportacao="2026-06-23 13:34:41.564461"),
    ]
    df = pd.DataFrame(linhas)
    df["data_exportacao"] = pd.to_datetime(df["data_exportacao"])
    return df


def test_listar_rodadas_agrupa_por_dia_nao_por_timestamp():
    rodadas = listar_rodadas_dump(_dump_multi_rodada())
    # O banco grava um timestamp por linha; rodada é o dia.
    assert [r["dia"] for r in rodadas] == ["2026-06-23", "2026-05-12", "2026-05-05"]
    assert [r["linhas"] for r in rodadas] == [1, 2, 2]
    # 2026-05-12 tem 2 linhas do mesmo par -> 1 par distinto.
    assert [r["pares"] for r in rodadas] == [1, 1, 2]


def test_filtrar_rodada_isola_uma_rodada():
    dump = _dump_multi_rodada()
    assert len(filtrar_rodada(dump)) == 1  # sem dia = a mais recente
    assert filtrar_rodada(dump)["descricao"].tolist() == ["Correia"]
    assert len(filtrar_rodada(dump, "2026-05-12")) == 2
    assert len(filtrar_rodada(dump, "2026-05-05")) == 2
    # Dia que não existe devolve vazio, em vez de cair noutra rodada.
    assert filtrar_rodada(dump, "2026-01-01").empty
    assert filtrar_rodada(dump, "nao-e-data").empty


def test_rodada_antiga_nao_contamina_o_calculo():
    """Passar o dump inteiro inflaria os pares e ponderaria o item repetido."""
    dump = _dump_multi_rodada()
    movimento = pd.DataFrame([
        _mov("Correia", "TECFIL", "2026-07-10", 100.0, 60.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-07-10", 900.0, 500.0),
    ])
    so_ultima = montar_pos_precificacao(filtrar_rodada(dump), movimento)
    tudo_junto = montar_pos_precificacao(dump, movimento)
    assert so_ultima["pares"] == 1
    assert tudo_junto["pares"] > so_ultima["pares"]
    assert so_ultima["resumo"]["receita_depois"] == pytest.approx(100.0)


def test_todos_os_itens_inclui_catalogo_fora_do_dump():
    """Sem `apenas_precificados`, a loja inteira entra: família e fabricante
    fora da rodada viram item `nao_precificado`, sem alvo."""
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-12", 140.0, 84.0),
        _mov("Filtro Lubrificante", "OUTRO", "2026-06-12", 60.0, 30.0),
        _mov("Outra Familia", "ACME", "2026-06-12", 200.0, 150.0),
    ])
    resultado = montar_pos_precificacao(dump, movimento, apenas_precificados=False)

    assert resultado["resumo"]["receita_depois"] == pytest.approx(400.0)
    # Alvo é da parte precificada; contra a loja inteira não significa nada.
    assert resultado["resumo"]["margem_alvo"] is None
    assert resultado["resumo"]["gap_alvo_pp"] is None
    assert resultado["resumo"]["situacoes"]["nao_precificado"] == 1

    produtos = {item["nome"]: item for item in resultado["produtos"]}
    assert set(produtos) == {"Filtro Lubrificante", "Outra Familia"}
    # A família precificada soma todos os fabricantes dela, não só o do dump.
    assert produtos["Filtro Lubrificante"]["precificado"] is True
    assert produtos["Filtro Lubrificante"]["receita_depois"] == pytest.approx(200.0)
    fora = produtos["Outra Familia"]
    assert fora["precificado"] is False
    assert fora["situacao"] == "nao_precificado"
    assert fora["skus_dump"] == 0
    assert fora["margem_alvo"] is None
    junho = next(p for p in fora["serie_mensal"] if p["periodo"] == "2026-06")
    assert junho["receita"] == pytest.approx(200.0)

    fabricantes = {item["nome"]: item for item in resultado["fabricantes"]}
    assert set(fabricantes) == {"TECFIL", "OUTRO", "ACME"}
    assert fabricantes["TECFIL"]["precificado"] is True
    assert fabricantes["ACME"]["situacao"] == "nao_precificado"


def test_apenas_precificados_mantem_so_pares_do_dump():
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-12", 140.0, 84.0),
        _mov("Outra Familia", "ACME", "2026-06-12", 200.0, 150.0),
    ])
    resultado = montar_pos_precificacao(dump, movimento, apenas_precificados=True)
    assert resultado["resumo"]["receita_depois"] == pytest.approx(140.0)
    assert resultado["resumo"]["margem_alvo"] == pytest.approx(32.0)
    assert [item["nome"] for item in resultado["produtos"]] == ["Filtro Lubrificante"]
    assert resultado["produtos"][0]["precificado"] is True
    assert resultado["resumo"]["situacoes"]["nao_precificado"] == 0


def test_variacao_antes_depois_e_por_dia_nao_pelo_total():
    """"Antes" e "depois" têm comprimentos diferentes: 1 dia antes, 3 depois,
    todos vendendo o mesmo por dia. Pelo total daria +200%; por dia é 0%."""
    dump = pd.DataFrame([_dump()])
    movimento = pd.DataFrame([
        _mov("Filtro Lubrificante", "TECFIL", "2026-05-01", 100.0, 60.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-01", 100.0, 60.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-02", 100.0, 60.0),
        _mov("Filtro Lubrificante", "TECFIL", "2026-06-03", 100.0, 60.0),
    ])
    resultado = montar_pos_precificacao(dump, movimento)
    assert resultado["resumo"]["receita_depois"] == pytest.approx(300.0)
    assert resultado["resumo"]["variacao_receita_pct"] == pytest.approx(0.0)
    assert resultado["resumo"]["variacao_lucro_pct"] == pytest.approx(0.0)
    assert resultado["produtos"][0]["variacao_qtd_pct"] == pytest.approx(0.0)
