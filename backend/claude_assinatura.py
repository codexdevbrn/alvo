"""Chamada ao Claude pela assinatura, via Claude Code logado nesta máquina.

A assinatura (Pro/Max/Team) não dá API key: o acesso programático é o próprio
Claude Code em modo não interativo (``claude -p``). Cada chamada é um processo
isolado, sem ferramentas, sem MCP, sem settings nem CLAUDE.md, e sem sessão
gravada, para que o modelo veja só o prompt do Prisma.

Três coisas que o teste manual ensinou:

- **Erro volta com saída 0.** Modelo inválido, login expirado e limite de uso
  chegam como ``is_error: true`` no JSON, não como código de saída.
- **API key no ambiente desvia da assinatura.** ``ANTHROPIC_API_KEY`` tem
  precedência sobre o login do claude.ai, então ela sai do ambiente do filho.
- **O prompt de sistema vai por arquivo.** A linha de comando do Windows tem
  teto de 32 mil caracteres; o dossiê passa disso.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Callable

MODELO_CLAUDE = "claude-sonnet-5-5"
TIMEOUT_CLAUDE_SEGUNDOS = 300

# Marcadores de sessão do Claude Code pai (quando o Prisma roda de dentro de
# uma) e credenciais de API, que tirariam a chamada da assinatura.
_PREFIXOS_REMOVIDOS = ("CLAUDE_CODE_",)
_VARIAVEIS_REMOVIDAS = ("CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")

_ROTULOS = {"user": "Usuário", "assistant": "Assistente"}

SERVIDOR_MCP = "prisma"


class ErroClaude(RuntimeError):
    """Falha ao obter resposta do Claude, com código estável para log e HTTP."""

    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo


def localizar_claude() -> str | None:
    """Executável do Claude Code: PATH primeiro, instalação padrão como reserva.

    A reserva existe porque o agendador e o .exe nem sempre herdam o PATH do
    usuário com ``~/.local/bin``.
    """
    achado = shutil.which("claude")
    if achado:
        return achado
    nome = "claude.exe" if os.name == "nt" else "claude"
    reserva = Path.home() / ".local" / "bin" / nome
    return str(reserva) if reserva.is_file() else None


def _ambiente_filho() -> dict[str, str]:
    return {
        nome: valor
        for nome, valor in os.environ.items()
        if nome not in _VARIAVEIS_REMOVIDAS and not nome.startswith(_PREFIXOS_REMOVIDOS)
    }


def montar_prompt(mensagens: list[dict]) -> tuple[str, str]:
    """Separa (sistema, prompt). Conversa com mais de uma mensagem vira transcrição.

    O ``claude -p`` recebe um prompt só; a correção de formato e o chat mandam
    histórico, que vai transcrito com a instrução de responder ao último turno.
    """
    sistema = "\n\n".join(
        str(m.get("content") or "") for m in mensagens if m.get("role") == "system"
    ).strip()
    conversa = [m for m in mensagens if m.get("role") in _ROTULOS]
    if not conversa:
        raise ErroClaude("claude_entrada", "Nenhuma mensagem para enviar ao Claude.")
    if len(conversa) == 1:
        return sistema, str(conversa[0].get("content") or "")
    blocos = [f"### {_ROTULOS[m['role']]}\n{m.get('content') or ''}" for m in conversa]
    prompt = (
        "Conversa até aqui. Responda somente à última mensagem de Usuário, "
        "sem repetir os rótulos.\n\n" + "\n\n".join(blocos)
    )
    return sistema, prompt


def _classificar_erro(texto: str) -> str:
    minusculo = texto.lower()
    if "log in" in minusculo or "login" in minusculo or "/login" in minusculo:
        return "claude_login"
    if "limit" in minusculo:
        return "claude_limite"
    return "claude_erro"


def _comando(
    executavel: str, pasta: str, sistema: str, modelo: str, formato: str, mcp: dict | None = None,
    esforco: str | None = None,
) -> list[str]:
    comando = [
        executavel, "-p",
        "--output-format", formato,
        "--model", modelo,
        "--tools", "",
        "--strict-mcp-config",
        "--setting-sources", "",
        "--no-session-persistence",
    ]
    if esforco:
        comando += ["--effort", esforco]
    if formato == "stream-json":
        comando += ["--verbose", "--include-partial-messages"]
    if sistema:
        arquivo_sistema = Path(pasta) / "sistema.md"
        arquivo_sistema.write_text(sistema, encoding="utf-8")
        comando += ["--system-prompt-file", str(arquivo_sistema)]
    if mcp:
        # Só o servidor do Prisma (--strict-mcp-config já ignora os do usuário) e
        # só as ferramentas dele liberadas; as nativas seguem desligadas (--tools "").
        arquivo_mcp = Path(pasta) / "mcp.json"
        arquivo_mcp.write_text(json.dumps({"mcpServers": {SERVIDOR_MCP: mcp}}), encoding="utf-8")
        comando += ["--mcp-config", str(arquivo_mcp), "--allowedTools", f"mcp__{SERVIDOR_MCP}"]
    return comando


def _erro_sem_resultado(codigo_saida: int | None, detalhe: str) -> ErroClaude:
    return ErroClaude(
        _classificar_erro(detalhe) if detalhe else "claude_resposta",
        f"Claude Code saiu com código {codigo_saida} sem resposta válida. {detalhe}".strip(),
    )


def _texto_do_resultado(dados: dict) -> str:
    """Resposta final do evento ``result``; erro com saída 0 vira ErroClaude."""
    resultado = dados.get("result")
    if dados.get("is_error"):
        texto = str(resultado or dados.get("terminal_reason") or "erro sem detalhe")[:200]
        raise ErroClaude(_classificar_erro(texto), f"Claude recusou a chamada: {texto}")
    if dados.get("stop_reason") == "refusal":
        raise ErroClaude("claude_recusa", "Claude declinou responder a este conteúdo.")
    if not isinstance(resultado, str) or not resultado.strip():
        raise ErroClaude("claude_vazio", "Claude retornou conteúdo vazio.")
    return resultado.strip()


def chamar_claude(
    mensagens: list[dict],
    *,
    modelo: str = MODELO_CLAUDE,
    timeout: int = TIMEOUT_CLAUDE_SEGUNDOS,
    ao_receber: Callable[[str], None] | None = None,
    ao_evento: Callable[[dict], None] | None = None,
    mcp: dict | None = None,
    esforco: str | None = None,
) -> str:
    """Envia a conversa ao Claude Code e devolve o texto da resposta.

    ``esforco`` (low…max) é o ``--effort`` do CLI; ``None`` usa o padrão do modelo.

    Com ``ao_receber``, cada pedaço do texto é entregue assim que chega (o chat
    mostra a resposta sendo escrita); o retorno continua sendo o texto inteiro.
    ``mcp`` (``{"command", "args", "env"}``) dá ao modelo as ferramentas do
    Prisma, e ``ao_evento`` avisa cada chamada: ``{"tipo": "ferramenta", "id",
    "nome", "argumentos"}`` ao pedir e ``{"tipo": "ferramenta_fim", "id",
    "erro"}`` ao receber o resultado.
    """
    executavel = localizar_claude()
    if not executavel:
        raise ErroClaude("claude_ausente", "Claude Code não está instalado nesta máquina.")
    sistema, prompt = montar_prompt(mensagens)
    if ao_receber is not None or ao_evento is not None or mcp:
        return _transmitir(
            executavel, sistema, prompt, modelo, timeout,
            ao_receber or (lambda _texto: None), ao_evento or (lambda _evento: None), mcp, esforco,
        )

    with tempfile.TemporaryDirectory(prefix="prisma-claude-") as pasta:
        comando = _comando(executavel, pasta, sistema, modelo, "json", esforco=esforco)
        try:
            # Três descritores explícitos: depois do FreeConsole do .exe os
            # handles herdados são inválidos (ver servidor._fechar_console).
            # cwd na pasta temporária: nenhum CLAUDE.md de projeto é achado.
            processo = subprocess.run(
                comando,
                input=prompt.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=pasta,
                env=_ambiente_filho(),
                timeout=timeout,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired as exc:
            raise ErroClaude("claude_timeout", f"Claude não respondeu em {timeout} s.") from exc
        except OSError as exc:
            raise ErroClaude("claude_ausente", "Claude Code não pôde ser executado.") from exc

    try:
        dados = json.loads(processo.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        detalhe = processo.stderr.decode("utf-8", "replace").strip()[:200]
        raise _erro_sem_resultado(processo.returncode, detalhe) from exc
    return _texto_do_resultado(dados)


def _transmitir(
    executavel: str,
    sistema: str,
    prompt: str,
    modelo: str,
    timeout: int,
    ao_receber: Callable[[str], None],
    ao_evento: Callable[[dict], None],
    mcp: dict | None,
    esforco: str | None = None,
) -> str:
    """``stream-json``: repassa cada ``text_delta`` e fecha com o evento ``result``.

    Com ferramentas, o pedido de chamada vem na mensagem ``assistant`` (bloco
    ``tool_use``, já com os argumentos inteiros) e o resultado numa mensagem
    ``user`` (bloco ``tool_result``).

    O timeout é de relógio (um Timer mata o processo), porque a leitura linha a
    linha não tem prazo próprio. O stderr é drenado em thread à parte: se ele
    enchesse o buffer do pipe, o processo travaria antes de fechar o stdout.
    """
    with tempfile.TemporaryDirectory(prefix="prisma-claude-") as pasta:
        comando = _comando(executavel, pasta, sistema, modelo, "stream-json", mcp, esforco)
        try:
            processo = subprocess.Popen(
                comando,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=pasta,
                env=_ambiente_filho(),
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as exc:
            raise ErroClaude("claude_ausente", "Claude Code não pôde ser executado.") from exc

        estourou = threading.Event()
        erros: list[bytes] = []

        def matar() -> None:
            estourou.set()
            processo.kill()

        relogio = threading.Timer(timeout, matar)
        dreno = threading.Thread(target=lambda: erros.append(processo.stderr.read()), daemon=True)
        relogio.start()
        dreno.start()
        final: dict | None = None
        try:
            processo.stdin.write(prompt.encode("utf-8"))
            processo.stdin.close()
            for linha in processo.stdout:
                try:
                    evento = json.loads(linha.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                if evento.get("type") == "stream_event":
                    delta = (evento.get("event") or {}).get("delta") or {}
                    if delta.get("type") == "text_delta" and delta.get("text"):
                        ao_receber(delta["text"])
                elif evento.get("type") in ("assistant", "user"):
                    for bloco in (evento.get("message") or {}).get("content") or []:
                        if not isinstance(bloco, dict):
                            continue
                        if bloco.get("type") == "tool_use":
                            ao_evento({"tipo": "ferramenta", "id": bloco.get("id"),
                                       "nome": bloco.get("name"), "argumentos": bloco.get("input") or {}})
                        elif bloco.get("type") == "tool_result":
                            ao_evento({"tipo": "ferramenta_fim", "id": bloco.get("tool_use_id"),
                                       "erro": bool(bloco.get("is_error"))})
                elif evento.get("type") == "result":
                    final = evento
            processo.wait()
            dreno.join(timeout=5)
        finally:
            relogio.cancel()
            if processo.poll() is None:
                processo.kill()

    if estourou.is_set():
        raise ErroClaude("claude_timeout", f"Claude não respondeu em {timeout} s.")
    if final is None:
        detalhe = b"".join(erros).decode("utf-8", "replace").strip()[:200]
        raise _erro_sem_resultado(processo.returncode, detalhe)
    return _texto_do_resultado(final)
