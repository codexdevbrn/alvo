"""
Ponto de entrada do executável. Dois modos:

    Prisma.exe                 sobe o backend, serve o frontend, abre o navegador
    Prisma.exe --pre-gerar     roda o lote de pré-geração de summaries e encerra

O modo de lote existe para a máquina que hospeda a tarefa agendada não precisar de
Python nem do repositório: o executável já carrega o lote, e o canal de atualização
mantém os dois em versão igual. Antes disso, o lote era um script solto da árvore de
código, e ficou três semanas quebrado sem ninguém notar porque nada o mantinha
junto do app.

Rodando do fonte, o fluxo continua sendo `uvicorn main:app` (ou
`iniciar_motor_prisma.bat`) e `python normalizar_todas_empresas.py`.
"""

import ctypes
import json
import logging
import multiprocessing
import os
import socket
import sys
import threading
import time
import urllib.error
import urllib.request
import webbrowser

import bandeja
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


def _fechar_console() -> bool:
    """Solta a janela do console, mantendo o processo servindo.

    O usuário pediu que a janela apareça no início e feche "quando estiver tudo
    ok". `FreeConsole` faz exatamente isso, e é bem menos invasivo que empacotar
    como aplicação de janela: o executável continua sendo aplicação de console, o
    que mantém o bootloader do PyInstaller e as flags de religamento do atualizador
    exatamente como estão — e um erro no boot continua visível, porque nesse caso
    nunca chegamos aqui.

    A saída padrão é desviada para o log ANTES de soltar: `FreeConsole` invalida os
    handles sem torná-los None, então o primeiro print depois disso levantaria
    OSError.
    """
    if sys.platform != "win32":
        return False
    if not getattr(sys, "frozen", False):
        # Rodando do fonte, a janela é do desenvolvedor e deve continuar lá.
        return False

    registro.desviar_saida_do_console()
    try:
        liberou = bool(ctypes.windll.kernel32.FreeConsole())
    except Exception as exc:  # noqa: BLE001
        logging.getLogger(__name__).warning("Não foi possível fechar o console: %s", exc)
        return False
    logging.getLogger(__name__).info(
        "Console fechado; o Prisma segue rodando na bandeja." if liberou
        else "FreeConsole não liberou o console."
    )
    return liberou


def _esperar_servidor(porta: int) -> bool:
    """True quando o servidor responde; False se estourar a espera."""
    for _ in range(ESPERAS_ATE_ABRIR):
        if _prisma_nesta_porta(porta):
            return True
        time.sleep(INTERVALO_DE_ESPERA)
    return False


ARG_PRE_GERAR = "--pre-gerar"


def _rodar_lote() -> int:
    """Executa a pré-geração e devolve o código de saída.

    Reusa `normalizar_todas_empresas.main()` em vez de reimplementar: é a mesma
    razão de o lote gerar o summary pelo mesmo caminho do app — duas
    implementações divergem com o tempo. Os argumentos restantes são repassados,
    então `Prisma.exe --pre-gerar --so Comkit` funciona.
    """
    # Congelado, o módulo vem embutido (ver hiddenimports no prisma.spec). Rodando
    # do fonte, ele fica na raiz do projeto e este arquivo em backend/, então a raiz
    # precisa entrar no path — é o mesmo ajuste que main.py faz para os scripts de
    # normalização.
    if not getattr(sys, "frozen", False):
        raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if raiz not in sys.path:
            sys.path.insert(0, raiz)

    import normalizar_todas_empresas as lote

    argv_original = sys.argv
    sys.argv = [argv_original[0]] + [a for a in argv_original[1:] if a != ARG_PRE_GERAR]
    try:
        lote.main()
    except SystemExit as saida:
        # argparse e o próprio lote encerram com sys.exit; o código importa para o
        # Agendador de Tarefas registrar sucesso ou falha.
        return int(saida.code or 0)
    except Exception:
        logging.getLogger(__name__).exception("Falha inesperada na pré-geração.")
        return 1
    finally:
        sys.argv = argv_original
    return 0


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

    if ARG_PRE_GERAR in sys.argv:
        # Sai antes de escolher porta, subir bandeja ou fechar console: é execução
        # de lote, sem interface, e a janela precisa ficar para o log ser visto.
        print(f"{NOME_APP} v{VERSAO} — pré-geração de summaries")
        print(f"Log: {caminho_log}")
        print()
        sys.exit(_rodar_lote())

    porta, ja_esta_rodando = escolher_porta()
    url = f"http://{HOST}:{porta}"

    if ja_esta_rodando:
        print(f"{NOME_APP} já está rodando em {url} — abrindo no navegador.")
        webbrowser.open(url)
        return

    print(f"{NOME_APP} v{VERSAO}")
    print(f"Interface: {url}")
    print(f"Log: {caminho_log}")

    import uvicorn

    from main import app

    # `app` como objeto, não "main:app": a string faria o uvicorn reimportar o
    # módulo por nome, o que não funciona dentro do pacote congelado.
    # log_config=None: sem isto o uvicorn instala a configuração própria dele,
    # que só tem handlers de stream, e o log pararia de ir para o arquivo.
    configuracao = uvicorn.Config(
        app, host=HOST, port=porta, log_level="info",
        log_config=registro.config_uvicorn(),
    )
    servidor = uvicorn.Server(configuracao)

    # Servidor na thread e bandeja no principal, e não o contrário: o laço de
    # mensagens do Windows que a bandeja usa só roda no thread principal.
    thread_servidor = threading.Thread(target=servidor.run, name="uvicorn", daemon=True)
    thread_servidor.start()

    _abrir_navegador_quando_subir(porta)

    def encerrar():
        print("Encerrando o Prisma...")
        servidor.should_exit = True

    def quando_a_bandeja_subir():
        # Só fecha a janela depois de o servidor responder de fato. Fechar antes
        # esconderia justamente a falha que o usuário precisa ver.
        if _esperar_servidor(porta):
            _fechar_console()
        else:
            print(
                "O servidor não respondeu; a janela fica aberta para você ver o erro."
            )

    def versao_no_canal():
        """Versão nova, se houver, lida do cache que a verificação periódica mantém.

        Lê o cache do mesmo processo em vez de chamar a própria API: é o mesmo dado,
        sem custo de rede, e o menu abre sem esperar.
        """
        import atualizacoes

        status = atualizacoes._cache_status
        return status.versao_disponivel if status and status.atualizavel else None

    com_bandeja = bandeja.executar(
        url=url,
        ao_sair=encerrar,
        ao_iniciar=quando_a_bandeja_subir,
        versao_disponivel=versao_no_canal,
    )

    if com_bandeja:
        # `executar` só retorna quando o usuário escolheu Sair; dar tempo ao
        # uvicorn de fechar as conexões antes de o processo terminar.
        thread_servidor.join(timeout=10)
        return

    # Sem bandeja (sessão sem shell gráfico, ou biblioteca ausente) o console volta
    # a ser a única interface, então ele não pode fechar.
    print("Mantenha esta janela aberta enquanto estiver usando o sistema.")
    print("Para encerrar, feche a janela ou pressione Ctrl+C.\n")
    try:
        while thread_servidor.is_alive():
            thread_servidor.join(timeout=1.0)
    except KeyboardInterrupt:
        encerrar()
        thread_servidor.join(timeout=10)


if __name__ == "__main__":
    main()
