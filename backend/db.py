"""Banco local (SQLite) com os usuários do Analisador (login simples) e as
configurações gerais do app (ex.: pasta onde ficam as configurações salvas
por empresa — ver empresas.py para o JSON por empresa em si)."""

import hashlib
import secrets
import sqlite3

from engine.recursos import caminho_dados_locais

CAMINHO_BANCO = caminho_dados_locais("app.db")


def _hash_senha(senha, salt):
    return hashlib.sha256((salt + senha).encode("utf-8")).hexdigest()


def _conectar():
    conexao = sqlite3.connect(CAMINHO_BANCO)
    conexao.row_factory = sqlite3.Row
    return conexao


def inicializar_banco():
    conexao = _conectar()
    try:
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS usuarios (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE NOT NULL,
                salt TEXT NOT NULL,
                senha_hash TEXT NOT NULL
            )
            """
        )
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS config_app (
                chave TEXT PRIMARY KEY,
                valor TEXT NOT NULL
            )
            """
        )
        conexao.execute(
            """
            CREATE TABLE IF NOT EXISTS sessoes (
                token TEXT PRIMARY KEY,
                usuario TEXT NOT NULL,
                criado_em TEXT NOT NULL DEFAULT (datetime('now'))
            )
            """
        )
        conexao.commit()
        existe_admin = conexao.execute(
            "SELECT 1 FROM usuarios WHERE usuario = ?", ("admin",)
        ).fetchone()
        if not existe_admin:
            criar_usuario("admin", "admin123")
    finally:
        conexao.close()


def criar_sessao(usuario: str) -> str:
    token = secrets.token_urlsafe(32)
    conexao = _conectar()
    try:
        conexao.execute(
            "INSERT INTO sessoes (token, usuario) VALUES (?, ?)",
            (token, usuario),
        )
        conexao.commit()
    finally:
        conexao.close()
    return token


def usuario_da_sessao(token: str) -> str | None:
    conexao = _conectar()
    try:
        linha = conexao.execute(
            "SELECT usuario FROM sessoes WHERE token = ?", (token,)
        ).fetchone()
    finally:
        conexao.close()
    return linha["usuario"] if linha else None


def obter_config_app(chave, padrao=None):
    conexao = _conectar()
    try:
        linha = conexao.execute("SELECT valor FROM config_app WHERE chave = ?", (chave,)).fetchone()
    finally:
        conexao.close()
    return linha["valor"] if linha else padrao


def definir_config_app(chave, valor):
    conexao = _conectar()
    try:
        conexao.execute(
            """
            INSERT INTO config_app (chave, valor) VALUES (?, ?)
            ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor
            """,
            (chave, valor),
        )
        conexao.commit()
    finally:
        conexao.close()


def criar_usuario(usuario, senha):
    salt = secrets.token_hex(16)
    senha_hash = _hash_senha(senha, salt)
    conexao = _conectar()
    try:
        conexao.execute(
            "INSERT INTO usuarios (usuario, salt, senha_hash) VALUES (?, ?, ?)",
            (usuario, salt, senha_hash),
        )
        conexao.commit()
    finally:
        conexao.close()


def verificar_login(usuario, senha):
    conexao = _conectar()
    try:
        linha = conexao.execute(
            "SELECT salt, senha_hash FROM usuarios WHERE usuario = ?", (usuario,)
        ).fetchone()
    finally:
        conexao.close()
    if linha is None:
        return False
    return _hash_senha(senha, linha["salt"]) == linha["senha_hash"]
