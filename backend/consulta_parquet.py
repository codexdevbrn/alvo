"""
Consultas SQL (DuckDB) direto nos parquet da fonte.

Por que existe: com a fonte em parquet, boa parte do que o app faz em pandas —
carregar a base inteira na RAM, limpar, e só então agregar — pode virar uma
consulta que lê do disco só as colunas e os blocos de linhas que a pergunta
precisa. O rodapé do parquet guarda mínimo e máximo por bloco, então
`max(DATA_MOVIMENTO)` nem chega a ler dado.

Somente leitura, em duas camadas: a conexão é em memória (não existe arquivo
de banco para gravar) e o módulo só roda SQL escrito aqui, com caminho passado
como parâmetro — nada vindo da requisição vira texto de SQL. A regra da fonte
somente-leitura continua valendo: `COPY`/`EXPORT` não aparecem neste módulo.

Conexão por chamada, não global: o DuckDB não deixa a mesma conexão ser usada
por duas threads ao mesmo tempo, e o FastAPI atende requisições em paralelo.
Abrir uma conexão em memória custa ~1 ms.
"""

from __future__ import annotations

import logging
import os
import threading
from datetime import date
from pathlib import Path
from typing import Any, Sequence

import duckdb
import pandas as pd

logger = logging.getLogger(__name__)


def consultar(sql: str, parametros: Sequence[Any] | None = None) -> pd.DataFrame:
    """Roda `sql` numa conexão em memória e devolve um DataFrame.

    Caminho de arquivo entra como parâmetro (`read_parquet(?)`), nunca
    interpolado: nome de empresa tem espaço, acento e ponto (`Peca.com`).
    """
    with duckdb.connect(":memory:") as conexao:
        return conexao.execute(sql, list(parametros or [])).df()


def _assinatura(caminho: Path) -> tuple[str, float, int]:
    info = os.stat(caminho)
    return (os.path.normcase(str(caminho)), info.st_mtime, info.st_size)


_cache_ultimo_movimento: dict[tuple[str, float, int], date | None] = {}
_trava_cache = threading.Lock()


def ultimo_movimento(caminho_movimento: Path) -> date | None:
    """Maior `DATA_MOVIMENTO` do arquivo — o "Último movimento" da barra lateral.

    Antes era a data de modificação do arquivo, que é quando o OneDrive
    sincronizou, não o último dia com venda. Sai das estatísticas do rodapé,
    então custa o mesmo para 100 mil ou 2 milhões de linhas; ainda assim fica
    em cache por (caminho, mtime, tamanho), porque é pedida a cada summary.
    """
    caminho_movimento = Path(caminho_movimento)
    chave = _assinatura(caminho_movimento)
    with _trava_cache:
        if chave in _cache_ultimo_movimento:
            return _cache_ultimo_movimento[chave]

    df = consultar("select max(DATA_MOVIMENTO) as ultimo from read_parquet(?)", [str(caminho_movimento)])
    valor = df["ultimo"].iloc[0] if not df.empty else None
    resultado = None if valor is None or pd.isna(valor) else pd.Timestamp(valor).date()

    with _trava_cache:
        # Uma entrada por arquivo: versão velha do mesmo caminho sai do cache.
        for antiga in [k for k in _cache_ultimo_movimento if k[0] == chave[0]]:
            del _cache_ultimo_movimento[antiga]
        _cache_ultimo_movimento[chave] = resultado
    return resultado
