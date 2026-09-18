"""
Cache em parquet do DataFrame bruto (MOVIMENTO_ATUAL + PRODUTO join) por empresa.

Por que existe: parsear os dois CSV de uma empresa grande custa segundos de CPU
(aspas, encoding com fallback, join, normalização de número). O cache em RAM do
processo (`_cache_base_empresa` em main.py) já evita reparse dentro do mesmo
processo, mas guarda só 1 empresa por vez — trocar de empresa, ou reiniciar o
backend (deploy/atualização), força reparse do zero. Este módulo grava, na
pasta de trabalho, uma cópia colunar do resultado do parse, ~40x mais rápida de
reler que o CSV.

Nunca escreve na fonte — só na pasta de trabalho, ao lado de
summary_dashboard.json/resumo_monitor.json. Frescor é o mtime do CSV mais
recente entre MOVIMENTO_ATUAL e PRODUTO, carimbado no próprio arquivo parquet
via `os.utime` (sem sidecar): se o mtime do parquet bater com o da fonte, o
cache está bom; senão, reparse e regrava.
"""

from __future__ import annotations

import logging
import os
import tempfile
from pathlib import Path

import pandas as pd

from engine import analise_funil as af

logger = logging.getLogger(__name__)

NOME_CACHE_PARQUET = "_cache_atacado.parquet"


def _mtime_fonte(caminho_movimento: Path, caminho_produto: Path) -> float:
    """mtime do mais recente entre os dois CSV da fonte."""
    return max(os.path.getmtime(caminho_movimento), os.path.getmtime(caminho_produto))


def carregar_atacado_df_cacheado(
    caminho_movimento: Path, caminho_produto: Path, pasta_trabalho: Path,
) -> pd.DataFrame:
    """Lê o join MOVIMENTO+PRODUTO, usando cache parquet na pasta de trabalho quando fresco.

    Comportamento idêntico a `af.carregar_csv_base_empresa(caminho_movimento,
    caminho_produto)` — este wrapper só decide se lê do parquet ou do CSV.
    """
    pasta_trabalho = Path(pasta_trabalho)
    mtime_fonte = _mtime_fonte(caminho_movimento, caminho_produto)
    caminho_parquet = pasta_trabalho / NOME_CACHE_PARQUET

    if caminho_parquet.is_file() and os.path.getmtime(caminho_parquet) == mtime_fonte:
        try:
            return pd.read_parquet(caminho_parquet)
        except Exception:
            # Parquet corrompido/incompleto (ex.: processo morto no meio da escrita
            # antes do os.replace) — cai para o CSV em vez de propagar o erro.
            pass

    df = af.carregar_csv_base_empresa(caminho_movimento, caminho_produto)
    try:
        _gravar_cache(df, pasta_trabalho, caminho_parquet, mtime_fonte)
    except Exception:
        # Cache é otimização, não requisito: falha ao gravar (disco cheio, pasta
        # de trabalho sem permissão, OneDrive travando o arquivo) não pode
        # impedir o carregamento — só volta a reparsear o CSV na próxima vez.
        logger.warning("Falha ao gravar cache parquet em %s", caminho_parquet, exc_info=True)
    return df


def _gravar_cache(df: pd.DataFrame, pasta_trabalho: Path, caminho_parquet: Path, mtime_fonte: float) -> None:
    """Grava via arquivo temporário + rename atômico, para não deixar um parquet
    parcial visível a outro processo (backend e lote noturno podem rodar juntos)."""
    pasta_trabalho.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".tmp_cache_atacado_", suffix=".parquet", dir=pasta_trabalho)
    os.close(fd)
    try:
        df.to_parquet(tmp_path, index=False)
        os.utime(tmp_path, (mtime_fonte, mtime_fonte))
        os.replace(tmp_path, caminho_parquet)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
