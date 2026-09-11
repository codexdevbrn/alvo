"""Painel da carteira de clientes: KPIs, movimento, curva ABC e tags."""

import datetime as _dt

import pandas as pd

import periodo_mensal
from analise_clientes import montar_painel_clientes


class _DataFixa:
    """Substitui `periodo_mensal.date` para fixar "hoje" nos testes de mês fechado."""

    def __init__(self, hoje: _dt.date):
        self._hoje = hoje

    def today(self):
        return self._hoje


def _linha(periodo: str, cliente: str, receita: float, qtd: int = 1) -> dict:
    return {
        "Cliente": cliente,
        "Periodo_Mensal": periodo,
        "Receita": receita,
        "QTD": qtd,
    }


def _base() -> pd.DataFrame:
    """Jan a ago/2026 com um caso de cada evento da carteira.

    A compra todo mês; B para em abril (perdido em julho); C compra em fevereiro
    e volta em agosto (perdido em maio, recuperado em agosto); D estreia em
    agosto (novo).
    """
    meses = (
        "2026-01", "2026-02", "2026-03", "2026-04",
        "2026-05", "2026-06", "2026-07", "2026-08",
    )
    linhas = [_linha(mes, "Cliente A", 100) for mes in meses]
    linhas += [_linha(mes, "Cliente B", 80) for mes in meses[:4]]
    linhas += [_linha("2026-02", "Cliente C", 60), _linha("2026-08", "Cliente C", 60)]
    linhas.append(_linha("2026-08", "Cliente D", 40))
    return pd.DataFrame(linhas)


def test_resumo_do_mes_contra_a_media_de_seis():
    painel = montar_painel_clientes(_base())
    resumo = painel["resumo"]

    assert painel["disponivel"] is True
    assert painel["periodo_atual"] == "2026-08"
    assert painel["meses_media"] == 6
    assert painel["periodo_media_inicio"] == "2026-02"
    assert painel["periodo_media_fim"] == "2026-07"
    assert resumo["clientes_ativos"] == 3
    assert resumo["receita_atual"] == 200
    assert resumo["receita_media"] == 150
    assert resumo["variacao_receita"] == 33.33
    assert resumo["ticket_medio"] == round(200 / 3, 2)


def test_novo_recuperado_e_perdido_contam_uma_vez_cada():
    painel = montar_painel_clientes(_base())
    por_mes = {linha["periodo"]: linha for linha in painel["movimento"]}
    resumo = painel["resumo"]

    # Agosto: D estreia, C volta depois de cinco meses parado.
    assert resumo["novos"] == 1
    assert resumo["recuperados"] == 1
    assert resumo["perdidos"] == 0
    assert resumo["saldo"] == 2

    # C parou em fevereiro: perdido em maio, e só ali.
    assert por_mes["2026-05"]["perdidos"] == 1
    assert por_mes["2026-06"]["perdidos"] == 0
    # B parou em abril: perdido em julho, e só ali.
    assert por_mes["2026-07"]["perdidos"] == 1
    assert por_mes["2026-08"]["perdidos"] == 0
    assert por_mes["2026-08"]["ativos"] == 3


def test_eventos_trazem_os_nomes_do_mes():
    painel = montar_painel_clientes(_base())
    eventos = painel["eventos"]

    assert [item["cliente"] for item in eventos["novos"]] == ["Cliente D"]
    assert [item["cliente"] for item in eventos["recuperados"]] == ["Cliente C"]
    assert eventos["recuperados"][0]["receita"] == 60
    assert eventos["perdidos"] == []


def test_perdido_mostra_receita_do_ultimo_mes_comprado():
    # Julho é o mês em que B completa a janela parado.
    base = _base()
    base = base.loc[base["Periodo_Mensal"] <= "2026-07"]
    painel = montar_painel_clientes(base)
    perdidos = painel["eventos"]["perdidos"]

    assert [item["cliente"] for item in perdidos] == ["Cliente B"]
    assert perdidos[0]["receita"] == 80
    assert perdidos[0]["ultimo_mes"] == "abr/26"


def test_primeiro_mes_da_base_nao_inventa_clientes_novos():
    painel = montar_painel_clientes(_base())
    primeiro = painel["movimento"][0]
    assert primeiro["periodo"] == "2026-01"
    assert primeiro["novos"] == 0
    assert primeiro["recuperados"] == 0


