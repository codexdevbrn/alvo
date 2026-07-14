"""Tokens de sessão persistidos no SQLite para sobreviver a --reload do uvicorn."""

from fastapi import Header, HTTPException

import db


def criar_token(usuario: str) -> str:
    return db.criar_sessao(usuario)


def usuario_do_token(token: str) -> str | None:
    return db.usuario_da_sessao(token)


def exigir_login(authorization: str = Header(default="")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    usuario = usuario_do_token(token) if token else None
    if usuario is None:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return usuario
