"""Resolução dos caminhos padrão a partir do OneDrive corporativo.

Os testes montam uma árvore falsa em tmp_path e apontam as variáveis de ambiente
para ela, para não depender do OneDrive real da máquina que roda os testes.
"""

import os

import caminhos_padrao


def _montar_onedrive(raiz, subpastas=("Dados Alvos", "analisador", os.path.join("Prisma", "Atualizações"))):
    """Cria `OneDrive - <dominio>/01 - Marco + Monitores/Ecossistema-Monitoria/...`."""
    onedrive = raiz / f"OneDrive - {caminhos_padrao.SUFIXO_ONEDRIVE_EMPRESA}"
    base = onedrive / caminhos_padrao.RAIZ_ECOSSISTEMA
    for sub in subpastas:
        (base / sub).mkdir(parents=True, exist_ok=True)
    return onedrive


def _limpar_ambiente(monkeypatch):
    for variavel in ("OneDriveCommercial", "OneDrive", "USERPROFILE"):
        monkeypatch.delenv(variavel, raising=False)


def test_usa_onedrive_commercial(tmp_path, monkeypatch):
    onedrive = _montar_onedrive(tmp_path)
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("OneDriveCommercial", str(onedrive))
    assert caminhos_padrao.raiz_onedrive_empresa() == str(onedrive)


def test_ignora_onedrive_pessoal(tmp_path, monkeypatch):
    """A variável `OneDrive` pode apontar para a conta pessoal. Usar aquela pasta
    faria o app procurar os dados da empresa no OneDrive de casa do usuário."""
    onedrive = _montar_onedrive(tmp_path)
    pessoal = tmp_path / "OneDrive"
    pessoal.mkdir()
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("OneDrive", str(pessoal))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    # Cai na varredura do perfil e acha a pasta corporativa, não a pessoal.
    assert caminhos_padrao.raiz_onedrive_empresa() == str(onedrive)


def test_varre_o_perfil_quando_nao_ha_variavel(tmp_path, monkeypatch):
    """Cobre processo iniciado fora da sessão interativa (ex.: tarefa agendada),
    onde o cliente do OneDrive não exportou as variáveis."""
    onedrive = _montar_onedrive(tmp_path)
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert caminhos_padrao.raiz_onedrive_empresa() == str(onedrive)


def test_sem_onedrive_nenhum(tmp_path, monkeypatch):
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    assert caminhos_padrao.raiz_onedrive_empresa() is None
    assert caminhos_padrao.fonte_dados() is None
    assert caminhos_padrao.trabalho() is None
    assert caminhos_padrao.atualizacoes() is None


def test_tres_caminhos_resolvidos(tmp_path, monkeypatch):
    onedrive = _montar_onedrive(tmp_path)
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("OneDriveCommercial", str(onedrive))
    base = os.path.join(str(onedrive), caminhos_padrao.RAIZ_ECOSSISTEMA)
    assert caminhos_padrao.fonte_dados() == os.path.join(base, "Dados Alvos")
    assert caminhos_padrao.trabalho() == os.path.join(base, "analisador")
    assert caminhos_padrao.atualizacoes() == os.path.join(base, "Prisma", "Atualizações")


def test_fonte_e_trabalho_nunca_coincidem(tmp_path, monkeypatch):
    """Invariante do projeto: o app recusa fonte == trabalho ou uma dentro da
    outra. Se os padrões violassem isso, toda instalação nova nasceria travada."""
    onedrive = _montar_onedrive(tmp_path)
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("OneDriveCommercial", str(onedrive))
    fonte = caminhos_padrao.fonte_dados()
    trab = caminhos_padrao.trabalho()
    assert fonte != trab
    assert not fonte.startswith(trab + os.sep)
    assert not trab.startswith(fonte + os.sep)


def test_subpasta_ausente_nao_e_sugerida(tmp_path, monkeypatch):
    """Devolver pasta inexistente faria o app falhar ao ler em vez de dizer que
    não está configurado."""
    onedrive = _montar_onedrive(tmp_path, subpastas=("Dados Alvos",))
    _limpar_ambiente(monkeypatch)
    monkeypatch.setenv("OneDriveCommercial", str(onedrive))
    assert caminhos_padrao.fonte_dados() is not None
    assert caminhos_padrao.trabalho() is None
    assert caminhos_padrao.atualizacoes() is None
