"""
Caminhos padrão do Prisma, derivados do OneDrive da empresa.

Existem para que uma máquina nova funcione sem ninguém configurar nada: os três
caminhos (fonte, trabalho e canal de atualização) ficam sempre nas mesmas pastas
do OneDrive corporativo, e o app as encontra sozinho.

Por que derivar em vez de fixar o texto completo: o caminho local do OneDrive
inclui o nome do usuário do Windows
(`C:\\Users\\<usuario>\\OneDrive - 2dconsultores.com.br\\...`), então um caminho
absoluto escrito aqui só funcionaria na máquina de quem o escreveu. A parte
relativa dentro do OneDrive, sim, é igual em todas.

O que o usuário salvar em Configurações continua tendo precedência — isto é só o
ponto de partida de quem nunca configurou.
"""

import os
from typing import Optional

#: Nome da conta corporativa. A pasta local do OneDrive de empresa é sempre
#: "OneDrive - <domínio>", e é isso que distingue da pessoal (só "OneDrive").
SUFIXO_ONEDRIVE_EMPRESA = "2dconsultores.com.br"

#: Trecho comum a todos os caminhos, dentro da raiz do OneDrive.
RAIZ_ECOSSISTEMA = os.path.join("01 - Marco + Monitores", "Ecossistema-Monitoria")

#: Subpastas, relativas a RAIZ_ECOSSISTEMA. Grafia exata das pastas que já
#: existem no OneDrive — inclusive o acento e a caixa, porque a pasta é criada
#: por pessoas e não pelo app, e o app não deve criar variação com outro nome.
SUBPASTA_FONTE = "Dados Alvos"
SUBPASTA_TRABALHO = "analisador"
SUBPASTA_ATUALIZACOES = os.path.join("Prisma", "Atualizações")


def raiz_onedrive_empresa() -> Optional[str]:
    """Pasta local do OneDrive corporativo, ou None se não houver.

    Tenta primeiro as variáveis que o cliente do OneDrive define na sessão do
    usuário; `OneDriveCommercial` é a da conta de empresa. Se elas não estiverem
    no ambiente — caso de processo iniciado fora da sessão interativa, como uma
    tarefa agendada como SYSTEM — procura a pasta no perfil do usuário.
    """
    for variavel in ("OneDriveCommercial", "OneDrive"):
        caminho = os.environ.get(variavel, "").strip()
        # A variável `OneDrive` pode apontar para a conta pessoal; só serve se
        # for a de empresa.
        if caminho and SUFIXO_ONEDRIVE_EMPRESA in caminho and os.path.isdir(caminho):
            return caminho

    perfil = os.environ.get("USERPROFILE", "").strip()
    if not perfil or not os.path.isdir(perfil):
        return None
    try:
        candidatos = os.listdir(perfil)
    except OSError:
        return None
    for nome in candidatos:
        if nome.startswith("OneDrive -") and SUFIXO_ONEDRIVE_EMPRESA in nome:
            caminho = os.path.join(perfil, nome)
            if os.path.isdir(caminho):
                return caminho
    return None


def _padrao(subpasta: str) -> Optional[str]:
    """Caminho padrão da subpasta, ou None se o OneDrive não estiver na máquina.

    Só devolve o que existe: sugerir uma pasta ausente faria o app tentar ler dali
    e falhar com erro de caminho, o que é pior do que dizer que não está
    configurado e deixar o usuário escolher.
    """
    raiz = raiz_onedrive_empresa()
    if not raiz:
        return None
    caminho = os.path.join(raiz, RAIZ_ECOSSISTEMA, subpasta)
    return caminho if os.path.isdir(caminho) else None


def fonte_dados() -> Optional[str]:
    return _padrao(SUBPASTA_FONTE)


def trabalho() -> Optional[str]:
    """Pasta de trabalho compartilhada.

    Compartilhada de propósito: é nela que o lote noturno grava os summaries. Uma
    máquina apontando para pasta local vazia teria de gerar cada empresa na hora
    (minutos por empresa, lendo dezenas de MB do OneDrive), com o usuário
    esperando — em vez de baixar um arquivo já pronto.
    """
    return _padrao(SUBPASTA_TRABALHO)


def atualizacoes() -> Optional[str]:
    return _padrao(SUBPASTA_ATUALIZACOES)
