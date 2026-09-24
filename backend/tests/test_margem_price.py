"""Leitura dos parquets do PRICE e a fórmula de margem por trás — validada
manualmente contra a tela real do PRICE (Lubrificante, IBAD, mar-set/26).
"""

import json

import pandas as pd
import pytest

import margem_price as mp


def _gravar_parquet(pasta, cnpj, linhas):
    pasta.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(linhas).to_parquet(pasta / f"margem_{cnpj}.parquet")


def _linha(data, descricao, receita, cmv, quantidade=1.0, codigo="COD1", fabricante="FAB", segmento="SEG"):
    return {
        "data": data, "cnpj": "00000000000000", "codigo_produto": codigo,
        "fabricante": fabricante, "descricao": descricao, "segmento": segmento,
        "cmv": cmv, "receita": receita, "quantidade": quantidade,
    }


def test_carregar_mapa_cnpj_ausente_devolve_vazio(tmp_path):
    assert mp.carregar_mapa_cnpj(tmp_path) == {}


def test_carregar_mapa_cnpj_normaliza_string_unica_e_lista(tmp_path):
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(
        json.dumps({"IBAD": "01.709.513/0001-39", "Altese": ["31263577000110", "31263577000209"]}),
        encoding="utf-8",
    )
    mapa = mp.carregar_mapa_cnpj(tmp_path)
    assert mapa["IBAD"] == ["01709513000139"]
    assert mapa["Altese"] == ["31263577000110", "31263577000209"]


def test_carregar_mapa_cnpj_invalido_devolve_vazio(tmp_path):
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text("não é json", encoding="utf-8")
    assert mp.carregar_mapa_cnpj(tmp_path) == {}


def test_resolver_cnpjs_empresa_sem_mapa(tmp_path):
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(json.dumps({"IBAD": ["01709513000139"]}), encoding="utf-8")
    assert mp.resolver_cnpjs("Motobras", tmp_path) == []


def test_assinatura_none_sem_mapa_ou_sem_parquet(tmp_path):
    pasta_margem = tmp_path / "margem_price"
    pasta_margem.mkdir()
    # Sem mapa: None.
    assert mp.assinatura("IBAD", tmp_path, pasta_margem) is None
    # Mapa existe, mas nenhum parquet no disco: também None.
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(json.dumps({"IBAD": ["01709513000139"]}), encoding="utf-8")
    assert mp.assinatura("IBAD", tmp_path, pasta_margem) is None


def test_assinatura_muda_quando_parquet_muda(tmp_path):
    """`st_size` é o sinal confiável aqui: dois parquets escritos no mesmo
    milissegundo podem carimbar o mesmo mtime, mas número de linhas diferente
    sempre muda o tamanho em disco."""
    pasta_margem = tmp_path / "margem_price"
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(json.dumps({"IBAD": ["01709513000139"]}), encoding="utf-8")
    _gravar_parquet(pasta_margem, "01709513000139", [_linha("2026-03-01", "Lubrificante", 100.0, 70.0)])
    a1 = mp.assinatura("IBAD", tmp_path, pasta_margem)
    assert a1 is not None
    _gravar_parquet(pasta_margem, "01709513000139", [
        _linha("2026-03-01", "Lubrificante", 200.0, 70.0),
        _linha("2026-03-02", "Bateria", 300.0, 200.0),
    ])
    a2 = mp.assinatura("IBAD", tmp_path, pasta_margem)
    assert a2 != a1


def test_carregar_bruto_soma_todas_as_lojas(tmp_path):
    """Duas lojas (CNPJs) da mesma empresa — `carregar_bruto` concatena as duas,
    não fica só na primeira que casar."""
    pasta_margem = tmp_path / "margem_price"
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(
        json.dumps({"IBAD": ["01709513000139", "07883453000152"]}), encoding="utf-8",
    )
    _gravar_parquet(pasta_margem, "01709513000139", [_linha("2026-03-01", "Lubrificante", 100.0, 70.0)])
    _gravar_parquet(pasta_margem, "07883453000152", [_linha("2026-03-01", "Lubrificante", 50.0, 40.0)])
    bruto = mp.carregar_bruto("IBAD", tmp_path, pasta_margem)
    assert len(bruto) == 2
    assert bruto["receita"].sum() == 150.0


def test_carregar_bruto_ignora_cnpj_do_mapa_sem_parquet_no_disco(tmp_path):
    """Uma filial nova no mapa antes do parquet dela existir não deve derrubar
    a leitura das lojas que já têm dado."""
    pasta_margem = tmp_path / "margem_price"
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(
        json.dumps({"IBAD": ["01709513000139", "99999999000199"]}), encoding="utf-8",
    )
    _gravar_parquet(pasta_margem, "01709513000139", [_linha("2026-03-01", "Lubrificante", 100.0, 70.0)])
    bruto = mp.carregar_bruto("IBAD", tmp_path, pasta_margem)
    assert len(bruto) == 1


