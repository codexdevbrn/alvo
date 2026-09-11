import datetime as _dt

import pandas as pd

import estoque_cobertura
from estoque_cobertura import montar_cobertura_estoque, montar_resumo_estoque


class _DataFixa:
    """Substitui `estoque_cobertura.date` para fixar "hoje" nos testes de mês fechado."""

    def __init__(self, hoje: _dt.date):
        self._hoje = hoje

    def today(self):
        return self._hoje


def _produto(codigo: str, *, fabricante: str, qtd: float, custo: float = 10.0) -> dict:
    return {
        "Loja": "Matriz",
        "NOME_FABRICANTE": fabricante,
        "descricao": f"Produto {codigo}",
        "CODIGO_INTERNO_PRODUTO": codigo,
        "CODIGO_REFERENCIA_PRODUTO": f"REF-{codigo}",
        "Qtd_estoque": qtd,
        "Preço_médio_de_venda": custo * 2,
        "Preço_médio_cmv": custo,
        "Último_custo": custo,
    }


def _estoque() -> pd.DataFrame:
    return pd.DataFrame([
        # gira bem: 90 em estoque, 35/mês
        _produto("A", fabricante="Marca A", qtd=90),
        # nunca vendeu: capital parado puro
        _produto("B", fabricante="Marca B", qtd=20, custo=12),
        # vende muito e o estoque acabou: ruptura
        _produto("C", fabricante="Marca A", qtd=5),
        # montanha parada: vende 1/mês com 400 em estoque
        _produto("D", fabricante="Marca B", qtd=400, custo=5),
    ])


def _vendas() -> pd.DataFrame:
    linhas = []
    for mes, qtd in enumerate((10, 20, 30, 40, 50, 60), start=1):
        linhas.append({"CODIGO_INTERNO_PRODUTO": "A", "Ano": 2026, "Mês": mes, "QTD": qtd})
    for mes in range(1, 7):
        linhas.append({"CODIGO_INTERNO_PRODUTO": "C", "Ano": 2026, "Mês": mes, "QTD": 120})
        linhas.append({"CODIGO_INTERNO_PRODUTO": "D", "Ano": 2026, "Mês": mes, "QTD": 1})
    return pd.DataFrame(linhas)


def test_soma_por_situacao_fecha_com_o_total():
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6)

    produtos = sum(item["produtos"] for item in resultado["por_situacao"])
    valor = sum(item["valor_estoque"] for item in resultado["por_situacao"])
    assert produtos == resultado["resumo"]["produtos"] == 4
    assert round(valor, 2) == resultado["resumo"]["valor_estoque"]


def test_resumo_e_mapa_classificam_igual():
    """As duas telas leem a mesma base; divergir de situação é o defeito a evitar."""
    mapa = montar_cobertura_estoque(_estoque(), _vendas(), meses=6)
    resumo = montar_resumo_estoque(_estoque(), _vendas(), meses=6)

    assert mapa["resumo"]["produtos"] == resumo["resumo"]["produtos"]
    assert mapa["resumo"]["ruptura"] == resumo["resumo"]["ruptura"]
    assert mapa["resumo"]["excesso"] == resumo["resumo"]["excesso"]
    assert mapa["resumo"]["sem_giro"] == resumo["resumo"]["sem_giro"]
    assert mapa["resumo"]["valor_estoque"] == resumo["resumo"]["valor_estoque"]


def test_ruptura_iminente_ordena_por_quem_para_de_faturar_primeiro():
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6)

    codigos = [item["codigo_interno"] for item in resultado["ruptura_iminente"]]
    assert codigos == ["C"]
    assert resultado["ruptura_iminente"][0]["venda_media"] == 120


def test_capital_parado_agrupa_fabricante_e_ignora_quem_gira():
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6)

    fabricantes = {item["fabricante"]: item for item in resultado["capital_parado_fabricante"]}
    # B (240) + D (2000) são da Marca B; A gira e C está em ruptura, nenhum parado.
    assert list(fabricantes) == ["Marca B"]
    assert fabricantes["Marca B"]["valor_estoque"] == 2240
    assert fabricantes["Marca B"]["produtos"] == 2
    assert resultado["resumo"]["valor_parado"] == 2240


def test_dinheiro_dormindo_traz_maior_capital_primeiro():
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6)

    itens = resultado["dinheiro_dormindo"]
    assert [item["codigo_interno"] for item in itens] == ["D", "B"]
    assert itens[0]["valor_estoque"] == 2000
    # D vendeu no último mês da base: parado é a cobertura, não a falta de saída.
    assert itens[0]["meses_sem_venda"] == 0
    # B nunca vendeu — sem último mês, o campo não inventa zero.
    assert itens[1]["meses_sem_venda"] is None


def test_meses_sem_venda_olha_alem_da_janela():
    """Produto parado há mais tempo que a janela não pode virar 'nunca vendeu'."""
    estoque = pd.DataFrame([_produto("E", fabricante="Marca C", qtd=50)])
    vendas = pd.DataFrame([
        {"CODIGO_INTERNO_PRODUTO": "E", "Ano": 2025, "Mês": 12, "QTD": 30},
        {"CODIGO_INTERNO_PRODUTO": "Z", "Ano": 2026, "Mês": 6, "QTD": 1},
    ])

    resultado = montar_resumo_estoque(estoque, vendas, meses=3)

    item = resultado["dinheiro_dormindo"][0]
    assert item["status"] == "no_sales"
    assert item["meses_sem_venda"] == 6


def test_cobertura_media_pesa_pelo_capital():
    """R$ 2.500 parados / R$ 355 saindo por mês, a custo."""
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6)

    # A: 35/mês × R$10 = 350 · C: 120/mês × R$10 = 1200 · D: 1/mês × R$5 = 5
    assert resultado["resumo"]["cobertura_media"] == round(3190 / 1555, 2)


def test_usar_mes_fechado_exclui_o_mes_corrente_em_aberto(monkeypatch):
    monkeypatch.setattr(estoque_cobertura, "date", _DataFixa(_dt.date(2026, 6, 15)))
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6, usar_mes_fechado=True)
    assert resultado["periodo_fim"] == "2026-05"


def test_usar_mes_fechado_false_inclui_o_mes_corrente(monkeypatch):
    monkeypatch.setattr(estoque_cobertura, "date", _DataFixa(_dt.date(2026, 6, 15)))
    resultado = montar_resumo_estoque(_estoque(), _vendas(), meses=6, usar_mes_fechado=False)
    assert resultado["periodo_fim"] == "2026-06"


def test_base_vazia_devolve_estrutura_completa():
    resultado = montar_resumo_estoque(pd.DataFrame(), pd.DataFrame(), meses=6)

    assert resultado["resumo"]["produtos"] == 0
    assert resultado["resumo"]["cobertura_media"] is None
    assert resultado["por_situacao"] == []
    assert resultado["ruptura_iminente"] == []
    assert resultado["capital_parado_fabricante"] == []
    assert resultado["dinheiro_dormindo"] == []
