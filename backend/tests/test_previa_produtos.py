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


def test_previa_recalcula_curva_sem_produtos_excluidos(monkeypatch):
    """Prévia deve espelhar a base filtrada usada pela análise final."""
    monkeypatch.setattr(
        api,
        "_carregar_base",
        lambda empresa=None, loja=None, copiar=False: (_base_produtos(), 0),
    )

    resposta = api.previa_produtos(
        api.ParametrosProdutos(
            produtos_excluidos=["Produto A"],
            corte_produtos=80,
            ajustar_cortes=False,
        ),
        usuario="admin",
    )

    itens = {item["produto"]: item for item in resposta["itens"]}
    assert resposta["grupos"][0]["quantidade"] == 2
    assert itens["Produto B"]["percentual_receita"] == 20 / 30 * 100
    assert itens["Produto B"]["grupo"] == "Grupo 1"
    assert itens["Produto A"]["grupo"] == ""
    assert itens["Produto A"]["percentual_receita"] is None
    assert itens["Produto A"]["percentual_acumulado"] is None
