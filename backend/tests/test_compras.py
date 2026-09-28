"""Tela Compras: fórmulas da planilha APMF, arredondamento, lojas, custo e mês corrente."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

import compras as cp

CORTE = date(2026, 9, 24)  # mês corrente = set/2026; fechados = out/2025 … ago/2026
FECHADOS = [(2025, m) for m in (10, 11, 12)] + [(2026, m) for m in range(1, 9)]


def _estoque(linhas):
    return pd.DataFrame([
        {
            "Loja": loja, "CODIGO_INTERNO_PRODUTO": codigo, "CODIGO_REFERENCIA_PRODUTO": f"REF-{codigo}",
            "descricao": f"Item {codigo}", "NOME_FABRICANTE": fab, "Qtd_estoque": qtd,
        }
        for loja, codigo, qtd, fab in linhas
    ])


def _vendas(loja, codigo, qtds, *, custo=10.0, corrente=0.0):
    """Uma linha por mês fechado (11 QTDs, do mais antigo ao último) + o corrente."""
    assert len(qtds) == 11
    linhas = [
        {"Nome_Loja": loja, "CODIGO_INTERNO_PRODUTO": codigo, "Ano": ano, "Mês": mes,
         "QTD": float(qtd), "CMV": float(qtd) * custo}
        for (ano, mes), qtd in zip(FECHADOS, qtds)
    ]
    linhas.append({"Nome_Loja": loja, "CODIGO_INTERNO_PRODUTO": codigo, "Ano": 2026, "Mês": 9,
                   "QTD": corrente, "CMV": corrente * custo})
    return linhas


def _rodar(estoque, vendas, corte=CORTE, **kwargs):
    base = cp.preparar_base_compras(estoque, pd.DataFrame(vendas), corte=corte)
    kwargs.setdefault("somente_recomendados", False)
    return cp.calcular_compras(base, **kwargs)


def _por_codigo(resp):
    """SKUs de todos os produtos, pelo código."""
    return {sku["codigo"]: sku for produto in resp["itens"] for sku in produto["skus"]}


def _codigos(resp):
    """Um SKU por produto nestes cenários: a ordem dos produtos é a dos códigos."""
    return [produto["skus"][0]["codigo"] for produto in resp["itens"]]


def _casos_referencia():
    estoque = _estoque([("1", "8526", 0, "A"), ("1", "51347", 10, "B"), ("1", "25607", 9, "C")])
    vendas = (
        _vendas("1", "8526", [275] * 11, corrente=90)
        # maior 80, 3 últimos 40/40/50 (média 43,33), último 50 → (80 + 86,67 + 50) / 4 = 54,17
        + _vendas("1", "51347", [80, 10, 10, 10, 10, 10, 10, 10, 40, 40, 50])
        + _vendas("1", "25607", [25] * 11)
    )
    return estoque, vendas


def test_casos_de_referencia_da_planilha():
    """Impulsionado · Imediato · caixa Não: 8526 → 165, 51347 → 23, 25607 → 6."""
    itens = _por_codigo(_rodar(*_casos_referencia()))

    assert itens["8526"]["media"] == pytest.approx(275.0)
    assert itens["8526"]["estoque_alvo"] == pytest.approx(165.0)
    assert itens["8526"]["sugestao"] == 165
    assert itens["51347"]["media"] == pytest.approx(54.1667, abs=1e-4)
    assert itens["51347"]["estoque_alvo"] == pytest.approx(32.5)
    assert itens["51347"]["sugestao"] == 23  # 22,5 meio pra cima; o round bancário daria 22
    assert itens["25607"]["estoque_alvo"] == pytest.approx(15.0)
    assert itens["25607"]["sugestao"] == 6
    assert {item["coluna"] for item in itens.values()} == {"minimo"}


def test_meio_pra_cima_nao_e_bancario():
    assert cp.meio_pra_cima(2.5) == 3
    assert cp.meio_pra_cima(22.5) == 23
    assert cp.meio_pra_cima(0.49) == 0
    assert cp.meio_pra_cima(12.345, 2) == pytest.approx(12.35)
    # resíduo do ponto flutuante: 54,1666… × 0,6 − 10
    assert cp.meio_pra_cima((80 + 2 * 130 / 3 + 50) / 4 * 0.6 - 10) == 23


def test_multiplicadores_por_prazo_giro_e_caixa():
    estoque, vendas = _estoque([("1", "X", 0, "A")]), _vendas("1", "X", [100] * 11)
    casos = {
        ("regular", "impulsionado", False): (100, "minimo"),
        ("industria", "impulsionado", True): (100, "minimo"),
        ("imediato", "impulsionado", True): (45, "minimo"),
        ("imediato", "nao_impulsionado", False): (90, "maximo"),
        ("industria", "nao_impulsionado", False): (210, "maximo"),
    }
    for (prazo, giro, caixa), (sugestao, coluna) in casos.items():
        item = _rodar(estoque, vendas, prazo_entrega=prazo, giro=giro, caixa_apertado=caixa)["itens"][0]
        assert (item["sugestao"], item["coluna"]) == (sugestao, coluna), (prazo, giro, caixa)


def test_negativo_vira_zero():
    # mês com devolução maior que a venda conta 0, não −30; estoque negativo conta 0
    estoque = _estoque([("1", "X", -5, "A")])
    vendas = _vendas("1", "X", [10] * 10 + [-30])
    item = _rodar(estoque, vendas)["itens"][0]
    assert item["venda_mensal"][10] == 0
    assert item["estoque"] == 0
    # (10 + 2 × 20/3 + 0) / 4 = 5,8333 → alvo 3,5 → 4
    assert item["media"] == pytest.approx(5.8333, abs=1e-4)
    assert item["sugestao"] == 4


def test_nao_impulsionado_com_caixa_apertado_nunca_compra():
    resp = _rodar(*_casos_referencia(), giro="nao_impulsionado", caixa_apertado=True)
    assert [item["sugestao"] for item in resp["itens"]] == [None, None, None]
    assert {item["coluna"] for item in resp["itens"]} == {None}
    assert resp["itens_a_comprar"] == 0
    assert resp["nao_recomendados"] == 3
    assert resp["total_compra"] == 0

    so_recomendados = _rodar(*_casos_referencia(), giro="nao_impulsionado", caixa_apertado=True,
                             somente_recomendados=True)
    assert so_recomendados["itens"] == []
    assert so_recomendados["nao_recomendados"] == 3


def test_dia_primeiro_o_mes_que_fechou_entra_na_media():
    """Em 1º/set o corte é 31/ago: agosto é fechado e inteiro, o corrente é setembro vazio."""
    estoque = _estoque([("1", "X", 0, "A")])
    vendas = [
        {"Nome_Loja": "1", "CODIGO_INTERNO_PRODUTO": "X", "Ano": ano, "Mês": mes, "QTD": 10.0, "CMV": 100.0}
        for ano, mes in FECHADOS[:-1]
    ] + [{"Nome_Loja": "1", "CODIGO_INTERNO_PRODUTO": "X", "Ano": 2026, "Mês": 8, "QTD": 50.0, "CMV": 500.0}]

    resp = _rodar(estoque, vendas, corte=date(2026, 8, 31))
    assert resp["meses"][-1] == "2026-09"
    assert resp["meses"][-2] == "2026-08"
    item = resp["itens"][0]
    assert item["venda_mensal"][10] == 50
    assert item["venda_mensal"][11] == 0
    # (50 + 2 × 70/3 + 50) / 4 = 36,67 — com agosto fora, sairia 10
    assert item["media"] == pytest.approx(36.6667, abs=1e-4)

    assert cp.mes_corrente_indice(date(2026, 8, 31)) == 2026 * 12 + 8
    assert cp.mes_corrente_indice(date(2026, 9, 24)) == 2026 * 12 + 8


def test_calcula_por_loja_e_soma_as_sugestoes():
    """Sobra na loja A não cobre falta na B."""
    estoque = _estoque([("A", "X", 100, "F"), ("B", "X", 0, "F")])
    vendas = _vendas("A", "X", [10] * 11) + _vendas("B", "X", [10] * 11)
    item = _rodar(estoque, vendas)["itens"][0]

    assert item["sugestao"] == 6          # somando o escopo daria 0 (alvo 12, estoque 100)
    assert item["estoque"] == 100
    assert item["media"] == pytest.approx(20)
    assert item["estoque_alvo"] == pytest.approx(12)
    assert item["venda_mensal"][0] == 20
    assert item["lojas"] == [
        {"loja": "A", "estoque": 100, "sugestao": None},
        {"loja": "B", "estoque": 0, "sugestao": 6},
    ]


def test_custo_medio_dos_3_ultimos_fechados_e_sem_custo_fora_do_total():
    estoque = _estoque([("1", "X", 0, "A"), ("1", "Y", 0, "A")])
    vendas = (
        _vendas("1", "X", [10] * 8 + [0, 0, 0], custo=5.0)  # sem venda nos 3 últimos → sem custo
        + [dict(linha, CMV=linha["QTD"] * (20.0 if linha["Mês"] in (6, 7, 8) else 1.0))
           for linha in _vendas("1", "Y", [10] * 11)]
    )
    resp = _rodar(estoque, vendas)
    itens = _por_codigo(resp)

    assert itens["X"]["custo"] is None
    assert itens["X"]["valor"] is None
    assert itens["X"]["sugestao"] == 2   # (10 + 0 + 0) / 4 × 0,6 = 1,5 → 2
    assert itens["Y"]["custo"] == pytest.approx(20.0)
    assert itens["Y"]["valor"] == pytest.approx(6 * 20.0)
    assert resp["produtos_sem_custo"] == 1
    assert resp["total_compra"] == pytest.approx(120.0)
    assert _codigos(resp) == ["Y", "X"]  # valor nulo vai para o fim


def test_kpis_antes_do_limite_e_filtros():
    estoque = _estoque([("1", f"P{i}", 0, "A" if i % 2 else "B") for i in range(5)])
    vendas = sum((_vendas("1", f"P{i}", [10 * (i + 1)] * 11) for i in range(5)), [])

    resp = _rodar(estoque, vendas, limite=2)
    assert resp["itens_exibidos"] == 2
    assert resp["itens_total"] == 5
    assert resp["limitado"] is True
    assert resp["itens_a_comprar"] == 5
    assert resp["total_compra"] == pytest.approx(sum(6 * (i + 1) * 10 for i in range(5)))
    assert _codigos(resp) == ["P4", "P3"]

    filtrado = _rodar(estoque, vendas, fabricante="a")
    assert {item["fabricante"] for item in filtrado["itens"]} == {"A"}
    assert filtrado["fabricantes"] == ["A", "B"]  # o select não encolhe ao filtrar
    assert _codigos(_rodar(estoque, vendas, busca="p2")) == ["P2"]


def test_agrupa_skus_por_descricao_e_fabricante():
    """Produto = descrição × fabricante; o SKU abre embaixo, a conta segue por SKU."""
    estoque = pd.DataFrame([
        {"Loja": "1", "CODIGO_INTERNO_PRODUTO": codigo, "CODIGO_REFERENCIA_PRODUTO": "",
         "descricao": desc, "NOME_FABRICANTE": fab, "Qtd_estoque": qtd}
        for codigo, desc, fab, qtd in (
            ("A1", "Lubrificante", "IPIRANGA", 0),
            ("A2", "Lubrificante", "IPIRANGA", 100),   # sobra no A2 não cobre falta no A1
            ("B1", "Lubrificante", "VALVOLINE", 0),
        )
    ])
    vendas = (
        _vendas("1", "A1", [10] * 11, custo=2.0)
        + _vendas("1", "A2", [10] * 11, custo=3.0)
        + _vendas("1", "B1", [5] * 11, custo=4.0)
    )
    resp = _rodar(estoque, vendas)
    produtos = {(p["descricao"], p["fabricante"]): p for p in resp["itens"]}

    ipiranga = produtos[("Lubrificante", "IPIRANGA")]
    assert [sku["codigo"] for sku in ipiranga["skus"]] == ["A1", "A2"]  # valor decrescente
    assert ipiranga["sugestao"] == 6
    assert ipiranga["valor"] == pytest.approx(12.0)
    assert ipiranga["estoque"] == 100
    assert ipiranga["venda_mensal"][0] == 20
    assert ipiranga["lojas"] == [{"loja": "1", "estoque": 100, "sugestao": 6}]
    assert produtos[("Lubrificante", "VALVOLINE")]["sugestao"] == 3
    assert resp["itens_a_comprar"] == 2        # SKUs
    assert resp["produtos_a_comprar"] == 2     # descrição × fabricante
    assert resp["itens_total"] == 2

    so_recomendados = _rodar(estoque, vendas, somente_recomendados=True)
    ipiranga = next(p for p in so_recomendados["itens"] if p["fabricante"] == "IPIRANGA")
    assert [sku["codigo"] for sku in ipiranga["skus"]] == ["A1"]


def test_parametro_invalido():
    base = cp.preparar_base_compras(_estoque([]), pd.DataFrame(), corte=CORTE)
    with pytest.raises(ValueError):
        cp.calcular_compras(base, prazo_entrega="amanha")
    with pytest.raises(ValueError):
        cp.calcular_compras(base, giro="rapido")
    assert cp.calcular_compras(base)["itens"] == []


# --- Exceções de prazo e giro (SKU > produto > tela) ------------------------

def _mesmo_produto():
    """SKUs 1 e 2 no produto "Amortecedor" × MONROE; SKU 3 em outro. Média 275, estoque 0."""
    estoque = _estoque([("1", "1", 0, "MONROE"), ("1", "2", 0, "MONROE"), ("1", "3", 0, "COFAP")])
    estoque["descricao"] = ["Amortecedor", "Amortecedor", "Amortecedor"]
    vendas = _vendas("1", "1", [275] * 11) + _vendas("1", "2", [275] * 11) + _vendas("1", "3", [275] * 11)
    return estoque, vendas


def test_excecao_sku_sobrepoe_produto_que_sobrepoe_a_tela():
    excecoes = cp.normalizar_excecoes({
        "produtos": [{"descricao": "Amortecedor", "fabricante": "MONROE", "prazo": "regular"}],
        "skus": {"2": {"prazo": "industria"}},
    })
    resp = _rodar(*_mesmo_produto(), excecoes=excecoes)
    skus = _por_codigo(resp)
    assert skus["1"]["sugestao"] == 275  # produto: regular 1,00
    assert skus["2"]["sugestao"] == 385  # SKU: indústria 1,40
    assert skus["3"]["sugestao"] == 165  # tela: imediato 0,60
    assert skus["2"]["excecao"] == {"prazo": "industria"} and skus["1"]["excecao"] is None
    assert (skus["1"]["prazo"], skus["2"]["prazo"], skus["3"]["prazo"]) == ("regular", "industria", "imediato")

    monroe = next(p for p in resp["itens"] if p["fabricante"] == "MONROE")
    assert monroe["sugestao"] == 660
    assert monroe["excecao"] == {"prazo": "regular"} and monroe["prazo"] == "regular"
    assert monroe["giro"] == "impulsionado" and monroe["skus_com_excecao"] == 1


def test_excecao_de_giro_com_caixa_apertado_segue_a_regra_de_nunca_comprar():
    # Tela impulsionado + caixa: SKU marcado não impulsionado nunca compra.
    excecoes = cp.normalizar_excecoes({"skus": {"2": {"giro": "nao_impulsionado"}}})
    skus = _por_codigo(_rodar(*_mesmo_produto(), caixa_apertado=True, excecoes=excecoes))
    assert skus["1"]["sugestao"] == 124  # 275 × 0,45 = 123,75
    assert skus["2"]["sugestao"] is None
    assert skus["2"]["coluna"] is None and skus["2"]["estoque_alvo"] is None

    # E o contrário: a tela nunca compra, mas o SKU impulsionado compra.
    excecoes = cp.normalizar_excecoes({"skus": {"2": {"giro": "impulsionado"}}})
    resp = _rodar(*_mesmo_produto(), giro="nao_impulsionado", caixa_apertado=True, excecoes=excecoes)
    skus = _por_codigo(resp)
    assert skus["1"]["sugestao"] is None and skus["2"]["sugestao"] == 124
    assert skus["2"]["coluna"] == "minimo"
    monroe = next(p for p in resp["itens"] if p["fabricante"] == "MONROE")
    assert monroe["coluna"] is None and monroe["sugestao"] == 124
    assert monroe["estoque_alvo"] == pytest.approx(123.75)


def test_filtro_de_produto_traz_todos_os_skus_dele():
    resp = _rodar(*_mesmo_produto(), produto=("Amortecedor", "MONROE"))
    assert len(resp["itens"]) == 1
    assert sorted(s["codigo"] for s in resp["itens"][0]["skus"]) == ["1", "2"]


def test_arquivo_de_excecoes_ida_e_volta_e_edicao():
    bruto = {
        "produtos": [
            {"descricao": "Amortecedor", "fabricante": "MONROE", "prazo": "regular", "giro": "xpto"},
            {"descricao": "", "fabricante": "", "prazo": "regular"},  # sem chave: sai
            "lixo",
        ],
        "skus": {"2": {"prazo": "industria"}, "3": {"prazo": "amanha"}},
    }
    exc = cp.normalizar_excecoes(bruto)
    assert exc == {"produtos": {("Amortecedor", "MONROE"): {"prazo": "regular"}}, "skus": {"2": {"prazo": "industria"}}}
    assert cp.normalizar_excecoes(cp.excecoes_para_arquivo(exc)) == exc

    exc = cp.definir_excecao(exc, nivel="sku", codigo="9", prazo=None, giro="nao_impulsionado")
    assert exc["skus"]["9"] == {"giro": "nao_impulsionado"}
    exc = cp.definir_excecao(exc, nivel="sku", codigo="9", prazo=None, giro=None)
    assert "9" not in exc["skus"]
    with pytest.raises(ValueError):
        cp.definir_excecao(exc, nivel="sku", codigo="9", prazo="amanha", giro=None)

    exc = cp.limpar_excecoes_produto(exc, descricao="Amortecedor", fabricante="MONROE", codigos=["2"])
    assert exc == {"produtos": {}, "skus": {}}


def test_base_em_disco_da_a_mesma_resposta(tmp_path):
    """A base que o lote grava em `_cache_telas` volta idêntica: mesma resposta em
    qualquer cenário, com e sem exceção. Chave diferente não é lida."""
    import cache_telas

    estoque, vendas = _casos_referencia()
    base = cp.preparar_base_compras(estoque, pd.DataFrame(vendas), corte=CORTE)
    cache_telas.gravar_tabelas(tmp_path, "compras-base", ("x", 1), *cp.base_para_disco(base))
    lida = cache_telas.ler_tabelas(tmp_path, "compras-base", ("x", 1), cp.TABELAS_BASE)
    assert lida is not None
    de_volta = cp.base_do_disco(*lida)

    excecoes = cp.normalizar_excecoes({"skus": {"51347": {"prazo": "industria"}}})
    for kwargs in ({}, {"giro": "nao_impulsionado", "prazo_entrega": "regular"}, {"excecoes": excecoes}):
        assert cp.calcular_compras(de_volta, somente_recomendados=False, **kwargs) == \
            cp.calcular_compras(base, somente_recomendados=False, **kwargs)
    assert cache_telas.ler_tabelas(tmp_path, "compras-base", ("x", 2), cp.TABELAS_BASE) is None
