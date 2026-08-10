"""Tokens de sessão persistidos no SQLite para sobreviver a --reload do uvicorn."""

from fastapi import Header, HTTPException

import db


def criar_token(usuario: str) -> str:
    return db.criar_sessao(usuario)


def usuario_do_token(token: str) -> str | None:
    return db.usuario_da_sessao(token)


#: Login desativado: o Analisador é aberto, como o Dashboard. As rotas mantêm a
#: dependência `exigir_login` (e portanto o nome do usuário nos logs quando há
#: token), mas ninguém é barrado. Para voltar a exigir login, basta trocar este
#: flag para False — nenhuma rota precisa mudar.
LOGIN_DESATIVADO = True

#: Usuário atribuído às requisições sem token quando o login está desativado.
USUARIO_ANONIMO = "anonimo"


def exigir_login(authorization: str = Header(default="")) -> str:
    token = authorization.removeprefix("Bearer ").strip()
    usuario = usuario_do_token(token) if token else None
    if usuario is None:
        if LOGIN_DESATIVADO:
            return USUARIO_ANONIMO
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return usuario
