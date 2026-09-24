"""Consultas DuckDB nos parquet da fonte (backend/consulta_parquet.py)."""

import os
from datetime import date

import main  # noqa: F401  (insere a raiz do projeto no sys.path)
import consulta_parquet as cp
from fonte_parquet_util import escrever_fonte


def _movimento(datas: list[str]) -> list[dict]:
    return [
        {"ID_LOJA": "1", "CODIGO_PRODUTO": "1", "DATA_MOVIMENTO": d, "TOTAL": "10,00"}
        for d in datas
    ]


def test_ultimo_movimento_e_a_maior_data_do_arquivo(tmp_path):
    caminho = escrever_fonte(tmp_path / "Peça.com_MOVIMENTO_ATUAL.parquet",
                             _movimento(["2026-08-15", "2026-09-22", "2026-09-01"]))
    assert cp.ultimo_movimento(caminho) == date(2026, 9, 22)


def test_ultimo_movimento_acompanha_o_arquivo_novo(tmp_path):
    """O cache é por (caminho, mtime, tamanho): arquivo reescrito é relido."""
    caminho = escrever_fonte(tmp_path / "E_MOVIMENTO_ATUAL.parquet", _movimento(["2026-09-01"]))
    assert cp.ultimo_movimento(caminho) == date(2026, 9, 1)
    escrever_fonte(caminho, _movimento(["2026-09-01", "2026-09-23"]))
    futuro = os.stat(caminho).st_mtime + 10
    os.utime(caminho, (futuro, futuro))
    assert cp.ultimo_movimento(caminho) == date(2026, 9, 23)


def test_ultimo_movimento_sem_data_devolve_none(tmp_path):
    caminho = escrever_fonte(tmp_path / "E_MOVIMENTO_ATUAL.parquet",
                             [{"ID_LOJA": "1", "DATA_MOVIMENTO": None}])
    assert cp.ultimo_movimento(caminho) is None


def test_consultar_recebe_caminho_como_parametro(tmp_path):
    """Nome de empresa com espaço, acento e aspas não pode quebrar o SQL."""
    caminho = escrever_fonte(tmp_path / "O'Reilly Peças_MOVIMENTO_ATUAL.parquet",
                             _movimento(["2026-09-01", "2026-09-02"]))
    df = cp.consultar("select count(*) as n, sum(TOTAL) as receita from read_parquet(?)", [str(caminho)])
    assert int(df["n"].iloc[0]) == 2
    assert float(df["receita"].iloc[0]) == 20.0
