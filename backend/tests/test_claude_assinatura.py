"""Claude pela assinatura (``claude -p``) e a reserva no Ollama Cloud."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

import claude_assinatura
from claude_assinatura import ErroClaude, chamar_claude, montar_prompt
from dossie_ia import MODELO_OLLAMA, EnvioIA, ErroProvedorIA


def _processo(dados: dict | None = None, *, stdout: bytes | None = None, stderr: bytes = b"", codigo: int = 0):
    corpo = stdout if stdout is not None else json.dumps(dados).encode("utf-8")
    return SimpleNamespace(stdout=corpo, stderr=stderr, returncode=codigo)


@pytest.fixture
def cli(monkeypatch):
    """Substitui o subprocess e guarda o que a chamada teria executado."""
    chamadas: list[dict] = []
    respostas: list = []

    def rodar(comando, **kwargs):
        sistema = None
        if "--system-prompt-file" in comando:
            with open(comando[comando.index("--system-prompt-file") + 1], encoding="utf-8") as arquivo:
                sistema = arquivo.read()
        chamadas.append({"comando": comando, "sistema": sistema, **kwargs})
        resposta = respostas.pop(0)
        if isinstance(resposta, BaseException):
            raise resposta
        return resposta

    monkeypatch.setattr(claude_assinatura, "localizar_claude", lambda: "claude")
    monkeypatch.setattr(claude_assinatura.subprocess, "run", rodar)
    return SimpleNamespace(chamadas=chamadas, respostas=respostas)


def test_mensagem_unica_vai_crua_e_sistema_separado():
    sistema, prompt = montar_prompt([
        {"role": "system", "content": "Regras"},
        {"role": "user", "content": "Pergunta"},
    ])
    assert sistema == "Regras"
    assert prompt == "Pergunta"


def test_conversa_vira_transcricao_com_ultimo_turno_do_usuario():
    _sistema, prompt = montar_prompt([
        {"role": "system", "content": "Regras"},
        {"role": "user", "content": "Contexto"},
        {"role": "assistant", "content": "Recebido"},
        {"role": "user", "content": "E agora?"},
    ])
    assert prompt.index("### Usuário\nContexto") < prompt.index("### Assistente\nRecebido")
    assert prompt.rstrip().endswith("### Usuário\nE agora?")


def test_chamada_isola_o_processo_e_tira_credencial_de_api(cli, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-nao-pode-passar")
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", "C:/perfil")
    cli.respostas.append(_processo({"is_error": False, "result": " Texto \n", "stop_reason": "end_turn"}))

    resposta = chamar_claude([
        {"role": "system", "content": "Regras longas"},
        {"role": "user", "content": "Pergunta"},
    ], modelo="claude-opus-5-5", timeout=30)

    assert resposta == "Texto"
    chamada = cli.chamadas[0]
    comando = chamada["comando"]
    assert comando[comando.index("--tools") + 1] == ""
    assert comando[comando.index("--model") + 1] == "claude-opus-5-5"
    assert "--no-session-persistence" in comando and "--strict-mcp-config" in comando
    assert chamada["sistema"] == "Regras longas"
    assert chamada["input"] == "Pergunta".encode("utf-8")
    assert chamada["stdout"] == subprocess.PIPE and chamada["stderr"] == subprocess.PIPE
    assert chamada["timeout"] == 30
    ambiente = chamada["env"]
    assert "ANTHROPIC_API_KEY" not in ambiente
    assert "CLAUDECODE" not in ambiente and "CLAUDE_CODE_ENTRYPOINT" not in ambiente
    assert ambiente["CLAUDE_CONFIG_DIR"] == "C:/perfil"


@pytest.mark.parametrize(("texto", "codigo"), [
    ("Not logged in · Please run /login", "claude_login"),
    ("Claude AI usage limit reached", "claude_limite"),
    ("There's an issue with the selected model", "claude_erro"),
])
def test_erro_com_saida_zero_vira_erro_classificado(cli, texto, codigo):
    cli.respostas.append(_processo({"is_error": True, "result": texto}))
    with pytest.raises(ErroClaude) as erro:
        chamar_claude([{"role": "user", "content": "oi"}])
    assert erro.value.codigo == codigo


def test_recusa_resposta_vazia_e_saida_invalida(cli):
    cli.respostas.extend([
        _processo({"is_error": False, "result": "x", "stop_reason": "refusal"}),
        _processo({"is_error": False, "result": "  "}),
        _processo(stdout=b"", stderr=b"boom", codigo=1),
    ])
    codigos = []
    for _ in range(3):
        with pytest.raises(ErroClaude) as erro:
            chamar_claude([{"role": "user", "content": "oi"}])
        codigos.append(erro.value.codigo)
    assert codigos == ["claude_recusa", "claude_vazio", "claude_erro"]


def test_timeout_e_ausencia(cli, monkeypatch):
    cli.respostas.append(subprocess.TimeoutExpired("claude", 5))
    with pytest.raises(ErroClaude) as erro:
        chamar_claude([{"role": "user", "content": "oi"}], timeout=5)
    assert erro.value.codigo == "claude_timeout"

    monkeypatch.setattr(claude_assinatura, "localizar_claude", lambda: None)
    with pytest.raises(ErroClaude) as erro:
        chamar_claude([{"role": "user", "content": "oi"}])
    assert erro.value.codigo == "claude_ausente"


def _falhar_claude(*_args, **_kwargs):
    raise ErroClaude("claude_limite", "limite")


def test_envio_usa_claude_e_registra_modelo():
    envio = EnvioIA(
        chamar_claude=lambda _m, **kw: f"ok {kw['modelo']}",
        chamar_reserva=lambda *_a, **_k: pytest.fail("reserva não deveria rodar"),
    )
    assert envio([], "chave", modelo="claude-opus-5-5") == "ok claude-opus-5-5"
    assert envio.ultimo_modelo == "claude-opus-5-5"


def test_envio_cai_na_reserva_com_chave():
    recebidos = []

    def reserva(mensagens, api_key, *, modelo):
        recebidos.append((api_key, modelo))
        return "do ollama"

    envio = EnvioIA(chamar_claude=_falhar_claude, chamar_reserva=reserva)
    assert envio([{"role": "user", "content": "oi"}], "chave-ollama") == "do ollama"
    assert recebidos == [("chave-ollama", MODELO_OLLAMA)]
    assert envio.ultimo_modelo == MODELO_OLLAMA


def test_envio_sem_chave_propaga_erro_do_claude():
    envio = EnvioIA(chamar_claude=_falhar_claude, chamar_reserva=lambda *_a, **_k: "nunca")
    with pytest.raises(ErroProvedorIA) as erro:
        envio([], None)
    assert erro.value.codigo == "claude_limite"


def test_crm_definitivo_tem_precedencia_sobre_a_reserva(tmp_path):
    from dossie_ia import localizar_crm

    client_id = "0173897f-5c7a-4767-9c35-3fc729ab1d2b"
    dossie, reserva = tmp_path / "dossie", tmp_path / "reserva"
    dossie.mkdir()
    reserva.mkdir()
    (reserva / f"{client_id}--peca-com.md").write_text("reserva", encoding="utf-8")

    assert localizar_crm(dossie, client_id, reserva) == reserva / f"{client_id}--peca-com.md"
    assert localizar_crm(dossie, client_id, None) is None

    (dossie / f"{client_id}-crm.md").write_text("definitivo", encoding="utf-8")
    assert localizar_crm(dossie, client_id, reserva) == dossie / f"{client_id}-crm.md"


def test_crm_ambiguo_na_reserva_conta_como_ausente(tmp_path):
    from dossie_ia import localizar_crm

    client_id = "0173897f-5c7a-4767-9c35-3fc729ab1d2b"
    (tmp_path / f"{client_id}--a.md").write_text("a", encoding="utf-8")
    (tmp_path / f"{client_id}--b.md").write_text("b", encoding="utf-8")
    assert localizar_crm(tmp_path / "vazio", client_id, tmp_path) is None
