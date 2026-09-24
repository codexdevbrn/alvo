"""Base empresa / loja / CNPJ a partir do `{empresa}_EMPRESA.dw_2d` do DW."""

from pathlib import Path

import main  # noqa: F401  (insere a raiz do projeto no sys.path)
import base_empresas as be
from precificacao_do_postgres import resolver_cnpjs

CABECALHO = '"ID_LOJA";"CNPJ";"NOME";"CEP";"TIPO_TRIBUTACAO";"DSN";"LINHAS_VAL";"LINHAS_INDEX";"DATA_ATT"'


def _arquivo(dw: Path, empresa: str, linhas: list[str], cabecalho: str = CABECALHO) -> None:
    pasta = dw / empresa / "BI"
    pasta.mkdir(parents=True)
    (pasta / f"{empresa}_EMPRESA.dw_2d").write_text(
        "\n".join([cabecalho, *linhas]) + "\n", encoding="utf-8-sig",
    )


def test_le_lojas_e_normaliza_cnpj(tmp_path):
    _arquivo(tmp_path, "IBAD", [
        '"ibad_dc";"01709513000139";"IBAD (DC)";"25070-070";"lp";"ibad_dc";"1";"1";"23/09/2026 03:26:12"',
        '"ibad_ilha";"01.709.513/0004-81";"IBAD (ILHA)";"21920-000";"lp";"ibad_ilha";"1";"1";"18/09/2026"',
    ])
    df = be.ler_arquivo_empresa(be.caminho_arquivo_empresa(tmp_path, "IBAD"), "IBAD")
    assert df["id_loja"].tolist() == ["ibad_dc", "ibad_ilha"]
    assert df["cnpj"].tolist() == ["01709513000139", "01709513000481"]  # zero à esquerda e máscara
    assert set(df["empresa"]) == {"IBAD"}


def test_empresa_sem_coluna_cnpj_entra_com_aviso(tmp_path):
    """A Cativo exporta só as lojas: elas entram, com CNPJ vazio e aviso."""
    _arquivo(tmp_path, "Cativo", [
        '"                   ";"cativo";"6";"1";"21/09/2026"',
        '"Cativo Matriz RJ   ";"cativo";"6";"4";"21/09/2026"',
    ], cabecalho='"ID_LOJA";"DSN";"LINHAS_VAL";"LINHAS_INDEX";"DATA_ATT"')
    base, avisos = be.montar_base(tmp_path, ["Cativo"])
    assert base["id_loja"].tolist() == ["Cativo Matriz RJ"]  # linha em branco some
    assert base["cnpj"].tolist() == [""]
    assert any("sem CNPJ" in a for a in avisos)
    assert be.cnpjs_por_empresa(base) == {}


def test_empresa_sem_arquivo_vira_aviso_e_as_outras_seguem(tmp_path):
    _arquivo(tmp_path, "GAP", ['"gap";"10481020000185";"GAP";"";"sn";"gap";"1";"1";""'])
    base, avisos = be.montar_base(tmp_path, ["GAP", "Fantasma"])
    assert be.cnpjs_por_empresa(base) == {"GAP": ["10481020000185"]}
    assert any(a.startswith("Fantasma:") for a in avisos)


def test_grava_e_recarrega(tmp_path):
    _arquivo(tmp_path / "dw", "Lupi", [
        '"lupi_1";"40384356000190";"LUPI";"";"lp";"x";"1";"1";""',
        '"lupi_2";"40384356000190";"LUPI 2";"";"lp";"x";"1";"1";""',
        '"lupi_3";"17764646000148";"PIERONI";"";"lp";"x";"1";"1";""',
    ])
    base, _ = be.montar_base(tmp_path / "dw", ["Lupi"])
    trabalho = tmp_path / "trabalho"
    trabalho.mkdir()
    be.gravar_base(base, trabalho)
    assert not list(trabalho.glob(".*tmp"))
    relida = be.carregar_base(trabalho)
    # Duas lojas no mesmo CNPJ: o CNPJ aparece uma vez só.
    assert be.cnpjs_por_empresa(relida) == {"Lupi": ["17764646000148", "40384356000190"]}


