"""Leitura do canal de atualização, incluindo os estados quebrados que o
OneDrive produz na prática (placeholder não baixado, sync pela metade)."""

import json

import pytest

import atualizacoes
from atualizacoes import consultar_canal
from versao import VERSAO


def _publicar(canal, versao_publicada, conteudo=b"pacote-fake", **sobrescreve):
    """Escreve um par version.json + zip coerente na pasta do canal."""
    nome = f"Prisma-{versao_publicada}.zip"
    pacote = canal / nome
    pacote.write_bytes(conteudo)
    manifesto = {
        "versao": versao_publicada,
        "arquivo": nome,
        "sha256": atualizacoes.sha256_do_arquivo(str(pacote)),
        "tamanho": len(conteudo),
        "data": "2026-08-12",
        "notas": "Notas da release.",
    }
    manifesto.update(sobrescreve)
    (canal / "version.json").write_text(json.dumps(manifesto), encoding="utf-8")
    return pacote


def _versao_maior():
    """Uma versão acima da atual, sem fixar número no teste — assim o bump de
    VERSAO não quebra os testes."""
    maior, menor, correcao = (int(p) for p in VERSAO.split("."))
    return f"{maior}.{menor}.{correcao + 1}"


def test_canal_nao_configurado_nao_e_erro(tmp_path):
    status = consultar_canal(None)
    assert not status.atualizavel
    assert "não configurado" in status.motivo


def test_canal_inacessivel(tmp_path):
    status = consultar_canal(str(tmp_path / "pasta-que-nao-existe"))
    assert not status.atualizavel
    assert "não está acessível" in status.motivo


def test_canal_sem_manifesto(tmp_path):
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "version.json" in status.motivo


def test_manifesto_corrompido(tmp_path):
    (tmp_path / "version.json").write_text("{isso não é json", encoding="utf-8")
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "corrompido" in status.motivo


def test_manifesto_sem_campo_obrigatorio(tmp_path):
    (tmp_path / "version.json").write_text(json.dumps({"versao": "9.9.9"}), encoding="utf-8")
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "'arquivo'" in status.motivo


def test_release_mais_nova_e_oferecida(tmp_path):
    nova = _versao_maior()
    _publicar(tmp_path, nova)
    status = consultar_canal(str(tmp_path))
    assert status.atualizavel
    assert status.versao_disponivel == nova
    assert status.versao_atual == VERSAO
    assert status.notas == "Notas da release."
    assert status.caminho_pacote is not None


def test_mesma_versao_nao_e_oferecida(tmp_path):
    _publicar(tmp_path, VERSAO)
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "versão mais recente" in status.motivo


def test_versao_anterior_nao_e_oferecida(tmp_path):
    _publicar(tmp_path, "0.0.1")
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel


def test_pacote_ausente(tmp_path):
    nova = _versao_maior()
    _publicar(tmp_path, nova)
    (tmp_path / f"Prisma-{nova}.zip").unlink()
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "não está lá" in status.motivo


def test_placeholder_do_onedrive_nao_e_oferecido(tmp_path):
    """Files On-Demand deixa o arquivo com 0 byte até alguém abrir. Aplicar isso
    instalaria um zip vazio por cima da instalação boa."""
    nova = _versao_maior()
    pacote = _publicar(tmp_path, nova)
    pacote.write_bytes(b"")
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "sincronizar" in status.motivo
    assert status.detalhes["tamanho_real"] == 0


def test_pacote_parcialmente_sincronizado_nao_e_oferecido(tmp_path):
    nova = _versao_maior()
    pacote = _publicar(tmp_path, nova, conteudo=b"conteudo-completo-do-pacote")
    pacote.write_bytes(b"conteudo-inc")
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert "sincronizar" in status.motivo


def test_sha256_do_arquivo_confere(tmp_path):
    arquivo = tmp_path / "x.bin"
    arquivo.write_bytes(b"abc")
    esperado = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
    assert atualizacoes.sha256_do_arquivo(str(arquivo)) == esperado


@pytest.mark.parametrize("campo", ["versao", "arquivo", "sha256", "tamanho"])
def test_todos_os_campos_obrigatorios_sao_checados(tmp_path, campo):
    _publicar(tmp_path, _versao_maior(), **{campo: ""})
    status = consultar_canal(str(tmp_path))
    assert not status.atualizavel
    assert f"'{campo}'" in status.motivo
