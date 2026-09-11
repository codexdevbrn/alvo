"""Flag que esconde a tela de vendedores até a coluna existir na base."""

from fastapi.testclient import TestClient

import db
import main


def _restaurar(original):
    if original is None:
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, "0")
    else:
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, original)


def test_padrao_e_escondido():
    original = db.obter_config_app(main.CHAVE_TELA_VENDEDORES)
    try:
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, "0")
        assert main.tela_vendedores_visivel() is False
    finally:
        _restaurar(original)


def test_ligar_e_desligar():
    original = db.obter_config_app(main.CHAVE_TELA_VENDEDORES)
    try:
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, "1")
        assert main.tela_vendedores_visivel() is True
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, "0")
        assert main.tela_vendedores_visivel() is False
    finally:
        _restaurar(original)


def test_valor_invalido_conta_como_escondido():
    original = db.obter_config_app(main.CHAVE_TELA_VENDEDORES)
    try:
        for valor in ("", "0", "sim", "true", "2"):
            db.definir_config_app(main.CHAVE_TELA_VENDEDORES, valor)
            assert main.tela_vendedores_visivel() is False, valor
    finally:
        _restaurar(original)


def test_api_some_quando_desligada():
    original = db.obter_config_app(main.CHAVE_TELA_VENDEDORES)
    cliente = TestClient(main.app)
    try:
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, "0")
        resposta = cliente.get("/api/vendedores/Altese")
        assert resposta.status_code == 404
        assert "Configurações" in resposta.json()["detail"]
    finally:
        _restaurar(original)


def test_dashboard_le_e_grava_a_flag():
    original = db.obter_config_app(main.CHAVE_TELA_VENDEDORES)
    cliente = TestClient(main.app)
    try:
        db.definir_config_app(main.CHAVE_TELA_VENDEDORES, "0")
        assert cliente.get("/api/dashboard/tela-vendedores").json()["visivel"] is False
        gravada = cliente.post("/api/dashboard/tela-vendedores", json={"visivel": True})
        assert gravada.status_code == 200
        assert gravada.json()["visivel"] is True
        assert cliente.get("/api/dashboard/tela-vendedores").json()["visivel"] is True
    finally:
        _restaurar(original)
