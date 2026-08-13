"""
Manter os dados do Prisma sempre baixados nesta máquina.

É o mesmo "Sempre manter neste dispositivo" do menu do OneDrive, feito pelo app:
marcar a pasta com `FILE_ATTRIBUTE_PINNED` faz o cliente do OneDrive baixar o
conteúdo e não o transformar de volta em placeholder para liberar espaço.

Para que serve: com *Files On-Demand*, um arquivo pode existir só como marcador, e
a primeira leitura paga o download. Numa máquina nova isso atinge tanto a fonte
(planilhas de dezenas de MB) quanto a pasta de trabalho (um summary de 13-20 MB por
empresa). Pinado, nada disso acontece no meio do uso.

Para que NÃO serve: acelerar o que já está local. Nesta máquina a fonte já vem
pinada, e a lentidão medida na geração de summary era o parser de xlsx, não a rede.

Marcar é instantâneo — é metadado. O download acontece depois, pelo cliente do
OneDrive, no tempo dele.
"""

import ctypes
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Flags de armazenamento na nuvem do Windows (winnt.h).
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
#: Presente quando o conteúdo NÃO está local: ler dispara download.
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

_ATRIBUTO_INVALIDO = 0xFFFFFFFF


class ErroDadosNoDisco(Exception):
    """Falha ao ler ou alterar os atributos de uma pasta."""


def _get_atributos(caminho: str) -> Optional[int]:
    valor = ctypes.windll.kernel32.GetFileAttributesW(ctypes.c_wchar_p(caminho))
    return None if valor == _ATRIBUTO_INVALIDO else valor


def _set_atributos(caminho: str, valor: int) -> bool:
    return bool(
        ctypes.windll.kernel32.SetFileAttributesW(ctypes.c_wchar_p(caminho), valor)
    )


def _marcar(caminho: str, fixar: bool) -> bool:
    """Liga PINNED e desliga UNPINNED (ou o contrário)."""
    atual = _get_atributos(caminho)
    if atual is None:
        return False
    if fixar:
        novo = (atual | FILE_ATTRIBUTE_PINNED) & ~FILE_ATTRIBUTE_UNPINNED
    else:
        novo = (atual | FILE_ATTRIBUTE_UNPINNED) & ~FILE_ATTRIBUTE_PINNED
    if novo == atual:
        return True
    return _set_atributos(caminho, novo)


def suportado() -> bool:
    return os.name == "nt"


def estado(caminho: Optional[str]) -> dict:
    """Resumo do que está local naquela árvore.

    Percorre só arquivos: uma pasta marcada não garante que o conteúdo já desceu, e
    é o conteúdo que interessa a quem vai esperar a leitura.
    """
    if not suportado():
        return {"suportado": False, "caminho": caminho, "arquivos": 0,
                "fixados": 0, "na_nuvem": 0, "bytes": 0}
    if not caminho or not os.path.isdir(caminho):
        return {"suportado": True, "caminho": caminho, "arquivos": 0,
                "fixados": 0, "na_nuvem": 0, "bytes": 0}

    arquivos = fixados = na_nuvem = 0
    total_bytes = 0
    for raiz, _pastas, nomes in os.walk(caminho):
        for nome in nomes:
            completo = os.path.join(raiz, nome)
            atributos = _get_atributos(completo)
            if atributos is None:
                continue
            arquivos += 1
            if atributos & FILE_ATTRIBUTE_PINNED:
                fixados += 1
            if atributos & FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS:
                na_nuvem += 1
            try:
                total_bytes += os.path.getsize(completo)
            except OSError:
                # Placeholder pode recusar getsize; o tamanho é informativo.
                pass
    return {
        "suportado": True,
        "caminho": caminho,
        "arquivos": arquivos,
        "fixados": fixados,
        "na_nuvem": na_nuvem,
        "bytes": total_bytes,
    }


def aplicar(caminho: Optional[str], fixar: bool) -> dict:
    """Marca a árvore inteira e devolve o que foi tocado.

    As pastas também são marcadas, e não só os arquivos: sem isso, o que a coleta
    gravar amanhã nasceria como placeholder de novo.
    """
    if not suportado():
        raise ErroDadosNoDisco("Só funciona no Windows.")
    if not caminho or not os.path.isdir(caminho):
        raise ErroDadosNoDisco(f"Pasta inacessível: {caminho}")

    tocados = falhas = 0
    if _marcar(caminho, fixar):
        tocados += 1
    else:
        falhas += 1
    for raiz, pastas, nomes in os.walk(caminho):
        for nome in list(pastas) + nomes:
            if _marcar(os.path.join(raiz, nome), fixar):
                tocados += 1
            else:
                falhas += 1

    logger.info(
        "%s %s: %d itens marcados, %d falhas.",
        "Fixado" if fixar else "Liberado", caminho, tocados, falhas,
    )
    if falhas and not tocados:
        raise ErroDadosNoDisco(
            "Não foi possível alterar nenhum item — a pasta é sincronizada pelo OneDrive?"
        )
    return {"tocados": tocados, "falhas": falhas, **estado(caminho)}
