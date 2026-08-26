"""Regressões do religamento seguro após falha de atualização."""

import importlib.util
from pathlib import Path
import zipfile


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


def test_backup_legado_preso_nao_bloqueia_nova_atualizacao(tmp_path, monkeypatch):
    """Regressão do WinError 183 visto ao atualizar 1.0.25 para 1.1.0."""
    destino = tmp_path / "Prisma"
    destino.mkdir()
    (destino / "Prisma.exe").write_bytes(b"versao-anterior")

    # Sobra real observada: rmtree removeu quase tudo, mas VCRUNTIME140.dll
    # permaneceu dentro do nome fixo usado pelas versões antigas.
    backup_legado = tmp_path / "Prisma_backup"
    dll = backup_legado / "_internal" / "VCRUNTIME140.dll"
    dll.parent.mkdir(parents=True)
    dll.write_bytes(b"preso")

    pacote = tmp_path / "Prisma-1.1.1.zip"
    with zipfile.ZipFile(pacote, "w") as arquivo:
        arquivo.writestr("Prisma.exe", b"versao-nova")

    monkeypatch.setattr(atualizador, "esperar_pid_morrer", lambda *_args: True)
    monkeypatch.setattr(atualizador, "religar", lambda *_args, **_kwargs: True)

    codigo = atualizador.aplicar(
        123, str(pacote), str(destino), "1.1.1", "1.1.0", lambda _m: None,
    )

    assert codigo == 0
    assert (destino / "Prisma.exe").read_bytes() == b"versao-nova"
    assert backup_legado.exists(), "sobra legada não deve ser reutilizada nem tocada"


def test_registro_funciona_sem_stdout(tmp_path, monkeypatch):
    """Executável windowed não possui console nem sys.stdout."""
    caminho = tmp_path / "atualizacao.log"
    monkeypatch.setattr(atualizador.sys, "stdout", None)

    atualizador.Registro(str(caminho))("teste sem CMD")

    assert "teste sem CMD" in caminho.read_text(encoding="utf-8")
