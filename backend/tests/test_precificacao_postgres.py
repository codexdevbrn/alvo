"""Assinatura que decide quem regerar, e a guarda de escrita do lote.

Nada aqui toca o Postgres: o que é testado é a comparação entre a assinatura do
banco e a do arquivo, que é o que evita reescrever empresa sem precificação nova.
"""

from pathlib import Path

import pandas as pd
import pytest

import main  # noqa: F401  (insere a raiz do projeto no sys.path)
import precificacao_postgres as pgp
from precificacao_do_postgres import (
    ErroLote,
    assinatura_arquivo,
    exigir_trabalho_fora_da_fonte,
    gravar_dump,
)

#: Como `assinaturas_por_cnpj` devolveria matriz e filial da mesma pasta.
POR_CNPJ = {
    "31263577000110": [
        {"dia": "2026-08-31", "linhas": 7643,
         "ultima": "2026-08-31T18:00:00.500000", "primeira": "2026-08-31T09:00:00.100000"},
        {"dia": "2026-08-28", "linhas": 885,
         "ultima": "2026-08-28T17:00:00", "primeira": "2026-08-28T08:00:00"},
    ],
    "31263577000209": [
        {"dia": "2026-09-02", "linhas": 652,
         "ultima": "2026-09-02T11:00:00", "primeira": "2026-09-02T10:00:00"},
    ],
}


def test_dobrar_assinatura_junta_matriz_e_filial():
    dobrada = pgp.dobrar_assinatura(POR_CNPJ, ["31263577000110", "31263577000209"])
    assert dobrada["linhas"] == 7643 + 885 + 652
    # O recorte de rodadas é por CNPJ, então os dias das duas entram juntos.
    assert dobrada["dias"] == ["2026-08-28", "2026-08-31", "2026-09-02"]
    assert dobrada["ultima"] == "2026-09-02T11:00:00"
    assert dobrada["primeira"] == "2026-08-28T08:00:00"


def test_dobrar_assinatura_aceita_cnpj_com_mascara():
    """O mapa é preenchido à mão; máscara não pode virar 'sem linha'."""
    dobrada = pgp.dobrar_assinatura(POR_CNPJ, ["31.263.577/0001-10"])
    assert dobrada is not None
    assert dobrada["linhas"] == 7643 + 885


def test_dobrar_assinatura_sem_linha_no_banco():
    assert pgp.dobrar_assinatura(POR_CNPJ, ["99999999999999"]) is None
    assert pgp.dobrar_assinatura(POR_CNPJ, []) is None


def _df_dump(timestamps: list[str]) -> pd.DataFrame:
    linhas = [
        {
            "cnpj": "01709513000139", "descricao": "Filtro Lubrificante",
            "codigo": "27043", "fabricante": "TECFIL",
            "margem_anterior": 33.19, "margem_alvo": 34.7,
            "receita": 589.59, "cmv": 393.9, "fx": "X2",
            "data_exportacao": ts, "markup_alvo": None,
            "preco_atual": None, "preco_sugerido": None, "variacao_pct": None,
        }
        for ts in timestamps
    ]
    df = pd.DataFrame(linhas, columns=list(pgp.COLUNAS_DUMP))
    df["data_exportacao"] = pd.to_datetime(df["data_exportacao"])
    return df


def test_assinatura_arquivo_preserva_microssegundo(tmp_path):
    """O microssegundo tem que sobreviver à gravação e à releitura.

    É o que faz o desvio funcionar: se a gravação truncasse o timestamp, a
    assinatura do arquivo nunca casaria com a do banco e toda empresa seria
    reescrita todo dia.
    """
    df = _df_dump([
        "2026-05-12 12:48:14.490185",
        "2026-05-12 12:48:14.167000",
        "2026-06-23 13:34:41.564461",
    ])
    gravar_dump(tmp_path, "IBAD", df)

    assinatura = assinatura_arquivo(tmp_path / "IBAD_PRECIFICACAO.parquet")
    assert assinatura == {
        "linhas": 3,
        "dias": ["2026-05-12", "2026-06-23"],
        "ultima": "2026-06-23T13:34:41.564461",
        "primeira": "2026-05-12T12:48:14.167000",
    }