def test_curva_abc_usa_a_regua_do_analisador():
    painel = montar_painel_clientes(_base(), cortes=(30.0, 50.0, 60.0))
    concentracao = painel["concentracao"]
    faixas = {faixa["nome"]: faixa for faixa in concentracao["faixas"]}

    assert concentracao["clientes"] == 4
    assert concentracao["receita"] == 1280
    # A (62,5%) e B (acumulado 87,5%) cobrem os 80%.
    assert concentracao["clientes_80"] == 2
    assert concentracao["participacao_clientes_80"] == 50.0
    assert faixas["Grupo 1"]["clientes"] == 1
    assert faixas["Grupo 1"]["participacao"] == 62.5
    assert faixas["Demais"]["clientes"] == 1


def test_corte_invalido_cai_no_padrao():
    painel = montar_painel_clientes(_base(), cortes=(60.0, 30.0, 200.0))
    nomes = [faixa["nome"] for faixa in painel["concentracao"]["faixas"]]
    assert nomes == ["Grupo 1", "Grupo 2", "Grupo 3", "Demais"]


def test_top_clientes_marca_queda_contra_a_media():
    painel = montar_painel_clientes(_base())
    top = {item["cliente"]: item for item in painel["top_clientes"]}

    assert top["Cliente A"]["receita_atual"] == 100
    assert top["Cliente A"]["receita_media"] == 100
    assert top["Cliente A"]["variacao"] == 0
    # C tem média baixa (uma compra em seis meses): variação positiva, sem alerta.
    assert top["Cliente C"]["alerta"] is False
    # D nunca vendeu antes: sem base de comparação.
    assert top["Cliente D"]["variacao"] is None


def test_resumo_por_tag_soma_receita_da_janela():
    catalogo = [
        {"id": "atencao", "rotulo": "Atenção", "cor": "#f00", "ativa": True},
        {"id": "inativa", "rotulo": "Desligada", "cor": "#0f0", "ativa": False},
    ]
    painel = montar_painel_clientes(
        _base(),
        tags={"Cliente B": ["atencao"]},
        catalogo=catalogo,
    )
    assert [tag["id"] for tag in painel["tags"]] == ["atencao"]
    assert painel["tags"][0]["clientes"] == 1
    assert painel["tags"][0]["receita"] == 320
    assert painel["tags"][0]["participacao"] == 25.0


def test_balcao_fica_fora_do_painel_mas_e_contado():
    painel = montar_painel_clientes(_base(), clientes_balcao=["Cliente D"])
    assert painel["balcao_excluidos"] == 1
    assert painel["resumo"]["clientes_ativos"] == 2
    assert painel["resumo"]["novos"] == 0
    assert "Cliente D" not in {item["cliente"] for item in painel["top_clientes"]}


def test_modo_periodo_fechados_recua_quando_ultimo_mes_esta_em_aberto(monkeypatch):
    monkeypatch.setattr(periodo_mensal, "date", _DataFixa(_dt.date(2026, 8, 15)))
    painel = montar_painel_clientes(_base(), modo_periodo="fechados")
    assert painel["periodo_atual"] == "2026-07"


def test_modo_periodo_completo_mantem_o_ultimo_mes_da_base(monkeypatch):
    monkeypatch.setattr(periodo_mensal, "date", _DataFixa(_dt.date(2026, 8, 15)))
    painel = montar_painel_clientes(_base(), modo_periodo="completo")
    assert painel["periodo_atual"] == "2026-08"


def test_modo_periodo_mesmo_periodo_corta_o_historico_no_mesmo_dia(monkeypatch):
    """Mês corrente só tem movimento até o dia 1 — o histórico (julho) entra
    só com o que aconteceu até o dia 1, não o mês inteiro."""
    monkeypatch.setattr(periodo_mensal, "date", _DataFixa(_dt.date(2026, 8, 2)))
    linhas = [
        {**_linha("2026-07", "Cliente A", 100), "Data_Venda_Diaria": "2026-07-01"},
        {**_linha("2026-07", "Cliente A", 100), "Data_Venda_Diaria": "2026-07-15"},
        {**_linha("2026-08", "Cliente A", 10), "Data_Venda_Diaria": "2026-08-01"},
    ]
    painel = montar_painel_clientes(pd.DataFrame(linhas), modo_periodo="mesmo_periodo")
    assert painel["periodo_atual"] == "2026-08"
    assert painel["resumo"]["receita_media"] == 100.0


def test_base_sem_cliente_responde_indisponivel():
    base = _base().drop(columns=["Cliente"])
    painel = montar_painel_clientes(base)
    assert painel["disponivel"] is False
    assert "Cliente" in painel["mensagem"]
    assert painel["movimento"] == []
