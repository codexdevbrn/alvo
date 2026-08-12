"""Leitura do canal de atualização, incluindo os estados quebrados que o
OneDrive produz na prática (placeholder não baixado, sync pela metade)."""

import json
import os

import pytest
from fastapi import HTTPException

import atualizacoes
import main
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


# ---------------------------------------------------------------------------
# preparar_pacote — cópia local + conferência do hash antes de instalar
# ---------------------------------------------------------------------------

def test_prepara_pacote_copiando_e_conferindo(tmp_path):
    canal = tmp_path / "canal"
    temporario = tmp_path / "tmp"
    canal.mkdir()
    temporario.mkdir()
    _publicar(canal, _versao_maior(), conteudo=b"pacote-valido")

    caminho, erro = atualizacoes.preparar_pacote(
        consultar_canal(str(canal)), str(temporario)
    )
    assert not erro
    assert caminho is not None
    # A cópia local é o que será instalado, e precisa estar fora do canal.
    assert os.path.dirname(caminho) == str(temporario)
    assert open(caminho, "rb").read() == b"pacote-valido"


def test_prepara_pacote_recusa_hash_diferente(tmp_path):
    """Cobre o pacote trocado entre a consulta e a cópia — sem isto, um zip
    diferente do publicado seria instalado por cima da versão boa."""
    canal = tmp_path / "canal"
    temporario = tmp_path / "tmp"
    canal.mkdir()
    temporario.mkdir()
    pacote = _publicar(canal, _versao_maior(), conteudo=b"pacote-original")

    status = consultar_canal(str(canal))
    assert status.atualizavel
    # Mesmo tamanho, conteúdo outro: passa pela checagem de tamanho e só o hash pega.
    pacote.write_bytes(b"pacote-trocado!")

    caminho, erro = atualizacoes.preparar_pacote(status, str(temporario))
    assert caminho is None
    assert "sha256" in erro
    assert not list(temporario.iterdir()), "a cópia inválida deve ser removida"


def test_prepara_pacote_sem_atualizacao_disponivel(tmp_path):
    status = consultar_canal(None)
    caminho, erro = atualizacoes.preparar_pacote(status, str(tmp_path))
    assert caminho is None
    assert erro


# ---------------------------------------------------------------------------
# Gate de origem local do POST /api/atualizacoes/aplicar
# ---------------------------------------------------------------------------

class _RequisicaoFalsa:
    """Só o que `_exigir_origem_local` olha: IP do cliente e cabeçalhos."""

    def __init__(self, host, headers=None):
        self.client = type("Cliente", (), {"host": host})() if host else None
        self.headers = headers or {}


def test_aceita_requisicao_de_loopback():
    main._exigir_origem_local(_RequisicaoFalsa("127.0.0.1"))
    main._exigir_origem_local(_RequisicaoFalsa("::1"))


def test_recusa_requisicao_de_outra_maquina():
    with pytest.raises(HTTPException) as excecao:
        main._exigir_origem_local(_RequisicaoFalsa("192.168.1.50"))
    assert excecao.value.status_code == 403


def test_recusa_requisicao_sem_cliente_identificado():
    with pytest.raises(HTTPException) as excecao:
        main._exigir_origem_local(_RequisicaoFalsa(None))
    assert excecao.value.status_code == 403


@pytest.mark.parametrize("cabecalho", main.CABECALHOS_DE_PROXY)
def test_recusa_loopback_repassado_por_proxy(cabecalho):
    """O caso que motiva o gate: o Apache do XAMPP escuta na LAN e faz
    ProxyPass /api para 127.0.0.1, então o IP chega como loopback."""
    with pytest.raises(HTTPException) as excecao:
        main._exigir_origem_local(
            _RequisicaoFalsa("127.0.0.1", {cabecalho: "192.168.1.50"})
        )
    assert excecao.value.status_code == 403
    assert "proxy" in excecao.value.detail
