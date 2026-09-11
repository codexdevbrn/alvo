"""Ranking e ficha de vendedores: último mês vs média dos 6 anteriores."""

import datetime as _dt

import pandas as pd
import pytest

import periodo_mensal
from analise_vendedores import (
    ErroFichaVendedor,
    NOME_SEM_VENDEDOR,
    coluna_vendedor_preenchida,
    montar_ficha_vendedor,
    montar_ranking_vendedores,
    preencher_vendedores_demo,
)


class _DataFixa:
    """Substitui `periodo_mensal.date` para fixar "hoje" nos testes de mês fechado."""

    def __init__(self, hoje: _dt.date):
        self._hoje = hoje

    def today(self):
        return self._hoje


def _linha(
    periodo: str,
    receita: float,
    *,
    vendedor: str = "Ana Souza",
    cliente: str = "Cliente A",
    produto: str = "Filtro",
    fabricante: str = "Wega",
    qtd: int = 1,
) -> dict:
    return {
        "Vendedor": vendedor,
        "Cliente": cliente,
        "Periodo_Mensal": periodo,
        "Receita": receita,
        "QTD": qtd,
        "descricao": produto,
        "NOME_FABRICANTE": fabricante,
    }


def _base() -> pd.DataFrame:
    linhas: list[dict] = []
    # Seis meses de histórico estáveis + agosto (mês atual) com movimentos distintos.
    for mes in ("2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"):
        linhas += [
            _linha(mes, 100, vendedor="Ana Souza", cliente="Cliente A", produto="Filtro"),
            _linha(mes, 80, vendedor="Bruno Lima", cliente="Cliente B", produto="Pastilha"),
            _linha(mes, 50, vendedor="Carla Dias", cliente="Cliente C", produto="Oleo"),
        ]
    linhas += [
        # Ana sobe 50% (150 vs média 100).
        _linha("2026-08", 150, vendedor="Ana Souza", cliente="Cliente A", produto="Filtro", qtd=2),
        # Bruno cai 50% (40 vs média 80) — alerta.
        _linha("2026-08", 40, vendedor="Bruno Lima", cliente="Cliente B", produto="Pastilha"),
        # Carla some no mês atual: entra com zero.
        _linha("2026-08", 10, vendedor="", cliente="Cliente D", produto="Correia"),
        # Confirma agosto como último período da base.
        _linha("2026-08", 5, vendedor="Ana Souza", cliente="Cliente E", produto="Vela", fabricante="NGK"),
    ]
    return pd.DataFrame(linhas)


def test_sem_coluna_devolve_indisponivel():
    base = _base().drop(columns=["Vendedor"])
    resultado = montar_ranking_vendedores(base)
    assert resultado["disponivel"] is False
    assert resultado["itens"] == []
    assert "vendedor" in resultado["mensagem"].lower()


def test_ranking_compara_ultimo_mes_com_media_de_seis():
    resultado = montar_ranking_vendedores(_base())
    itens = {item["vendedor"]: item for item in resultado["itens"]}

    assert resultado["disponivel"] is True
    assert resultado["periodo_atual"] == "2026-08"
    assert resultado["meses_media"] == 6
    assert itens["Ana Souza"]["receita_atual"] == 155
    assert itens["Ana Souza"]["receita_media"] == 100
    assert itens["Ana Souza"]["variacao"] == 55
    assert itens["Ana Souza"]["clientes_atual"] == 2
    assert itens["Bruno Lima"]["receita_atual"] == 40
    assert itens["Bruno Lima"]["variacao"] == -50
    assert itens["Carla Dias"]["receita_atual"] == 0
    assert itens["Carla Dias"]["receita_media"] == 50
    assert itens["Carla Dias"]["variacao"] == -100
    assert itens[NOME_SEM_VENDEDOR]["receita_atual"] == 10
    assert resultado["resumo"]["maior_alta"]["vendedor"] == "Ana Souza"
    assert resultado["resumo"]["maior_queda"]["vendedor"] == "Carla Dias"


def test_ficha_alerta_cliente_e_produto_em_queda():
    dados = montar_ficha_vendedor(_base(), "Bruno Lima")
    assert dados["receita_atual"] == 40
    assert dados["receita_media"] == 80
    assert dados["variacao"] == -50
    assert dados["alertas"]["clientes"][0]["cliente"] == "Cliente B"
    assert dados["alertas"]["produtos"][0]["produto"] == "Pastilha"
    assert dados["clientes"][0]["alerta"] is True


