"""Log em arquivo e sobrevivência a `sys.stdout is None` (modo sem console)."""

import logging
import sys

import pytest

import registro


@pytest.fixture
def logs_em_tmp(tmp_path, monkeypatch):
    """Aponta pasta_logs para tmp_path e devolve a raiz do logging limpa."""
    monkeypatch.setattr(registro, "pasta_logs", lambda: str(tmp_path))
    raiz = logging.getLogger()
    handlers_originais = list(raiz.handlers)
    nivel_original = raiz.level
    raiz.handlers = []
    yield tmp_path
    for h in raiz.handlers:
        h.close()
    raiz.handlers = handlers_originais
    raiz.setLevel(nivel_original)


def test_grava_no_arquivo(logs_em_tmp):
    caminho = registro.configurar()
    logging.getLogger("teste").info("linha de teste")
    logging.getLogger().handlers[0].flush()
    assert "linha de teste" in open(caminho, encoding="utf-8").read()


def test_configurar_duas_vezes_nao_duplica(logs_em_tmp):
    registro.configurar()
    antes = len(logging.getLogger().handlers)
    registro.configurar()
    assert len(logging.getLogger().handlers) == antes


def test_stdout_ausente_e_substituido(logs_em_tmp, monkeypatch):
    """O caso que motiva o módulo: empacotado sem console, sys.stdout é None e
    qualquer print levantaria AttributeError, derrubando o app no boot."""
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    caminho = registro.configurar()

    print("mensagem que iria para o vazio")  # noqa: T201 - é o objeto do teste
    sys.stdout.flush()

    assert sys.stdout is not None
    assert "mensagem que iria para o vazio" in open(caminho, encoding="utf-8").read()


def test_print_sem_console_nao_levanta(logs_em_tmp, monkeypatch):
    monkeypatch.setattr(sys, "stdout", None)
    registro.configurar()
    print("uma", "duas", "tres")  # noqa: T201
    print()  # noqa: T201 - linha vazia não deve virar registro


def test_saida_agrupa_por_linha(logs_em_tmp):
    """`print` chama write duas vezes (texto e "\\n"); sem agrupar, cada fragmento
    viraria uma linha de log separada."""
    registrador = logging.getLogger("saida-teste")
    registros = []
    monkey = logging.Handler()
    monkey.emit = lambda r: registros.append(r.getMessage())
    registrador.addHandler(monkey)
    registrador.setLevel(logging.INFO)

    saida = registro._SaidaParaLog(registrador, logging.INFO)
    saida.write("primeira")
    saida.write("\n")
    saida.write("segunda\nterceira\n")

    assert registros == ["primeira", "segunda", "terceira"]


def test_saida_ignora_linhas_vazias(logs_em_tmp):
    registrador = logging.getLogger("saida-vazia")
    registros = []
    h = logging.Handler()
    h.emit = lambda r: registros.append(r.getMessage())
    registrador.addHandler(h)
    registrador.setLevel(logging.INFO)

    saida = registro._SaidaParaLog(registrador, logging.INFO)
    saida.write("\n\n   \n")
    assert registros == []


def test_fileno_levanta_como_stream_sem_descritor(logs_em_tmp):
    """Bibliotecas checam fileno(); devolver um número falso faria alguém tentar
    escrever num descritor que não é nosso."""
    saida = registro._SaidaParaLog(logging.getLogger("x"), logging.INFO)
    with pytest.raises(OSError):
        saida.fileno()
    assert saida.isatty() is False


def test_config_uvicorn_e_none(logs_em_tmp):
    """None faz o uvicorn herdar a raiz em vez de instalar handlers de stream —
    é o que mantém o access log dentro do arquivo."""
    assert registro.config_uvicorn() is None
