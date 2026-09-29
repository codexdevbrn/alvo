"""Servidor MCP (stdio) com as ferramentas do Prisma para o chat do Assistente.

O ``claude -p`` do chat sobe este processo e fala com ele por JSON-RPC, uma
mensagem por linha (``initialize``, ``tools/list``, ``tools/call``). Ele não
calcula nada: repassa cada chamada a ``POST /api/ia/ferramentas/executar`` do
Prisma que está atendendo a conversa — os dados já estão na RAM de lá, e o
número sai igual ao da tela.

Escrito à mão, sem a biblioteca ``mcp``: o protocolo usado é pequeno, e uma
dependência a menos é uma a menos no executável. Só a biblioteca padrão e o
catálogo de ``ferramentas_ia`` (que não importa nada pesado no topo), para
subir em milissegundos a cada pergunta.

Ambiente, preenchido pelo backend na hora da pergunta:
- ``PRISMA_API``: base da API local (``http://127.0.0.1:8003``);
- ``PRISMA_SESSAO``: token da conversa, que fixa a empresa no backend.

Tudo que não é protocolo vai para o stderr: o stdout é o canal do JSON-RPC.
"""

from __future__ import annotations

import json
import os
import sys
from urllib import error as urllib_error
from urllib import request as urllib_request

import ferramentas_ia

VERSAO_PROTOCOLO = "2025-06-18"
TIMEOUT_CHAMADA_SEGUNDOS = 90


def _log(texto: str) -> None:
    print(f"[mcp-prisma] {texto}", file=sys.stderr, flush=True)


def _chamar_prisma(nome: str, argumentos: dict) -> tuple[str, bool]:
    api = os.environ.get("PRISMA_API", "").rstrip("/")
    sessao = os.environ.get("PRISMA_SESSAO", "")
    if not api or not sessao:
        return "Servidor de ferramentas sem configuração do Prisma.", True
    corpo = json.dumps({"nome": nome, "argumentos": argumentos}, ensure_ascii=False).encode("utf-8")
    pedido = urllib_request.Request(
        f"{api}/api/ia/ferramentas/executar",
        data=corpo,
        method="POST",
        headers={"Content-Type": "application/json", "X-Prisma-Sessao": sessao},
    )
    try:
        with urllib_request.urlopen(pedido, timeout=TIMEOUT_CHAMADA_SEGUNDOS) as resposta:
            dados = json.loads(resposta.read().decode("utf-8"))
    except urllib_error.HTTPError as exc:
        return f"O Prisma recusou a chamada (HTTP {exc.code}).", True
    except (urllib_error.URLError, TimeoutError, OSError, ValueError) as exc:
        return f"O Prisma não respondeu à ferramenta ({type(exc).__name__}).", True
    return str(dados.get("texto") or ""), bool(dados.get("erro"))


def responder(mensagem: dict) -> dict | None:
    """Resposta JSON-RPC para ``mensagem``; ``None`` para notificação."""
    metodo = mensagem.get("method")
    identificador = mensagem.get("id")
    if identificador is None:
        return None  # notificação (ex.: notifications/initialized)

    def ok(resultado: dict) -> dict:
        return {"jsonrpc": "2.0", "id": identificador, "result": resultado}

    if metodo == "initialize":
        pedida = (mensagem.get("params") or {}).get("protocolVersion") or VERSAO_PROTOCOLO
        return ok({
            "protocolVersion": pedida,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "prisma", "version": "1.0"},
        })
    if metodo == "ping":
        return ok({})
    if metodo == "tools/list":
        return ok({"tools": ferramentas_ia.catalogo()})
    if metodo == "tools/call":
        params = mensagem.get("params") or {}
        texto, erro = _chamar_prisma(str(params.get("name") or ""), params.get("arguments") or {})
        return ok({"content": [{"type": "text", "text": texto}], "isError": erro})
    return {"jsonrpc": "2.0", "id": identificador, "error": {"code": -32601, "message": f"Método desconhecido: {metodo}"}}


def main() -> None:
    entrada = sys.stdin.buffer
    saida = sys.stdout.buffer
    for linha in entrada:
        if not linha.strip():
            continue
        try:
            mensagem = json.loads(linha.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            _log("mensagem ilegível ignorada")
            continue
        resposta = responder(mensagem)
        if resposta is not None:
            saida.write(json.dumps(resposta, ensure_ascii=False).encode("utf-8") + b"\n")
            saida.flush()


if __name__ == "__main__":
    main()
