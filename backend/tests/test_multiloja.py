"""Contrato do escopo multi-loja usado por base, configurações e relatórios."""

import json

import pandas as pd
import pytest
from fastapi import HTTPException

import main


def _escopo(*lojas: str) -> str:
    return main.PREFIXO_ESCOPO_MULTILOJAS + json.dumps(list(lojas), ensure_ascii=False)


def test_normaliza_uma_ou_varias_lojas_sem_ambiguidade():
    assert main._normalizar_lojas(None) == []
    assert main._normalizar_lojas("Loja A") == ["Loja A"]
    assert main._normalizar_lojas(_escopo("Loja B", "Loja A", "Loja A")) == ["Loja A", "Loja B"]

    # Vírgula faz parte do nome e nunca é tratada como separador.
    com_virgula = _escopo("Matriz, Centro", "Filial")
    assert main._normalizar_lojas(com_virgula) == ["Filial", "Matriz, Centro"]
    assert main._normalizar_loja(com_virgula) == '@lojas:["Filial","Matriz, Centro"]'


def test_filtra_uniao_das_lojas_selecionadas():
    df = pd.DataFrame({
        "Loja": ["A", "B", "C", "A"],
        "Receita": [10.0, 20.0, 30.0, 40.0],
    })

    filtrado = main._filtrar_loja(df, _escopo("A", "C"))

    assert filtrado["Loja"].tolist() == ["A", "C", "A"]
    assert filtrado["Receita"].sum() == 80.0
    assert filtrado is not df


def test_escopo_multiloja_invalido_e_rejeitado():
    with pytest.raises(HTTPException) as erro:
        main._normalizar_lojas("@lojas:{invalido}")
    assert erro.value.status_code == 400
