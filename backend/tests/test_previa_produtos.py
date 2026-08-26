import os
import sys

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import main as api


def _base_produtos():
    return pd.DataFrame(
        {
            "descricao": ["Produto A", "Produto B", "Produto C"],
            "Receita": [70.0, 20.0, 10.0],
        }
    )


def _usar_base(monkeypatch, df):
    monkeypatch.setattr(
        api,
        "_carregar_base",
        lambda empresa=None, loja=None, copiar=False: (df, 0),
    )


def _por_produto(resposta):
    return {item["produto"]: item for item in resposta["itens"]}


def test_previa_recalcula_curva_sem_produtos_excluidos(monkeypatch):
    """Prévia deve espelhar a base filtrada usada pela análise final."""
    _usar_base(monkeypatch, _base_produtos())

    resposta = api.previa_produtos(
        api.ParametrosProdutos(produtos_excluidos=["Produto A"], corte_produtos=80),
        usuario="admin",
    )

    itens = _por_produto(resposta)
    assert resposta["grupos"][0]["quantidade"] == 2
    assert itens["Produto B"]["percentual_receita"] == 20 / 30 * 100
    assert itens["Produto B"]["grupo"] == "Grupo 1"
    assert itens["Produto A"]["grupo"] == ""
    assert itens["Produto A"]["percentual_receita"] is None
    assert itens["Produto A"]["percentual_acumulado"] is None
    assert itens["Produto A"]["fora_por_regra"] is None


def test_corte_percentual_manda_sem_teto_de_itens(monkeypatch):
    """Não existe mais teto de itens no alto giro: quem está abaixo do corte
    percentual entra no Grupo 1, por mais produtos que isso signifique."""
    df = pd.DataFrame(
        {
            "descricao": [f"Produto {i:03d}" for i in range(100)],
            "Receita": [100.0] * 100,
        }
    )
    _usar_base(monkeypatch, df)

    resposta = api.previa_produtos(
        api.ParametrosProdutos(corte_produtos=90), usuario="admin",
    )

    assert resposta["corte_produtos"] == 90
    assert resposta["grupos"][0]["quantidade"] == 90
    assert resposta["grupos"][1]["quantidade"] == 10


def test_desconsiderar_demais_marca_sem_apagar_a_curva(monkeypatch):
    """A regra não vira exclusão: o produto mantém faixa e percentuais e só
    ganha o motivo — é o que impede a foto congelada no config.json."""
    _usar_base(monkeypatch, _base_produtos())

    resposta = api.previa_produtos(
        api.ParametrosProdutos(corte_produtos=80, desconsiderar_demais_produtos=True),
        usuario="admin",
    )

    itens = _por_produto(resposta)
    assert itens["Produto A"]["fora_por_regra"] is None
    assert itens["Produto C"]["fora_por_regra"] == "demais"
    assert itens["Produto C"]["grupo"] == "Demais"
    assert itens["Produto C"]["percentual_receita"] == 10.0
    assert resposta["produtos_fora_por_regra"] == ["Produto C"]


def test_nao_harmonizado_sai_do_denominador_da_curva(monkeypatch):
    """O balde "NÃO HARMONIZADO" costuma ser o maior item da base; deixá-lo no
    denominador deslocaria a curva inteira."""
    df = pd.DataFrame(
        {
            "descricao": ["NÃO HARMONIZADO", "Produto A", "Produto B"],
            "Receita": [900.0, 70.0, 30.0],
        }
    )
    _usar_base(monkeypatch, df)

    resposta = api.previa_produtos(
        api.ParametrosProdutos(corte_produtos=80, desconsiderar_nao_harmonizados=True),
        usuario="admin",
    )

    itens = _por_produto(resposta)
    assert itens["NÃO HARMONIZADO"]["fora_por_regra"] == "nao_harmonizado"
    assert itens["NÃO HARMONIZADO"]["percentual_receita"] is None
    assert itens["Produto A"]["percentual_receita"] == 70.0
    assert resposta["produtos_fora_por_regra"] == ["NÃO HARMONIZADO"]


def test_analise_aplica_as_regras_de_produto(monkeypatch):
    """As mesmas regras precisam valer no relatório final, não só na prévia."""
    df = pd.DataFrame(
        {
            "descricao": ["NÃO HARMONIZADO", "Produto A", "Produto B", "Produto C"],
            "Receita": [900.0, 70.0, 20.0, 10.0],
        }
    )
    _usar_base(monkeypatch, df)

    filtrado = api._carregar_df_filtrado(
        [],
        corte_produtos=80,
        desconsiderar_demais_produtos=True,
        desconsiderar_nao_harmonizados=True,
    )

    assert sorted(filtrado["descricao"]) == ["Produto A", "Produto B"]


def test_analise_sem_regras_nao_toca_na_base(monkeypatch):
    df = _base_produtos()
    _usar_base(monkeypatch, df)

    assert api._carregar_df_filtrado([]) is df
