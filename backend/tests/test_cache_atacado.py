"""Cache parquet do join MOVIMENTO+PRODUTO (backend/cache_atacado.py)."""

import os
import time
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import cache_atacado
import main  # noqa: F401  (garante raiz do projeto no sys.path, como no servidor)
from engine import analise_funil as af


def _escrever_csv(caminho: Path, linhas: list[dict]) -> None:
    pd.DataFrame(linhas).to_csv(caminho, sep=";", index=False, encoding="utf-8-sig")


def _linha_movimento(**overrides) -> dict:
    base = {
        "ID_LOJA": "1",
        "CODIGO_PRODUTO": "100",
        "CODIGO_REFERENCIA_PRODUTO": "REF-100",
        "DESCRICAO_PRODUTO": "produto bruto 100",
        "NOME_FABRICANTE": "Fabricante X",
        "NOME_CLIENTE": "Cliente A",
        "NOME_VENDEDOR": "João",
        "DATA_MOVIMENTO": "2026-08-15",
        "DIA": "15",
        "MES": "8",
        "ANO": "2026",
        "TOTAL": "1.234,56",
        "QUANTIDADE": "3",
        "CMV": "800,00",
    }
    base.update(overrides)
    return base


def _linha_produto(**overrides) -> dict:
    base = {
        "ID_LOJA": "1",
        "CODIGO_INTERNO_PRODUTO": "100",
        "CODIGO_REFERENCIA_PRODUTO": "REF-100",
        "DESCRICAO_PRODUTO": "produto bruto 100",
        "DESCRICAO_HARMONIZADA": "Produto Harmonizado 100",
        "QUANTIDADE_ESTOQUE": "12",
    }
    base.update(overrides)
    return base


def _preparar_fonte(tmp_path: Path) -> tuple[Path, Path]:
    pasta = tmp_path / "fonte" / "Empresa"
    pasta.mkdir(parents=True)
    caminho_movimento = pasta / "Empresa_MOVIMENTO_ATUAL.csv"
    caminho_produto = pasta / "Empresa_PRODUTO.csv"
    _escrever_csv(caminho_movimento, [_linha_movimento()])
    _escrever_csv(caminho_produto, [_linha_produto()])
    return caminho_movimento, caminho_produto


def test_grava_parquet_e_reusa_sem_reparsear_csv(tmp_path):
    caminho_movimento, caminho_produto = _preparar_fonte(tmp_path)
    pasta_trabalho = tmp_path / "trabalho" / "Empresa"

    df1 = cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
    caminho_parquet = pasta_trabalho / cache_atacado.NOME_CACHE_PARQUET
    assert caminho_parquet.is_file()

    with patch.object(af, "carregar_csv_base_empresa") as mock_parse:
        df2 = cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
        mock_parse.assert_not_called()

    pd.testing.assert_frame_equal(df1.reset_index(drop=True), df2.reset_index(drop=True))


def test_csv_alterado_invalida_cache(tmp_path):
    caminho_movimento, caminho_produto = _preparar_fonte(tmp_path)
    pasta_trabalho = tmp_path / "trabalho" / "Empresa"

    df1 = cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
    assert df1["Código Interno"].tolist() == ["100"]

    # mtime precisa avançar de fato; sistemas de arquivo comuns têm resolução
    # de 1s ou pior.
    novo_mtime = os.path.getmtime(caminho_movimento) + 2
    _escrever_csv(caminho_movimento, [_linha_movimento(CODIGO_PRODUTO="200", DESCRICAO_PRODUTO="novo")])
    os.utime(caminho_movimento, (novo_mtime, novo_mtime))

    df2 = cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
    assert df2["Código Interno"].tolist() == ["200"]


def test_parquet_corrompido_cai_para_csv(tmp_path):
    caminho_movimento, caminho_produto = _preparar_fonte(tmp_path)
    pasta_trabalho = tmp_path / "trabalho" / "Empresa"

    cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
    caminho_parquet = pasta_trabalho / cache_atacado.NOME_CACHE_PARQUET
    mtime_bom = os.path.getmtime(caminho_parquet)
    caminho_parquet.write_bytes(b"nao e parquet de verdade")
    os.utime(caminho_parquet, (mtime_bom, mtime_bom))

    df = cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
    assert df["Código Interno"].tolist() == ["100"]


def test_falha_ao_gravar_cache_nao_impede_carregamento(tmp_path):
    caminho_movimento, caminho_produto = _preparar_fonte(tmp_path)
    pasta_trabalho = tmp_path / "trabalho" / "Empresa"

    with patch.object(cache_atacado, "_gravar_cache", side_effect=OSError("disco cheio")):
        df = cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)

    assert df["Código Interno"].tolist() == ["100"]
    assert not (pasta_trabalho / cache_atacado.NOME_CACHE_PARQUET).exists()


def test_nunca_escreve_na_pasta_fonte(tmp_path):
    """Cache mora na pasta trabalho; a fonte usada no teste não pode ganhar arquivo novo."""
    caminho_movimento, caminho_produto = _preparar_fonte(tmp_path)
    pasta_fonte = caminho_movimento.parent
    pasta_trabalho = tmp_path / "trabalho" / "Empresa"

    antes = set(pasta_fonte.iterdir())
    cache_atacado.carregar_atacado_df_cacheado(caminho_movimento, caminho_produto, pasta_trabalho)
    depois = set(pasta_fonte.iterdir())

    assert antes == depois
