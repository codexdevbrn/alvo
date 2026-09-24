"""
Cache em disco do resultado das telas (Clientes, Diagnóstico, Vendedores,
Estoque, Pós-precificação), na pasta de trabalho da empresa.

Por que existe: essas telas guardavam o resultado só na RAM do processo, com
`date.today()` na chave. Todo dia a primeira abertura de cada empresa recalculava
tudo (Clientes ~8 s na IBAD, Pós-precificação ~3 s), e cada máquina pagava de
novo, porque a RAM não é compartilhada. Com o resultado em disco, o lote da
manhã (`preparar_telas.py`) calcula uma vez e toda máquina lê pronto.

A chave é a MESMA tupla que a tela já usava na RAM (empresa, loja, modo,
assinatura da base, dia, cortes, tags...). Ela é serializada de forma estável e
vira o nome do arquivo (hash) — e fica gravada dentro dele, conferida na
leitura. Qualquer mudança que invalidaria a RAM (base nova, corte do dia, tag
editada) muda a chave, e o arquivo antigo simplesmente não é mais achado.

Best-effort nos dois sentidos: falha ao ler vira "não tem"; falha ao gravar
(OneDrive travando, disco cheio) só é registrada. Nunca escreve na fonte.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import logging
import os
import tempfile
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SUBPASTA = "_cache_telas"
#: Arquivo mais velho que isso é apagado na limpeza do lote. Com o dia na
#: chave, nada de ontem volta a ser lido; o prazo só evita acumular lixo.
DIAS_PARA_LIMPAR = 3


def _estavel(valor: Any) -> Any:
    """Estrutura só com tipos JSON e ordem determinística (set vira lista ordenada)."""
    if isinstance(valor, dict):
        return {str(k): _estavel(v) for k, v in sorted(valor.items(), key=lambda kv: str(kv[0]))}
    if isinstance(valor, (set, frozenset)):
        return sorted((_estavel(v) for v in valor), key=lambda v: json.dumps(v, sort_keys=True))
    if isinstance(valor, (list, tuple)):
        return [_estavel(v) for v in valor]
    if isinstance(valor, (date, datetime)):
        return valor.isoformat()
    if isinstance(valor, Path):
        return str(valor)
    if isinstance(valor, float):
        return repr(valor)  # mtime: repr é exato e igual entre processos
    if valor is None or isinstance(valor, (str, int, bool)):
        return valor
    return str(valor)


def texto_chave(tela: str, chave: Any) -> str:
    return json.dumps([tela, _estavel(chave)], ensure_ascii=False, sort_keys=True)


def caminho(pasta_trabalho: Path, tela: str, chave: Any) -> Path:
    resumo = hashlib.sha1(texto_chave(tela, chave).encode("utf-8")).hexdigest()[:20]
    return Path(pasta_trabalho) / SUBPASTA / f"{tela}-{resumo}.json.gz"


def ler(pasta_trabalho: Path, tela: str, chave: Any) -> dict | None:
    arquivo = caminho(pasta_trabalho, tela, chave)
    if not arquivo.is_file():
        return None
    try:
        with gzip.open(arquivo, "rt", encoding="utf-8") as f:
            conteudo = json.load(f)
    except Exception:  # noqa: BLE001 — arquivo pela metade ou corrompido: recalcula
        return None
    if conteudo.get("chave") != texto_chave(tela, chave):
        return None  # colisão de hash: improvável, mas não serve resultado de outra chave
    return conteudo.get("resultado")


def gravar(pasta_trabalho: Path, tela: str, chave: Any, resultado: dict) -> None:
    destino = caminho(pasta_trabalho, tela, chave)
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".tmp_", suffix=".json.gz", dir=destino.parent)
        os.close(fd)
        try:
            with gzip.open(tmp, "wt", encoding="utf-8", compresslevel=4) as f:
                json.dump(
                    {"chave": texto_chave(tela, chave), "gerado_em": datetime.now().isoformat(),
                     "resultado": resultado},
                    f, ensure_ascii=False, default=str,
                )
            os.replace(tmp, destino)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
    except Exception:  # noqa: BLE001
        logger.warning("Falha ao gravar cache da tela %s em %s", tela, destino, exc_info=True)


def limpar_antigos(pasta_trabalho: Path, dias: int = DIAS_PARA_LIMPAR) -> int:
    """Apaga arquivos de cache com mais de `dias` dias. Devolve quantos."""
    pasta = Path(pasta_trabalho) / SUBPASTA
    if not pasta.is_dir():
        return 0
    limite = time.time() - dias * 86400
    apagados = 0
    for arquivo in pasta.iterdir():
        try:
            if arquivo.is_file() and arquivo.stat().st_mtime < limite:
                arquivo.unlink()
                apagados += 1
        except OSError:
            continue
    return apagados
