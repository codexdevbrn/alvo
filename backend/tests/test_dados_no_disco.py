"""Marcação de "sempre manter nesta máquina" (FILE_ATTRIBUTE_PINNED).

A API do Windows é dublada por um dicionário de atributos, para os testes rodarem
sem depender de uma pasta sincronizada pelo OneDrive. A mecânica real (marcar, ler
de volta, desmarcar) foi verificada nesta máquina numa pasta de teste.
"""

import os

import pytest

import dados_no_disco as d


@pytest.fixture
def atributos_falsos(monkeypatch):
    """Substitui Get/SetFileAttributesW por um dicionário caminho -> atributos."""
    tabela: dict[str, int] = {}

    monkeypatch.setattr(d, "_get_atributos", lambda c: tabela.get(os.path.normcase(c)))

    def definir(caminho, valor):
        tabela[os.path.normcase(caminho)] = valor
        return True

    monkeypatch.setattr(d, "_set_atributos", definir)
    monkeypatch.setattr(d, "suportado", lambda: True)
    return tabela


def _povoar(tmp_path, tabela, arquivos=("a.csv", "b.csv"), atributos=0):
    (tmp_path / "sub").mkdir()
    tabela[os.path.normcase(str(tmp_path))] = atributos
    tabela[os.path.normcase(str(tmp_path / "sub"))] = atributos
    for nome in arquivos:
        caminho = tmp_path / "sub" / nome
        caminho.write_text("x", encoding="utf-8")
        tabela[os.path.normcase(str(caminho))] = atributos
    return tmp_path


def test_fixar_liga_pinned_e_desliga_unpinned(tmp_path, atributos_falsos):
    _povoar(tmp_path, atributos_falsos, atributos=d.FILE_ATTRIBUTE_UNPINNED)
    d.aplicar(str(tmp_path), fixar=True)
    for valor in atributos_falsos.values():
        assert valor & d.FILE_ATTRIBUTE_PINNED
        assert not valor & d.FILE_ATTRIBUTE_UNPINNED


def test_liberar_faz_o_inverso(tmp_path, atributos_falsos):
    _povoar(tmp_path, atributos_falsos, atributos=d.FILE_ATTRIBUTE_PINNED)
    d.aplicar(str(tmp_path), fixar=False)
    for valor in atributos_falsos.values():
        assert valor & d.FILE_ATTRIBUTE_UNPINNED
        assert not valor & d.FILE_ATTRIBUTE_PINNED


def test_preserva_os_outros_atributos(tmp_path, atributos_falsos):
    """Sobrescrever o valor inteiro apagaria ReadOnly, Hidden, Archive."""
    ARCHIVE = 0x20
    _povoar(tmp_path, atributos_falsos, atributos=ARCHIVE)
    d.aplicar(str(tmp_path), fixar=True)
    for valor in atributos_falsos.values():
        assert valor & ARCHIVE, "atributo alheio foi perdido"


def test_marca_as_pastas_tambem(tmp_path, atributos_falsos):
    """Sem marcar a pasta, o que a coleta gravar amanhã nasce placeholder de novo."""
    _povoar(tmp_path, atributos_falsos)
    d.aplicar(str(tmp_path), fixar=True)
    assert atributos_falsos[os.path.normcase(str(tmp_path))] & d.FILE_ATTRIBUTE_PINNED
    assert atributos_falsos[os.path.normcase(str(tmp_path / "sub"))] & d.FILE_ATTRIBUTE_PINNED


def test_estado_conta_fixados_e_na_nuvem(tmp_path, atributos_falsos):
    _povoar(tmp_path, atributos_falsos, arquivos=("a.csv", "b.csv", "c.csv"))
    caminhos = sorted(k for k in atributos_falsos if k.endswith(".csv"))
    atributos_falsos[caminhos[0]] = d.FILE_ATTRIBUTE_PINNED
    atributos_falsos[caminhos[1]] = d.FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
    atributos_falsos[caminhos[2]] = 0

    e = d.estado(str(tmp_path))
    assert e["arquivos"] == 3
    assert e["fixados"] == 1
    assert e["na_nuvem"] == 1


def test_estado_ignora_pastas_na_contagem(tmp_path, atributos_falsos):
    """Pasta marcada não garante que o conteúdo desceu, e é o conteúdo que faz o
    usuário esperar."""
    _povoar(tmp_path, atributos_falsos, arquivos=("a.csv",))
    assert d.estado(str(tmp_path))["arquivos"] == 1


def test_estado_de_pasta_inexistente_nao_levanta(atributos_falsos):
    e = d.estado(r"C:\naoexiste\xyz")
    assert e["arquivos"] == 0
    assert e["suportado"] is True


def test_estado_sem_caminho(atributos_falsos):
    assert d.estado(None)["arquivos"] == 0


def test_aplicar_em_pasta_inexistente_recusa(atributos_falsos):
    with pytest.raises(d.ErroDadosNoDisco, match="inacessível"):
        d.aplicar(r"C:\naoexiste\xyz", fixar=True)


def test_fora_do_windows_recusa(monkeypatch):
    monkeypatch.setattr(d, "suportado", lambda: False)
    with pytest.raises(d.ErroDadosNoDisco, match="Windows"):
        d.aplicar("qualquer", fixar=True)
    assert d.estado("qualquer")["suportado"] is False


def test_falha_total_levanta(tmp_path, monkeypatch, atributos_falsos):
    """Nenhum item alterado provavelmente significa pasta fora do OneDrive; dizer
    isso é melhor que reportar sucesso silencioso."""
    _povoar(tmp_path, atributos_falsos)
    monkeypatch.setattr(d, "_marcar", lambda c, f: False)
    with pytest.raises(d.ErroDadosNoDisco, match="OneDrive"):
        d.aplicar(str(tmp_path), fixar=True)
