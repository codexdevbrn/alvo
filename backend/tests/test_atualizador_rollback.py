"""Regressões do religamento seguro após falha de atualização."""

import importlib.util
from pathlib import Path


CAMINHO_ATUALIZADOR = Path(__file__).resolve().parents[2] / "atualizador" / "atualizador.py"
SPEC = importlib.util.spec_from_file_location("atualizador_testado", CAMINHO_ATUALIZADOR)
assert SPEC and SPEC.loader
atualizador = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(atualizador)


def test_rollback_exige_versao_anterior_exata(monkeypatch):
    chamadas = []
    monkeypatch.setattr(
        atualizador,
        "religar",
        lambda destino, log, versao_esperada="": chamadas.append(
            (destino, versao_esperada)
        ) or True,
    )

    assert atualizador.religar_versao_anterior("C:/Prisma", lambda _m: None, "1.0.16") is True
    assert chamadas == [("C:/Prisma", "1.0.16")]


def test_rollback_falha_fechado_sem_versao_anterior(monkeypatch):
    mensagens = []
    monkeypatch.setattr(
        atualizador,
        "religar",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("não deve religar")),
    )

    assert atualizador.religar_versao_anterior("C:/Prisma", mensagens.append, "") is False
    assert "não pode ser confirmado" in mensagens[0]
