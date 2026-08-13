"""
Log em arquivo do Prisma.

Existe por causa do modo sem console: empacotado como aplicação de janela, o
processo não tem console, `sys.stdout` é None, e aí `print` levanta AttributeError
em vez de só perder a mensagem — o que derruba o app no boot. O `StreamHandler`
padrão do uvicorn tem o mesmo problema.

Então tudo passa a ir para `logs/prisma.log` ao lado do executável, e a saída
padrão é substituída por um adaptador quando ela não existe, para que qualquer
`print` de terceiros (uvicorn, pandas, PyInstaller) também caia no arquivo em vez
de estourar.

Sem console, o log é a única forma de descobrir por que o app não subiu.
"""

import logging
import logging.handlers
import os
import sys

from engine.recursos import pasta_logs

NOME_ARQUIVO = "prisma.log"

# ~5 MB × 3 arquivos. O log é sobretudo o access log do uvicorn; num dia de uso
# intenso passa de 1 MB, e três gerações cobrem o histórico útil para suporte sem
# crescer sem limite na máquina do usuário.
BYTES_POR_ARQUIVO = 5 * 1024 * 1024
ARQUIVOS_MANTIDOS = 3

FORMATO = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"


class _SaidaParaLog:
    """Objeto mínimo tipo arquivo que encaminha escritas para o log.

    Substitui `sys.stdout`/`sys.stderr` quando eles não existem. Só implementa o
    que o CPython e as bibliotecas de fato chamam: `write`, `flush`, `isatty` e
    `fileno` — este último levantando, que é o comportamento esperado de um
    stream sem descritor.
    """

    def __init__(self, logger: logging.Logger, nivel: int):
        self._logger = logger
        self._nivel = nivel
        self._parcial = ""

    def write(self, texto):
        if not texto:
            return 0
        # `print` chama write duas vezes (texto e "\n"); acumular até a quebra
        # evita uma linha de log por fragmento.
        self._parcial += texto
        while "\n" in self._parcial:
            linha, self._parcial = self._parcial.split("\n", 1)
            if linha.strip():
                self._logger.log(self._nivel, linha)
        return len(texto)

    def flush(self):
        if self._parcial.strip():
            self._logger.log(self._nivel, self._parcial)
        self._parcial = ""

    def isatty(self):
        return False

    def fileno(self):
        raise OSError("stream sem descritor de arquivo")


def caminho_arquivo() -> str:
    return os.path.join(pasta_logs(), NOME_ARQUIVO)


def configurar() -> str:
    """Liga o log em arquivo e devolve o caminho dele.

    Idempotente: chamar duas vezes não duplica handler nem duplica cada linha no
    arquivo.
    """
    caminho = caminho_arquivo()
    raiz = logging.getLogger()
    raiz.setLevel(logging.INFO)

    ja_configurado = any(
        isinstance(h, logging.handlers.RotatingFileHandler)
        and getattr(h, "baseFilename", None) == caminho
        for h in raiz.handlers
    )
    if not ja_configurado:
        arquivo = logging.handlers.RotatingFileHandler(
            caminho,
            maxBytes=BYTES_POR_ARQUIVO,
            backupCount=ARQUIVOS_MANTIDOS,
            encoding="utf-8",
        )
        arquivo.setFormatter(logging.Formatter(FORMATO))
        raiz.addHandler(arquivo)

    # Console continua recebendo quando existe: rodando do fonte, ver o log na
    # hora é mais prático do que abrir o arquivo.
    tem_console = sys.stdout is not None and sys.stdout.isatty()
    if tem_console and not any(
        isinstance(h, logging.StreamHandler)
        and not isinstance(h, logging.handlers.RotatingFileHandler)
        for h in raiz.handlers
    ):
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(FORMATO))
        raiz.addHandler(console)

    _redirecionar_saida_ausente()
    return caminho


def _redirecionar_saida_ausente() -> None:
    """Aponta stdout/stderr para o log quando o processo não tem console."""
    logger = logging.getLogger("stdout")
    if sys.stdout is None:
        sys.stdout = _SaidaParaLog(logger, logging.INFO)
    if sys.stderr is None:
        sys.stderr = _SaidaParaLog(logging.getLogger("stderr"), logging.ERROR)


def desviar_saida_do_console() -> None:
    """Troca stdout/stderr pelo log, mesmo que ainda pareçam válidos.

    Chamado imediatamente antes de `FreeConsole()`: soltar o console invalida os
    handles sem torná-los None, e aí o primeiro `print` levantaria OSError em vez
    de só não aparecer. Também remove o StreamHandler do console, que passaria a
    escrever num handle morto a cada linha de log.
    """
    sys.stdout = _SaidaParaLog(logging.getLogger("stdout"), logging.INFO)
    sys.stderr = _SaidaParaLog(logging.getLogger("stderr"), logging.ERROR)

    raiz = logging.getLogger()
    for handler in list(raiz.handlers):
        if isinstance(handler, logging.StreamHandler) and not isinstance(
            handler, logging.handlers.RotatingFileHandler
        ):
            raiz.removeHandler(handler)
            handler.close()


def config_uvicorn() -> None:
    """O que passar em `uvicorn.run(log_config=...)`.

    None faz o uvicorn **não** instalar a configuração própria dele, que só tem
    handlers de stream. Assim ele herda a raiz configurada aqui e o access log vai
    para o arquivo junto com o resto.
    """
    return None
