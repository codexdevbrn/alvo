"""Histórico de precificações por SKU (aba Pós-precificação da tela Precificação)."""

import pandas as pd
import pytest

import historico_precificacao as hp


def _dump(linhas):
    base = {
        "cnpj": "01709513000139", "descricao": "Filtro", "fabricante": "TECFIL",
        "margem_anterior": 30.0, "margem_alvo": 32.0, "receita": 1000.0, "cmv": 700.0,
        "fx": "A1",
    }
    return pd.DataFrame([{**base, **linha} for linha in linhas])


def _mov(linhas):
    """(codigo, data, receita, cmv, qtd)."""
    return pd.DataFrame([
        {"codigo_produto": c, "Data_Venda_Diaria": pd.Timestamp(d), "Receita": r, "CMV": m, "QTD": q,
         "descricao": "x", "NOME_FABRICANTE": "x"}
        for c, d, r, m, q in linhas
    ])


def _preparar(dump, mov):
    eventos = hp.calcular_efeitos(hp.preparar_eventos(dump), hp.preparar_diario(mov))
    return eventos, hp.preparar_serie(mov)


def _loja_vende_todo_dia(inicio, fim, codigo="OUTRO"):
    """Garante que a loja vendeu em todos os dias — isola o teste da régua de dias."""
    return [(codigo, d, 1.0, 1.0, 1) for d in pd.date_range(inicio, fim)]


def test_dump_sem_codigo_avisa_para_gerar_pelo_postgres():
    dump = _dump([{"data_exportacao": "2026-05-05 10:00"}]).drop(columns=["fx"])
    with pytest.raises(hp.ErroHistoricoPrecificacao, match="Postgres"):
        hp.preparar_eventos(dump)


def test_mesmo_sku_no_mesmo_dia_vale_a_ultima_gravacao():
    dump = _dump([
        {"codigo": "A", "data_exportacao": "2026-05-05 10:00", "margem_alvo": 30.0},
        {"codigo": "A", "data_exportacao": "2026-05-05 18:00", "margem_alvo": 35.0},
    ])
    eventos = hp.preparar_eventos(dump)
    assert len(eventos) == 1
    assert eventos["margem_alvo"].iloc[0] == 35.0


def test_depois_corta_na_proxima_precificacao_do_mesmo_sku():
    dump = _dump([
        {"codigo": "A", "data_exportacao": "2026-05-01 10:00"},
        {"codigo": "A", "data_exportacao": "2026-05-11 10:00"},
    ])
    mov = _mov([
        ("A", "2026-05-05", 100.0, 60.0, 1),   # depois do 1º evento, antes do 2º
        ("A", "2026-05-15", 500.0, 300.0, 1),  # depois do 2º — não pode entrar no 1º
        *_loja_vende_todo_dia("2026-04-01", "2026-06-10"),
    ])
    eventos, _ = _preparar(dump, mov)
    primeiro = eventos.sort_values("dia").iloc[0]
    assert primeiro["receita_d"] == pytest.approx(100.0)
    assert primeiro["dias_d"] == 10  # 01/05 → 11/05


def test_por_dia_divide_pelos_dias_em_que_a_loja_vendeu():
    """Domingo sem venda na loja não entra no divisor."""
    dump = _dump([{"codigo": "A", "data_exportacao": "2026-05-04 10:00"}])  # segunda
    dias_uteis = [d for d in pd.date_range("2026-04-01", "2026-06-10") if d.weekday() != 6]
    mov = _mov([("A", d, 10.0, 6.0, 1) for d in dias_uteis])
    eventos, _ = _preparar(dump, mov)
    ev = eventos.iloc[0]
    assert ev["ld_a"] == pytest.approx(4.0)  # lucro 4 por dia útil, não 4 × 26/30
    assert ev["ld_d"] == pytest.approx(4.0)


def test_vigente_e_o_ultimo_evento_e_a_tabela_agrupa_por_familia():
    dump = _dump([
        {"codigo": "A", "data_exportacao": "2026-05-01 10:00", "margem_alvo": 30.0},
        {"codigo": "A", "data_exportacao": "2026-05-20 10:00", "margem_alvo": 20.0},
        {"codigo": "B", "data_exportacao": "2026-05-01 10:00", "margem_alvo": 40.0, "fx": "C2"},
    ])
    mov = _mov([
        ("A", "2026-05-25", 100.0, 70.0, 1),  # margem 30% vs alvo vigente 20%
        ("B", "2026-05-10", 100.0, 70.0, 1),  # margem 30% vs alvo 40%
        *_loja_vende_todo_dia("2026-04-01", "2026-06-30"),
    ])
    eventos, serie = _preparar(dump, mov)
    r = hp.montar_historico(eventos, serie, nivel="sku", periodo_dias=365)
    por_sku = {linha["nome"]: linha for linha in r["linhas"]}
    assert por_sku["A"]["alvo"] == pytest.approx(20.0)
    assert por_sku["A"]["precificacoes"] == 2
    assert por_sku["A"]["ultima"] == "2026-05-20"
    assert por_sku["A"]["situacao"] == "acima"
    assert por_sku["B"]["situacao"] == "abaixo"
    fam = hp.montar_historico(eventos, serie, nivel="familia", periodo_dias=365)
    assert [linha["nome"] for linha in fam["linhas"]] == ["Filtro"]
    assert fam["linhas"][0]["skus"] == 2
    assert fam["kpis"]["skus"] == 2
    assert fam["faixas_disponiveis"] == ["A", "C"]


def test_filtros_de_faixa_rodada_e_periodo():
    dump = _dump([
        {"codigo": "A", "data_exportacao": "2026-01-10 10:00"},
        {"codigo": "B", "data_exportacao": "2026-05-10 10:00", "fx": "C1"},
    ])
    mov = _mov(_loja_vende_todo_dia("2026-01-01", "2026-06-30", codigo="A"))
    eventos, serie = _preparar(dump, mov)
    assert hp.montar_historico(eventos, serie, periodo_dias=90)["kpis"]["skus"] == 1
    assert hp.montar_historico(eventos, serie, periodo_dias=365)["kpis"]["skus"] == 2
    assert hp.montar_historico(eventos, serie, periodo_dias=365, faixas=["c"])["kpis"]["skus"] == 1
    r = hp.montar_historico(eventos, serie, periodo_dias=365, rodadas=["2026-01-10"])
    assert r["kpis"]["skus"] == 1
    assert [t["selecionada"] for t in r["linha_tempo"]] == [True, False]


def test_item_traz_historico_mesmo_fora_do_filtro():
    dump = _dump([
        {"codigo": "A", "data_exportacao": "2026-01-10 10:00", "margem_alvo": 28.0},
        {"codigo": "A", "data_exportacao": "2026-05-10 10:00", "margem_alvo": 31.0},
    ])
    mov = _mov(_loja_vende_todo_dia("2026-01-01", "2026-06-30", codigo="A"))
    eventos, serie = _preparar(dump, mov)
    item = hp.montar_item(eventos, serie, nivel="familia", nome="Filtro", periodo_dias=90)
    assert [h["dia"] for h in item["historico"]] == ["2026-05-10", "2026-01-10"]
    assert [h["no_filtro"] for h in item["historico"]] == [True, False]
    assert item["skus"][0]["codigo"] == "A"
    assert item["skus"][0]["alvo"] == pytest.approx(31.0)