def test_assinatura_arquivo_ausente_ou_ilegivel(tmp_path):
    assert assinatura_arquivo(tmp_path / "nao_existe.parquet") is None
    quebrado = tmp_path / "IBAD_PRECIFICACAO.parquet"
    quebrado.write_text("não é parquet", encoding="utf-8")
    assert assinatura_arquivo(quebrado) is None
    # Sem `data_exportacao` não há assinatura: o lote regera em vez de assumir igual.
    pd.DataFrame({"coluna_errada": [1]}).to_parquet(quebrado, index=False)
    assert assinatura_arquivo(quebrado) is None


def test_assinatura_muda_quando_o_recorte_muda(tmp_path):
    """Rodada a mais no recorte tem que diferir, mesmo com a última data igual."""
    tres = _df_dump([
        "2026-05-05 08:00:00.000001",
        "2026-05-12 12:48:14.490185",
        "2026-06-23 13:34:41.564461",
    ])
    duas = _df_dump([
        "2026-05-12 12:48:14.490185",
        "2026-06-23 13:34:41.564461",
    ])
    gravar_dump(tmp_path, "IBAD", tres)
    assinatura_tres = assinatura_arquivo(tmp_path / "IBAD_PRECIFICACAO.parquet")
    gravar_dump(tmp_path, "IBAD", duas)
    assinatura_duas = assinatura_arquivo(tmp_path / "IBAD_PRECIFICACAO.parquet")

    assert assinatura_tres["ultima"] == assinatura_duas["ultima"]
    assert assinatura_tres != assinatura_duas


def test_gravar_dump_nao_deixa_temporario(tmp_path):
    gravar_dump(tmp_path, "IBAD", _df_dump(["2026-05-12 12:48:14.490185"]))
    assert (tmp_path / "IBAD_PRECIFICACAO.parquet").is_file()
    assert not list(tmp_path.glob(".*tmp"))


def test_trabalho_nao_pode_ficar_sob_a_fonte(tmp_path):
    """A fonte é somente-leitura absoluta — o lote recusa antes de gravar."""
    fonte = tmp_path / "fonte"
    fonte.mkdir()
    with pytest.raises(ErroLote):
        exigir_trabalho_fora_da_fonte(fonte, fonte / "trabalho")
    with pytest.raises(ErroLote):
        exigir_trabalho_fora_da_fonte(fonte, fonte)
    with pytest.raises(ErroLote):
        exigir_trabalho_fora_da_fonte(tmp_path / "fonte" / "sub", tmp_path / "fonte")
    # Irmãs: liberado.
    exigir_trabalho_fora_da_fonte(fonte, tmp_path / "trabalho")


def test_colunas_dump_cobrem_o_que_o_leitor_exige():
    """O arquivo gerado tem que satisfazer `carregar_csv_precificacao`."""
    from engine import analise_funil as af

    faltando = set(af.COLUNAS_PRECIFICACAO_EMPRESA) - set(pgp.COLUNAS_DUMP)
    assert not faltando
    assert set(af.COLUNAS_PRECIFICACAO_OPCIONAIS) <= set(pgp.COLUNAS_DUMP)


def test_dump_gerado_e_lido_pelo_motor(tmp_path):
    """Ponta a ponta no formato: grava como o lote e lê como o app."""
    from engine import analise_funil as af

    gravar_dump(tmp_path, "IBAD", _df_dump(["2026-05-12 12:48:14.490185"]))
    lido = af.carregar_csv_precificacao(tmp_path / "IBAD_PRECIFICACAO.parquet")
    assert lido["cnpj"].iloc[0] == "01709513000139"  # zero à esquerda preservado
    assert lido["receita"].iloc[0] == pytest.approx(589.59)
    assert pd.isna(lido["preco_sugerido"].iloc[0])
