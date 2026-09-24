"""Flag que aplica os cortes do Relatórios nas outras telas."""

from fastapi.testclient import TestClient

import pandas as pd

import db
import main
from dashboard_summary import aplicar_cortes_no_summary


def _restaurar(original):
    if original is None:
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "0")
    else:
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, original)


def test_padrao_desligado():
    original = db.obter_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS)
    try:
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "0")
        assert main.aplicar_cortes_relatorios() is False
    finally:
        _restaurar(original)


def test_ligar_e_desligar():
    original = db.obter_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS)
    try:
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "1")
        assert main.aplicar_cortes_relatorios() is True
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "0")
        assert main.aplicar_cortes_relatorios() is False
    finally:
        _restaurar(original)


def test_api_le_e_grava_a_flag():
    original = db.obter_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS)
    cliente = TestClient(main.app)
    try:
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "0")
        assert cliente.get("/api/dashboard/aplicar-cortes-relatorios").json()["ativo"] is False
        gravada = cliente.post("/api/dashboard/aplicar-cortes-relatorios", json={"ativo": True})
        assert gravada.status_code == 200
        assert gravada.json()["ativo"] is True
        assert cliente.get("/api/dashboard/aplicar-cortes-relatorios").json()["ativo"] is True
    finally:
        _restaurar(original)


def test_carregar_base_telas_exclui_cliente(monkeypatch):
    original = db.obter_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS)
    df = pd.DataFrame({
        "Cliente": ["Alice", "Bob"],
        "descricao": ["Filtro", "Pastilha"],
        "Receita": [10.0, 20.0],
    })
    monkeypatch.setattr(main, "_carregar_base", lambda *a, **k: (df.copy(), 0))
    monkeypatch.setattr(
        main, "_ler_config_escopo", lambda *a, **k: {"clientesExcluidos": ["Alice"]},
    )
    try:
        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "0")
        cru, _ = main._carregar_base_telas("EmpresaX")
        assert list(cru["Cliente"]) == ["Alice", "Bob"]

        db.definir_config_app(main.CHAVE_APLICAR_CORTES_RELATORIOS, "1")
        cortado, _ = main._carregar_base_telas("EmpresaX")
        assert list(cortado["Cliente"]) == ["Bob"]
    finally:
        _restaurar(original)


def test_summary_corta_cliente_excluido():
    summary = {
        "maps": {
            "s": ["Loja"],
            "c": ["Alice", "Bob"],
            "m": ["Wega"],
            "d": ["Filtro"],
            "r": ["R1"],
            "p": [202601],
        },
        "rows": [
            [0, 0, 0, 0, 0, 0, 100.0, 1, 40.0],
            [0, 0, 1, 0, 0, 0, 50.0, 2, 20.0],
        ],
        "monthly": [{"name": "jan/26", "rev": 150.0, "cmv": 60.0, "pid": 202601, "year": 2026}],
        "yoy": {"2026": 150.0},
        "kpis": {"rev": 150.0, "qty": 3, "avg": 75.0, "cnt": 2, "cmv": 60.0},
    }
    saida = aplicar_cortes_no_summary(summary, {"clientes_excluidos": ["Alice"]})
    assert saida["maps"]["c"] == ["Bob"]
    assert saida["kpis"]["rev"] == 50.0
    assert saida["kpis"]["qty"] == 2
    assert saida["kpis"]["cmv"] == 20.0
    assert len(saida["rows"]) == 1
