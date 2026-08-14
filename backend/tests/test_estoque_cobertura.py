import pandas as pd

from estoque_cobertura import montar_cobertura_estoque


def _estoque() -> pd.DataFrame:
    return pd.DataFrame([
        {
            "Loja": "Matriz",
            "NOME_FABRICANTE": "Marca A",
            "descricao": "Produto saudável",
            "CODIGO_INTERNO_PRODUTO": "A",
            "CODIGO_REFERENCIA_PRODUTO": "REF-A",
            "Qtd_estoque": 60,
            "Preço_médio_de_venda": 20,
            "Preço_médio_cmv": 8,
            "Último_custo": 10,
        },
        {
            "Loja": "Filial",
            "NOME_FABRICANTE": "Marca A",
            "descricao": "Produto saudável",
            "CODIGO_INTERNO_PRODUTO": "A",
            "CODIGO_REFERENCIA_PRODUTO": "REF-A",
            "Qtd_estoque": 30,
            "Preço_médio_de_venda": 20,
            "Preço_médio_cmv": 8,
            "Último_custo": 10,
        },
        {
            "Loja": "Matriz",
            "NOME_FABRICANTE": "Marca B",
            "descricao": "Produto sem giro",
            "CODIGO_INTERNO_PRODUTO": "B",
            "CODIGO_REFERENCIA_PRODUTO": "REF-B",
            "Qtd_estoque": 20,
            "Preço_médio_de_venda": 30,
            "Preço_médio_cmv": 12,
            "Último_custo": 0,
        },
    ])


def _vendas() -> pd.DataFrame:
    linhas = []
    for mes, qtd in enumerate((10, 20, 30, 40, 50, 60), start=1):
        linhas.append({
            "Nome_Loja": "Matriz",
            "NOME_FABRICANTE": "Marca A",
            "descricao": "Produto saudável",
            "CODIGO_INTERNO_PRODUTO": "A",
            "CODIGO_REFERENCIA_PRODUTO": "REF-A",
            "Ano": 2026,
            "Mês": mes,
            "QTD": qtd,
        })
    return pd.DataFrame(linhas)


def test_combina_lojas_calcula_cobertura_valor_e_tendencia():
    resultado = montar_cobertura_estoque(_estoque(), _vendas(), meses=6)
    itens = {item["codigo_interno"]: item for item in resultado["itens"]}

    produto = itens["A"]
    assert produto["estoque"] == 90
    assert produto["venda_media"] == 35
    assert produto["cobertura"] == round(90 / 35, 4)
    assert produto["valor_estoque"] == 900
    assert produto["variacao_pct"] == 150
    assert produto["status"] == "normal"
    assert resultado["periodo_inicio"] == "2026-01"
    assert resultado["periodo_fim"] == "2026-06"


def test_produto_sem_venda_entra_no_resumo_com_fallback_de_cmv():
    resultado = montar_cobertura_estoque(_estoque(), _vendas(), meses=6)
    itens = {item["codigo_interno"]: item for item in resultado["itens"]}

    produto = itens["B"]
    assert produto["status"] == "no_sales"
    assert produto["cobertura"] is None
    assert produto["valor_estoque"] == 240
    assert resultado["resumo"]["sem_giro"] == 1
    assert resultado["resumo"]["produtos"] == 2


def test_mes_por_extenso_entra_na_janela_de_vendas():
    estoque = _estoque().iloc[[0]].copy()
    vendas = pd.DataFrame([
        {"CODIGO_INTERNO_PRODUTO": "A", "Ano": 2026, "Mês": "Março", "QTD": 12},
        {"CODIGO_INTERNO_PRODUTO": "A", "Ano": 2026, "Mês": "abril", "QTD": 18},
    ])

    resultado = montar_cobertura_estoque(estoque, vendas, meses=2)

    assert resultado["periodo_inicio"] == "2026-03"
    assert resultado["periodo_fim"] == "2026-04"
    assert resultado["itens"][0]["venda_media"] == 15.0
