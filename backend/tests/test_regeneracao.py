"""Trava de regeneração de bases.

Existe porque a pasta de trabalho é compartilhada e, com o app distribuído como
executável, várias máquinas passam a poder escrever nela. Duas regenerando a mesma
empresa não dá erro: o OneDrive cria cópia de conflito em silêncio.
"""

import pytest
from fastapi import HTTPException

import db
import main


@pytest.fixture(autouse=True)
def _config_limpa():
    """Restaura o valor original — é estado persistido, vazaria entre testes."""
    original = db.obter_config_app(main.CHAVE_REGENERACAO_PERMITIDA)
    yield
    if original is None:
        db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, "0")
    else:
        db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, original)


def test_padrao_e_desligado():
    """Instalação nova não regenera: a maioria das máquinas só lê."""
    db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, "0")
    assert main.regeneracao_permitida() is False


def test_ligar_e_desligar():
    db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, "1")
    assert main.regeneracao_permitida() is True
    db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, "0")
    assert main.regeneracao_permitida() is False


def test_recusa_com_conflito_e_explica_onde_regenerar():
    """409 e não 403: não é falta de permissão, é conflito de responsabilidade —
    e a mensagem precisa dizer onde a regeneração acontece."""
    db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, "0")
    with pytest.raises(HTTPException) as excecao:
        main._exigir_regeneracao_permitida()
    assert excecao.value.status_code == 409
    assert "lote noturno" in excecao.value.detail
    assert "Configurações" in excecao.value.detail


def test_permite_quando_ligado():
    db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, "1")
    main._exigir_regeneracao_permitida()  # não levanta


def test_valor_invalido_conta_como_desligado():
    """Só "1" liga. Qualquer outra coisa no banco (edição manual, migração) tem de
    cair no lado seguro."""
    for valor in ("", "0", "sim", "true", "2"):
        db.definir_config_app(main.CHAVE_REGENERACAO_PERMITIDA, valor)
        assert main.regeneracao_permitida() is False, valor