def test_base_ausente_devolve_vazia(tmp_path):
    assert be.carregar_base(tmp_path).empty
    assert be.carregar_base(None).empty


def test_lote_prefere_base_do_dw_ao_mapa_manual():
    base = {"IBAD": ["01709513000139", "07883453000233"]}
    mapa = {"IBAD": ["01709513000139"], "Cativo": ["99999999000199"]}
    assert resolver_cnpjs("IBAD", mapa, base) == (["01709513000139", "07883453000233"], "base DW")
    # Empresa que o DW não cobre cai no mapa manual.
    assert resolver_cnpjs("Cativo", mapa, base) == (["99999999000199"], "mapa")
    assert resolver_cnpjs("Nenhuma", mapa, base) == ([], "sem mapa")


def test_incremental_so_busca_empresa_nova_e_tira_quem_saiu(tmp_path):
    dw = tmp_path / "dw"
    _arquivo(dw, "GAP", ['"gap";"10481020000185";"GAP";"";"sn";"x";"1";"1";""'])
    _arquivo(dw, "Tadeu", ['"tadeu";"02983455000108";"TADEU";"";"lp";"x";"1";"1";""'])
    atual, _ = be.montar_base(dw, ["GAP", "Antiga"])
    # "Antiga" nem tem arquivo; simula que já estava no mapa salvo.
    atual.loc[len(atual)] = ["Antiga", "a1", "11111111000111", "", "", "", ""]
    # O DW da GAP mudou depois de mapeada: o incremental não relê quem já está.
    (dw / "GAP" / "BI" / "GAP_EMPRESA.dw_2d").unlink()

    base, novas, removidas, avisos = be.atualizar_base(atual, dw, ["GAP", "Tadeu", "Nova Sem DW"])

    assert novas == ["Tadeu"]
    assert removidas == ["Antiga"]
    assert be.cnpjs_por_empresa(base) == {"GAP": ["10481020000185"], "Tadeu": ["02983455000108"]}
    # Empresa nova sem arquivo não entra, e fica para a próxima tentativa.
    assert "Nova Sem DW" not in set(base["empresa"])
    assert any(a.startswith("Nova Sem DW:") for a in avisos)


def test_incremental_com_mapa_vazio_monta_tudo(tmp_path):
    _arquivo(tmp_path, "GAP", ['"gap";"10481020000185";"GAP";"";"sn";"x";"1";"1";""'])
    vazio = be.carregar_base(tmp_path / "sem_base")
    base, novas, removidas, _ = be.atualizar_base(vazio, tmp_path, ["GAP"])
    assert novas == ["GAP"] and removidas == []
    assert len(base) == 1


def test_complemento_preenche_cnpj_vazio_e_nao_sobrescreve_o_dw(tmp_path):
    _arquivo(tmp_path, "Cativo", ['"Cativo Matriz RJ   ";"cativo";"6";"4";""'],
             cabecalho='"ID_LOJA";"DSN";"LINHAS_VAL";"LINHAS_INDEX";"DATA_ATT"')
    _arquivo(tmp_path, "GAP", ['"gap";"10481020000185";"GAP";"";"sn";"x";"1";"1";""'])
    base, _ = be.montar_base(tmp_path, ["Cativo", "GAP"])
    complemento = {
        "Cativo": {"cativo matriz rj": "05.154.197/0001-37", "Ecocity Solar": "08.348.589/0001-25"},
        "GAP": {"gap": "99999999000199"},        # DW já tem CNPJ: não troca
        "Fora da fonte": {"x": "11111111000111"},  # empresa que não está na Dados Alvos: ignora
    }
    base, mudancas = be.aplicar_complemento(base, complemento, ["Cativo", "GAP"])
    assert be.cnpjs_por_empresa(base) == {
        "Cativo": ["05154197000137", "08348589000125"],
        "GAP": ["10481020000185"],
    }
    assert len(mudancas) == 2