def test_ficha_corta_lista_de_alertas_nos_dez_maiores():
    linhas: list[dict] = []
    for i in range(15):
        for mes in ("2026-02", "2026-03", "2026-04", "2026-05", "2026-06", "2026-07"):
            linhas.append(_linha(mes, 100, cliente=f"C{i}", produto=f"P{i}"))
        linhas.append(_linha("2026-08", 10, cliente=f"C{i}", produto=f"P{i}"))
    dados = montar_ficha_vendedor(pd.DataFrame(linhas), "Ana Souza")
    assert dados["alertas"]["clientes_total"] == 15
    assert dados["alertas"]["produtos_total"] == 15
    assert len(dados["alertas"]["clientes"]) == 10
    assert len(dados["alertas"]["produtos"]) == 10


def test_modo_periodo_fechados_recua_quando_ultimo_mes_esta_em_aberto(monkeypatch):
    monkeypatch.setattr(periodo_mensal, "date", _DataFixa(_dt.date(2026, 8, 15)))
    resultado = montar_ranking_vendedores(_base(), modo_periodo="fechados")
    assert resultado["periodo_atual"] == "2026-07"


def test_modo_periodo_completo_mantem_o_ultimo_mes_da_base(monkeypatch):
    monkeypatch.setattr(periodo_mensal, "date", _DataFixa(_dt.date(2026, 8, 15)))
    resultado = montar_ranking_vendedores(_base(), modo_periodo="completo")
    assert resultado["periodo_atual"] == "2026-08"


def test_modo_periodo_mesmo_periodo_corta_o_historico_no_mesmo_dia(monkeypatch):
    """Mês corrente só tem movimento até o dia 1 — o histórico (julho) entra
    só com o que aconteceu até o dia 1, não o mês inteiro."""
    monkeypatch.setattr(periodo_mensal, "date", _DataFixa(_dt.date(2026, 8, 2)))
    linhas = [
        {**_linha("2026-07", 100), "Data_Venda_Diaria": "2026-07-01"},
        {**_linha("2026-07", 100), "Data_Venda_Diaria": "2026-07-15"},
        {**_linha("2026-08", 10), "Data_Venda_Diaria": "2026-08-01"},
    ]
    resultado = montar_ranking_vendedores(pd.DataFrame(linhas), modo_periodo="mesmo_periodo")
    assert resultado["periodo_atual"] == "2026-08"
    item = next(i for i in resultado["itens"] if i["vendedor"] == "Ana Souza")
    assert item["receita_media"] == 100.0


def test_ficha_recusa_vendedor_ausente():
    with pytest.raises(ErroFichaVendedor, match="não encontrado"):
        montar_ficha_vendedor(_base(), "Ninguém")


def test_demo_preenche_tres_vendedores_estaveis():
    base = pd.DataFrame({
        "Cliente": ["AAA", "BBB", "AAA", "CONSUMIDOR FINAL"],
        "Receita": [1, 2, 3, 4],
    })
    preenchida = preencher_vendedores_demo(base)
    assert coluna_vendedor_preenchida(preenchida)
    por_cliente = (
        preenchida.groupby("Cliente")["Vendedor"].nunique().to_dict()
    )
    assert por_cliente["AAA"] == 1
    assert por_cliente["BBB"] == 1
    assert set(preenchida.loc[preenchida["Cliente"] != "CONSUMIDOR FINAL", "Vendedor"]) <= set(
        ["Ana Souza", "Bruno Lima", "Carla Dias"]
    )
    assert (preenchida.loc[preenchida["Cliente"] == "CONSUMIDOR FINAL", "Vendedor"] == "").all()


def test_aplicar_demo_so_na_empresa_mockada():
    import main

    base = pd.DataFrame({"Cliente": ["Cliente X"], "Receita": [10]})
    mockada = main._aplicar_vendedores_demo_se_preciso(base, "Dados Mockados")
    outra = main._aplicar_vendedores_demo_se_preciso(base, "Altese")
    assert "Vendedor" in mockada.columns
    assert "Vendedor" not in outra.columns

    com_coluna = pd.DataFrame({"Cliente": ["Cliente X"], "Receita": [10], "Vendedor": ["Real"]})
    preservada = main._aplicar_vendedores_demo_se_preciso(com_coluna, "Dados Mockados")
    assert preservada["Vendedor"].tolist() == ["Real"]


def test_mapeia_coluna_nome_vendedor_da_fonte():
    from engine.analise_funil import mapear_coluna_vendedor

    bruto = pd.DataFrame({"NOME_VENDEDOR": ["Ana"], "Receita": [1]})
    mapeado = mapear_coluna_vendedor(bruto)
    assert "Vendedor" in mapeado.columns
    assert mapeado["Vendedor"].tolist() == ["Ana"]
