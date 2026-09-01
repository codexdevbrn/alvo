"""A IA segue o mesmo modo aberto configurado para o restante do Prisma."""

import auth


def test_login_aberto_aceita_anonimo(monkeypatch):
    monkeypatch.setattr(auth, "usuario_do_token", lambda _token: None)

    assert auth.exigir_login("") == auth.USUARIO_ANONIMO


def test_login_aberto_preserva_sessao_valida(monkeypatch):
    monkeypatch.setattr(auth, "usuario_do_token", lambda token: "admin" if token == "valido" else None)

    assert auth.exigir_login("Bearer valido") == "admin"
