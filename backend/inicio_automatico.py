"""
Início automático do Prisma: com o Windows e/ou num horário fixo.

Duas coisas diferentes, porque resolvem situações diferentes:

- **Com o Windows**: valor em `HKCU\\...\\Run`. Abre no logon do usuário.
- **Num horário**: tarefa no Agendador. Serve para a máquina que fica ligada e
  onde o Prisma foi fechado — às 8h ele volta sozinho.

Tudo por usuário e sem elevação: a chave é HKCU e a tarefa roda como o usuário
logado. Nada aqui exige admin, e nada afeta outros usuários da máquina.

Se o Prisma já estiver rodando quando o gatilho disparar, a guarda de instância
única de `servidor.escolher_porta` cuida: a segunda cópia vê a primeira, abre o
navegador nela e encerra.
"""

import logging
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from typing import Optional

logger = logging.getLogger(__name__)

CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
NOME_VALOR = "Prisma"
NOME_TAREFA = "Prisma - abrir diariamente"

# CREATE_NO_WINDOW: sem isto cada chamada ao schtasks pisca um console preto na
# tela do usuário, e o app justamente deixou de ter janela.
_SEM_JANELA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def disponivel() -> bool:
    """Só faz sentido com um executável para agendar.

    Rodando do fonte o comando seria `python servidor.py` com um interpretador e um
    diretório que podem mudar; agendar isso criaria uma entrada que quebra sem
    ninguém entender por quê.
    """
    return sys.platform == "win32" and getattr(sys, "frozen", False)


def caminho_executavel() -> str:
    return os.path.abspath(sys.executable)


# ---------------------------------------------------------------------------
# Com o Windows (chave Run)
# ---------------------------------------------------------------------------

def _comando_registro() -> str:
    # Aspas porque o caminho de instalação contém espaços em quase toda máquina
    # ("C:\\Users\\...\\AppData\\Local\\Prisma").
    return f'"{caminho_executavel()}"'


def logon_ativo() -> bool:
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_RUN) as chave:
            valor, _tipo = winreg.QueryValueEx(chave, NOME_VALOR)
    except FileNotFoundError:
        return False
    except OSError as exc:
        logger.warning("Não foi possível ler a chave Run: %s", exc)
        return False
    return bool(valor)


def definir_logon(ativo: bool) -> None:
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE
    ) as chave:
        if ativo:
            winreg.SetValueEx(
                chave, NOME_VALOR, 0, winreg.REG_SZ, _comando_registro()
            )
            logger.info("Início com o Windows ligado: %s", _comando_registro())
        else:
            try:
                winreg.DeleteValue(chave, NOME_VALOR)
                logger.info("Início com o Windows desligado.")
            except FileNotFoundError:
                pass  # já não estava lá


# ---------------------------------------------------------------------------
# Num horário (Agendador de Tarefas)
# ---------------------------------------------------------------------------

def _schtasks(*args: str) -> subprocess.CompletedProcess:
    """Chama o schtasks capturando a saída.

    `stdin=DEVNULL` não é decoração: o app fecha o próprio console depois do boot
    (ver `servidor._fechar_console`), e a partir daí os handles padrão do processo
    estão inválidos. Sem informar stdin explicitamente, o subprocess tenta duplicar
    o stdin herdado e falha com `WinError 50 — Não há suporte para o pedido`.
    """
    return subprocess.run(
        ["schtasks", *args],
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        check=False,
        creationflags=_SEM_JANELA,
    )


def horario_agendado() -> Optional[str]:
    """`"HH:MM"` da tarefa diária, ou None se não existir.

    Lê o XML da tarefa em vez da saída em lista porque aquela é traduzida: o rótulo
    da hora muda com o idioma do Windows, e parsear texto localizado quebraria numa
    máquina em inglês.
    """
    resultado = _schtasks("/Query", "/TN", NOME_TAREFA, "/XML")
    if resultado.returncode != 0:
        return None
    try:
        raiz = ET.fromstring(resultado.stdout)
    except ET.ParseError as exc:
        logger.warning("XML da tarefa agendada ilegível: %s", exc)
        return None
    # O XML do Agendador usa namespace; buscar pelo nome local evita depender dele.
    for elemento in raiz.iter():
        if elemento.tag.rsplit("}", 1)[-1] == "StartBoundary" and elemento.text:
            # "2026-08-12T08:30:00" -> "08:30"
            hora = elemento.text.split("T", 1)[-1]
            return hora[:5]
    return None


def definir_horario(horario: Optional[str]) -> None:
    """Cria/atualiza a tarefa diária, ou remove quando `horario` é None."""
    if horario is None:
        resultado = _schtasks("/Delete", "/TN", NOME_TAREFA, "/F")
        # returncode != 0 quando a tarefa não existe; remover o que não existe é
        # sucesso do ponto de vista de quem chamou.
        logger.info("Agendamento removido (schtasks saiu com %s).", resultado.returncode)
        return

    validar_horario(horario)
    resultado = _schtasks(
        "/Create",
        "/TN", NOME_TAREFA,
        "/TR", _comando_registro(),
        "/SC", "DAILY",
        "/ST", horario,
        "/F",  # sobrescreve, para "salvar" com outra hora não exigir remover antes
    )
    if resultado.returncode != 0:
        raise ErroInicioAutomatico(
            (resultado.stderr or resultado.stdout or "").strip()
            or "Não foi possível criar a tarefa agendada."
        )
    logger.info("Agendado para abrir todo dia às %s.", horario)


class ErroInicioAutomatico(Exception):
    """Falha ao ler ou gravar a configuração de início automático."""


def validar_horario(horario: str) -> str:
    """Garante `HH:MM` 24h. O schtasks aceita formatos estranhos e falha depois."""
    partes = horario.strip().split(":")
    if len(partes) != 2 or not all(p.isdigit() for p in partes):
        raise ErroInicioAutomatico("Informe o horário como HH:MM (ex.: 08:30).")
    hora, minuto = (int(p) for p in partes)
    if not (0 <= hora <= 23 and 0 <= minuto <= 59):
        raise ErroInicioAutomatico("Horário fora da faixa: use 00:00 a 23:59.")
    return f"{hora:02d}:{minuto:02d}"


def estado() -> dict:
    """O que a interface precisa saber, num objeto só."""
    if not disponivel():
        return {
            "disponivel": False,
            "logon": False,
            "horario": None,
            "motivo": "O início automático só existe na versão instalada (.exe).",
        }
    return {
        "disponivel": True,
        "logon": logon_ativo(),
        "horario": horario_agendado(),
        "motivo": "",
    }
