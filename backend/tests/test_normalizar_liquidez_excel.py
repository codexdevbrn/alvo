from pathlib import Path

import pandas as pd

# Importar main inclui a raiz do projeto no sys.path, como acontece no servidor.
import main  # noqa: F401
import normalizar_liquidez as liquidez


def test_excel_e_lido_como_texto(monkeypatch):
    esperado = pd.DataFrame({"Produto": ["00123"]})
    chamadas = []

    def falso_read_excel(caminho, **opcoes):
        chamadas.append((caminho, opcoes))
        return esperado

    monkeypatch.setattr(liquidez.pd, "read_excel", falso_read_excel)

    resultado = liquidez.ler_tabela_liquidez(Path("Dados_Estoque_Empresa.xlsx"))

    assert resultado is esperado
    assert chamadas == [(Path("Dados_Estoque_Empresa.xlsx"), {"dtype": str})]


def test_normalizacao_descarta_linhas_sem_produto(monkeypatch):
    estoque = pd.DataFrame([
        {
            "Loja": "GOMEC",
            "Fabricante": "Marca",
            "Descrição": "Válido",
            "Produto": "00123",
            "CODIGO_REFERENCIA_PRODUTO": "REF",
            "QTD Estoque": "4",
            "Preço médio de venda": "20",
            "Preço médio cmv": "10",
            "Último custo": "8",
        },
        {
            "Loja": "GOMEC",
            "Fabricante": None,
            "Descrição": None,
            "Produto": None,
            "CODIGO_REFERENCIA_PRODUTO": None,
            "QTD Estoque": None,
            "Preço médio de venda": None,
            "Preço médio cmv": None,
            "Último custo": None,
        },
    ])
    monkeypatch.setattr(liquidez, "ler_tabela_liquidez", lambda _caminho: estoque)

    resultado = liquidez.normalizar_estoque(Path("Dados_Estoque_Empresa.xlsx"))

    assert resultado["CODIGO_INTERNO_PRODUTO"].tolist() == ["00123"]
