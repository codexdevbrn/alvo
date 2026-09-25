"""Religado pelo atualizador, o app não abre aba nova: a aberta se recarrega sozinha."""

from __future__ import annotations

import os
import sys
import time

import servidor


def test_argumento_do_atualizador_segura_o_navegador(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["Prisma.exe", servidor.ARG_APOS_ATUALIZAR])
    assert servidor._religado_pelo_atualizador() is True


def test_abertura_normal_abre_o_navegador(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["Prisma.exe"])
    assert servidor._religado_pelo_atualizador() is False


def test_atualizador_antigo_sem_argumento_e_reconhecido_pelo_log_recente(monkeypatch, tmp_path):
    instalacao = tmp_path / "Prisma"
    instalacao.mkdir()
    log = tmp_path / "Prisma-atualizacao.log"
    log.write_text("Religando...", encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["Prisma.exe"])
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(instalacao / "Prisma.exe"))
    assert servidor._religado_pelo_atualizador() is True
    # Log de uma atualização antiga não segura a abertura de hoje.
    antigo = time.time() - servidor.SEGUNDOS_LOG_ATUALIZACAO_RECENTE - 60
    os.utime(log, (antigo, antigo))
    assert servidor._religado_pelo_atualizador() is False
