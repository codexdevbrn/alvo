"""
Ícone do Prisma na bandeja do Windows (área de notificação).

Existe porque a janela do console vai fechar depois do boot: sem ela, não haveria
como abrir a interface de novo nem encerrar o app a não ser pelo Gerenciador de
Tarefas. O ícone é a interface do processo em segundo plano.

A biblioteca (`pystray`) exige rodar no thread principal, então quem chama inverte
a ordem natural: o servidor vai para uma thread e a bandeja fica no principal.

Nada aqui é essencial ao funcionamento: numa sessão sem shell gráfico, ou se a
biblioteca faltar, `executar` devolve False e o chamador segue servindo. Perder o
ícone é ruim; não subir o servidor por causa dele seria pior.
"""

import logging
import threading
import webbrowser
from typing import Callable, Optional

logger = logging.getLogger(__name__)

TITULO = "Prisma"


def _carregar_icone():
    """Imagem do ícone, ou None se não der para carregar.

    Usa o mesmo `logo_2d_icone.png` do resto do sistema — a versão quadrada e sem
    o texto da marca, que é a única legível em 16×16.
    """
    try:
        from PIL import Image

        from engine.recursos import CAMINHO_LOGO_ICONE

        return Image.open(CAMINHO_LOGO_ICONE)
    except Exception as exc:  # noqa: BLE001 - qualquer falha aqui é degradação, não erro
        logger.warning("Não foi possível carregar o ícone da bandeja: %s", exc)
        return None


def executar(
    url: str,
    ao_sair: Callable[[], None],
    ao_verificar_atualizacao: Optional[Callable[[], None]] = None,
    ao_iniciar: Optional[Callable[[], None]] = None,
) -> bool:
    """Mostra o ícone e **bloqueia** até o usuário escolher Sair.

    `ao_iniciar` roda uma vez, já com o ícone registrado na bandeja. É onde o
    chamador fecha a janela do console: só é seguro fechá-la depois que existe
    outra forma de o usuário abrir a interface e encerrar o app.

    Devolve False sem bloquear se a bandeja não estiver disponível, para o
    chamador decidir como esperar pelo servidor.
    """
    try:
        import pystray
    except ImportError as exc:
        logger.warning("pystray indisponível, seguindo sem ícone na bandeja: %s", exc)
        return False

    icone_imagem = _carregar_icone()
    if icone_imagem is None:
        return False

    def abrir(_icone=None, _item=None):
        webbrowser.open(url)

    def verificar(_icone=None, _item=None):
        if ao_verificar_atualizacao is not None:
            ao_verificar_atualizacao()
        # Levar para a tela de Configurações, que é onde o resultado aparece e onde
        # fica o botão de aplicar.
        webbrowser.open(f"{url}/config")

    def sair(icone, _item=None):
        # Encerrar o servidor antes de tirar o ícone: se o ícone sumisse primeiro,
        # o usuário acharia que fechou enquanto o processo ainda estivesse no ar.
        try:
            ao_sair()
        finally:
            icone.stop()

    menu = pystray.Menu(
        pystray.MenuItem("Abrir Prisma", abrir, default=True),
        pystray.MenuItem("Verificar atualização", verificar),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Sair", sair),
    )

    try:
        icone = pystray.Icon("prisma", icone_imagem, TITULO, menu)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível criar o ícone da bandeja: %s", exc)
        return False

    def preparar(ic):
        ic.visible = True
        logger.info("Ícone da bandeja ativo (duplo clique abre a interface).")
        if ao_iniciar is not None:
            try:
                ao_iniciar()
            except Exception as exc:  # noqa: BLE001
                # Falhar aqui não pode derrubar a bandeja: o ícone é o que dá ao
                # usuário como sair do app.
                logger.warning("Falha em ao_iniciar da bandeja: %s", exc)

    try:
        # Bloqueia no laço de mensagens do Windows até icone.stop().
        icone.run(setup=preparar)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Laço da bandeja terminou com erro: %s", exc)
        return False
    return True


def notificar(mensagem: str, titulo: str = TITULO) -> None:
    """Balão na área de notificação. Silencioso se não houver bandeja.

    Usado para avisar de falha depois que o console já fechou, quando não há mais
    onde o usuário ver uma mensagem.
    """
    try:
        import pystray

        icone_imagem = _carregar_icone()
        if icone_imagem is None:
            return
        icone = pystray.Icon("prisma-aviso", icone_imagem, titulo)

        def mostrar(ic):
            ic.visible = True
            ic.notify(mensagem, titulo)
            # Sem isto o processo ficaria preso no laço deste ícone temporário.
            threading.Timer(8.0, ic.stop).start()

        icone.run(setup=mostrar)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Não foi possível notificar na bandeja: %s", exc)
