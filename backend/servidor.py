"""
Ponto de entrada do executável: sobe o backend, que também serve o frontend, e
abre o navegador padrão na interface.

Rodando do fonte o fluxo continua sendo `uvicorn main:app` (ou
`iniciar_motor_prisma.bat`) — este módulo existe para o pacote congelado, onde
não há linha de comando para digitar.
"""

import json
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import registro

PORTA_PREFERIDA = 8003
TENTATIVAS_DE_PORTA = 10
HOST = "127.0.0.1"

# ~30 s no total. Importar pandas/numpy no primeiro boot de um pacote congelado
# passa fácil de 10 s em máquina com antivírus inspecionando os arquivos.
ESPERAS_ATE_ABRIR = 60
INTERVALO_DE_ESPERA = 0.5


def _porta_livre(porta: int) -> bool:
    """True se dá para escutar em `porta` agora.

    SO_REUSEADDR fica de fora de propósito: no Windows ele permitiria o bind
    numa porta já em uso e a checagem passaria a mentir.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((HOST, porta))
        except OSError:
            return False
    return True


def _prisma_nesta_porta(porta: int) -> bool:
    """True se quem ocupa a porta é outra instância do Prisma.

    Serve para não subir uma segunda instância: duas escrevendo no mesmo app.db
    e na mesma pasta de trabalho é corrupção esperando acontecer.
    """
    url = f"http://{HOST}:{porta}/api/versao"
    try:
        with urllib.request.urlopen(url, timeout=2) as resposta:  # noqa: S310 (localhost)
            return json.load(resposta).get("app") == "Prisma"
    except (urllib.error.URLError, OSError, ValueError):
        return False


def escolher_porta() -> tuple[int, bool]:
    """`(porta, ja_esta_rodando)`.

    Percorre as portas a partir da preferida. Se encontrar um Prisma já no ar,
    devolve a porta dele com `ja_esta_rodando=True` para o chamador só abrir o
    navegador. A porta preferida costuma estar ocupada por um uvicorn órfão de
    uma execução anterior, e travar o app por causa disso seria gratuito.
    """
    for deslocamento in range(TENTATIVAS_DE_PORTA):
        porta = PORTA_PREFERIDA + deslocamento
        if _porta_livre(porta):
            return porta, False
        if _prisma_nesta_porta(porta):
            return porta, True
    raise SystemExit(
        f"Nenhuma porta livre entre {PORTA_PREFERIDA} e "
        f"{PORTA_PREFERIDA + TENTATIVAS_DE_PORTA - 1}. Feche outros programas "
        "que usem essas portas e tente de novo."
    )


def _abrir_navegador_quando_subir(porta: int) -> None:
    """Abre o navegador depois de confirmar que o servidor responde.

    Abrir junto com o processo mostraria erro de conexão: importar pandas e
    montar o app leva alguns segundos. A espera é ativa com pausa — sem a pausa
    as tentativas se esgotariam em milissegundos, porque conexão recusada volta
    na hora em vez de esperar o timeout.
    """
    url = f"http://{HOST}:{porta}"

    def tentar():
        for _ in range(ESPERAS_ATE_ABRIR):
            if _prisma_nesta_porta(porta):
                webbrowser.open(url)
                return
            time.sleep(INTERVALO_DE_ESPERA)
        print(f"O servidor demorou para responder. Abra {url} manualmente.")

    threading.Thread(target=tentar, daemon=True).start()


def _preparar_console() -> None:
    """Faz o console do Windows aceitar acento.

    O console herda a codepage do sistema (850/1252 no Brasil), então texto com
    acento sai como `j� est�` — a janela que o usuário mantém aberta é a única
    interface do executável, e não pode parecer defeituosa. `chcp` muda a
    codepage; `reconfigure` alinha o encoding do Python a ela. Ambos podem falhar
    quando a saída está redirecionada, e nesse caso não há console para arrumar.
    """
    if sys.platform != "win32":
        return
    os.system("chcp 65001 > nul")
    for fluxo in (sys.stdout, sys.stderr):
        try:
            fluxo.reconfigure(encoding="utf-8")
        except (AttributeError, OSError, ValueError):
            pass


def main() -> None:
    # Congelado no Windows, qualquer uso de multiprocessing relança o
    # executável em vez de bifurcar; sem isto o app abriria cópias de si mesmo.
    multiprocessing.freeze_support()
    _preparar_console()
    # Antes de qualquer print: sem console (modo janela) `sys.stdout` é None e
    # `print` levantaria AttributeError. configurar() cobre isso e liga o arquivo.
    caminho_log = registro.configurar()

    from versao import NOME_APP, VERSAO

    if sys.platform == "win32":
        os.system(f"title {NOME_APP} v{VERSAO}")

    porta, ja_esta_rodando = escolher_porta()
    url = f"http://{HOST}:{porta}"

    if ja_esta_rodando:
        print(f"{NOME_APP} já está rodando em {url} — abrindo no navegador.")
        webbrowser.open(url)
        return

    print(f"{NOME_APP} v{VERSAO}")
    print(f"Interface: {url}")
    print("Mantenha esta janela aberta enquanto estiver usando o sistema.")
    print("Para encerrar, feche a janela ou pressione Ctrl+C.\n")

    import uvicorn

    from main import app

    _abrir_navegador_quando_subir(porta)
    # `app` como objeto, não "main:app": a string faria o uvicorn reimportar o
    # módulo por nome, o que não funciona dentro do pacote congelado.
    # log_config=None: sem isto o uvicorn instala a configuração própria dele,
    # que só tem handlers de stream, e o log pararia de ir para o arquivo.
    uvicorn.run(
        app, host=HOST, port=porta, log_level="info",
        log_config=registro.config_uvicorn(),
    )


if __name__ == "__main__":
    main()
