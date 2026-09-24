"""Chave do cache das telas: tags entram pelo conteúdo, não pelo mtime.

O `Bancos/tags.json` era regravado igual a cada salvamento de tags, e cada
regravação trocava a chave do painel de Clientes — o que o lote da manhã
preparava nunca era reencontrado.
"""

import os
import time

import main


def test_regravar_igual_nao_muda_a_assinatura(tmp_path):
    arquivo = tmp_path / "tags.json"
    arquivo.write_text('[{"id": "balcao"}]', encoding="utf-8")
    antes = main._assinatura_conteudo_opcional(arquivo)
    os.utime(arquivo, (time.time() + 60, time.time() + 60))
    arquivo.write_text('[{"id": "balcao"}]', encoding="utf-8")
    assert main._assinatura_conteudo_opcional(arquivo) == antes


def test_mudar_conteudo_muda_a_assinatura(tmp_path):
    arquivo = tmp_path / "tags.json"
    arquivo.write_text('[{"id": "balcao"}]', encoding="utf-8")
    antes = main._assinatura_conteudo_opcional(arquivo)
    arquivo.write_text('[{"id": "interno"}]', encoding="utf-8")
    assert main._assinatura_conteudo_opcional(arquivo) != antes


def test_arquivo_ausente(tmp_path):
    assert main._assinatura_conteudo_opcional(tmp_path / "nao_existe.json") == (0, "")


def test_catalogo_igual_nao_e_regravado(tmp_path, monkeypatch):
    arquivo = tmp_path / "tags.json"
    monkeypatch.setattr(main, "CAMINHO_BANCO_CENTRALIZADO_TAGS", str(arquivo))
    main._gravar_catalogo_centralizado([{"id": "balcao"}])
    os.utime(arquivo, (1_000_000, 1_000_000))
    main._gravar_catalogo_centralizado([{"id": "balcao"}])
    assert os.stat(arquivo).st_mtime == 1_000_000
    main._gravar_catalogo_centralizado([{"id": "interno"}])
    assert os.stat(arquivo).st_mtime != 1_000_000