def test_carregar_bruto_sem_cnpj_mapeado_levanta(tmp_path):
    pasta_margem = tmp_path / "margem_price"
    pasta_margem.mkdir()
    with pytest.raises(mp.ErroMargemPrice):
        mp.carregar_bruto("Desconhecida", tmp_path, pasta_margem)


def test_carregar_bruto_sem_nenhum_parquet_no_disco_levanta(tmp_path):
    pasta_margem = tmp_path / "margem_price"
    pasta_margem.mkdir()
    (tmp_path / mp.NOME_MAPA_CNPJ).write_text(json.dumps({"IBAD": ["01709513000139"]}), encoding="utf-8")
    with pytest.raises(mp.ErroMargemPrice):
        mp.carregar_bruto("IBAD", tmp_path, pasta_margem)


def test_para_movimento_precificacao_renomeia_colunas():
    bruto = pd.DataFrame([_linha("2026-03-01", "Lubrificante", 100.0, 70.0)])
    bruto["data"] = pd.to_datetime(bruto["data"])
    mov = mp.para_movimento_precificacao(bruto)
    assert set(["Data_Venda_Diaria", "NOME_FABRICANTE", "Receita", "CMV", "QTD"]).issubset(mov.columns)
    assert "descricao" in mov.columns  # não renomeada — precificacao.py já espera esse nome


def test_para_movimento_precificacao_descarta_linha_sem_segmento():
    """Sem segmento é o balde "NÃO HARMONIZADO" — a tela do PRICE não conta."""
    bruto = pd.DataFrame([
        _linha("2026-04-01", "Lubrificante", 100.0, 70.0),
        _linha("2026-04-01", "NÃO HARMONIZADO", 50.0, 40.0, segmento=None),
    ])
    bruto["data"] = pd.to_datetime(bruto["data"])
    mov = mp.para_movimento_precificacao(bruto)
    assert mov["descricao"].tolist() == ["Lubrificante"]


def test_margem_mensal_pondera_por_loja_nao_faz_media_simples():
    """A margem certa é (receita-cmv)/receita somando as duas lojas primeiro —
    não a média das margens de cada loja isolada, que dá outro número.
    """
    bruto = pd.DataFrame([
        _linha("2026-03-05", "Lubrificante", 100.0, 50.0),  # margem 50%
        _linha("2026-03-10", "Lubrificante", 900.0, 810.0),  # margem 10%
    ])
    bruto["data"] = pd.to_datetime(bruto["data"])
    pontos = mp.margem_mensal(bruto, "Lubrificante")
    assert len(pontos) == 1
    # Ponderada: (100+900 - 50-810) / (100+900) = 140/1000 = 14%.
    assert pontos[0]["margem"] == pytest.approx(14.0)
    # Média simples das duas margens (50% e 10%) daria 30% — errado, não é isso.
    assert pontos[0]["margem"] != pytest.approx(30.0)


def test_margem_mensal_dias_venda_conta_dias_distintos_com_receita():
    bruto = pd.DataFrame([
        _linha("2026-03-05", "Lubrificante", 100.0, 50.0),
        _linha("2026-03-05", "Lubrificante", 50.0, 25.0),  # mesmo dia, 2ª venda
        _linha("2026-03-10", "Lubrificante", 200.0, 100.0),
        _linha("2026-03-15", "Lubrificante", 0.0, 0.0),  # sem receita: não conta como dia de venda
    ])
    bruto["data"] = pd.to_datetime(bruto["data"])
    pontos = mp.margem_mensal(bruto, "Lubrificante")
    assert pontos[0]["dias_venda"] == 2
    assert pontos[0]["lucro_dia"] == pytest.approx((350.0 - 175.0) / 2)


def test_margem_mensal_sem_descricao_agrega_empresa_inteira():
    bruto = pd.DataFrame([
        _linha("2026-03-05", "Lubrificante", 100.0, 50.0),
        _linha("2026-03-05", "Bateria", 200.0, 100.0),
    ])
    bruto["data"] = pd.to_datetime(bruto["data"])
    pontos = mp.margem_mensal(bruto)
    assert len(pontos) == 1
    assert pontos[0]["receita"] == 300.0


def test_margem_mensal_descricao_sem_venda_devolve_vazio():
    bruto = pd.DataFrame([_linha("2026-03-05", "Lubrificante", 100.0, 50.0)])
    bruto["data"] = pd.to_datetime(bruto["data"])
    assert mp.margem_mensal(bruto, "Produto Inexistente") == []


def test_margem_geral_pondera_todo_o_recorte():
    bruto = pd.DataFrame([
        _linha("2026-03-05", "Lubrificante", 100.0, 50.0),
        _linha("2026-04-05", "Lubrificante", 900.0, 810.0),
    ])
    bruto["data"] = pd.to_datetime(bruto["data"])
    resultado = mp.margem_geral(bruto)
    assert resultado["margem"] == pytest.approx(14.0)


def test_margem_geral_vazio_devolve_none():
    assert mp.margem_geral(pd.DataFrame(columns=["receita", "cmv"])) is None
