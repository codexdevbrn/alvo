"""Integração fina entre rota FastAPI e serviço de chat."""

from fastapi.testclient import TestClient
from starlette.requests import Request

import chat_ia
import main


def _contexto() -> chat_ia.ContextoEmpresa:
    crm = chat_ia.DocumentoContexto("id-crm.md", True, "2026-08-27T10:00:00+00:00", None, "CRM")
    analise = chat_ia.DocumentoContexto(
        "id-analise.md", True, "2026-08-27T11:00:00+00:00", "ok", "ANÁLISE",
    )
    return chat_ia.ContextoEmpresa("client-id", "Empresa", "Empresa", crm, analise)


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/api/ia/chat",
        "headers": [],
        "client": ("127.0.0.1", 50000),
        "server": ("127.0.0.1", 8003),
        "scheme": "http",
        "query_string": b"",
    })


def test_status_da_rota_nao_devolve_markdown(monkeypatch):
    monkeypatch.setattr(main, "_contexto_chat_empresa", lambda _empresa: _contexto())

    resposta = main.obter_contexto_chat_empresa("Empresa", _usuario="admin")

    assert resposta["pronto"] is True
    assert "conteudo" not in resposta["crm"]
    assert "ANÁLISE" not in str(resposta)


def test_status_http_aceita_requisicao_sem_login(monkeypatch):
    """Modo aberto precisa funcionar sem Authorization também pela rota HTTP."""
    monkeypatch.setattr(main, "_contexto_chat_empresa", lambda _empresa: _contexto())

    cliente = TestClient(main.app)
    resposta = cliente.get("/api/ia/contexto", params={"empresa": "Empresa"})

    assert resposta.status_code == 200
    assert resposta.json()["pronto"] is True


def test_rota_chat_nao_devolve_chave_ou_documentos(monkeypatch):
    main._chat_rate.clear()
    monkeypatch.setattr(main, "_contexto_chat_empresa", lambda _empresa: _contexto())
    monkeypatch.setattr(chat_ia, "carregar_api_key_ollama", lambda: "chave-super-secreta")

    def responder(_contexto, _mensagens, chave):
        assert chave == "chave-super-secreta"
        return "Resposta comprovada [CRM]."

    monkeypatch.setattr(chat_ia, "responder_chat", responder)
    corpo = main.ChatEmpresaBody(
        empresa="Empresa",
        mensagens=[main.ChatMensagemBody(role="user", content="Qual risco?")],
    )

    resposta = main.conversar_com_empresa(
        corpo, _request(), usuario="admin",
    )

    assert resposta["resposta"] == "Resposta comprovada [CRM]."
    assert "chave-super-secreta" not in str(resposta)
    assert "ANÁLISE" not in str(resposta)


def test_chat_http_aceita_requisicao_sem_login(monkeypatch):
    """Chat aberto mantém chave e documentos restritos ao backend."""
    main._chat_rate.clear()
    monkeypatch.setattr(main, "_contexto_chat_empresa", lambda _empresa: _contexto())
    monkeypatch.setattr(chat_ia, "carregar_api_key_ollama", lambda: "chave-super-secreta")
    monkeypatch.setattr(
        chat_ia,
        "responder_chat",
        lambda _contexto, _mensagens, _chave: "Resposta comprovada [CRM].",
    )

    cliente = TestClient(main.app)
    resposta = cliente.post(
        "/api/ia/chat",
        json={
            "empresa": "Empresa",
            "mensagens": [{"role": "user", "content": "Qual risco?"}],
        },
    )

    assert resposta.status_code == 200
    assert resposta.json()["resposta"] == "Resposta comprovada [CRM]."
    assert "chave-super-secreta" not in resposta.text
    assert "ANÁLISE" not in resposta.text
