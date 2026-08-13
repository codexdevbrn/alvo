"""Fiação do menu da bandeja e degradação quando ela não está disponível.

O `pystray` real abre janela e bloqueia num laço de mensagens do Windows, então
aqui ele é substituído por um dublê que apenas registra o que foi montado e chama
os callbacks. O que estes testes protegem é a ordem das ações e o "degradar em vez
de morrer" — o resto (o shell aceitar o ícone) foi verificado rodando.
"""

import sys
import types

import pytest

import bandeja


class _IconeFalso:
    def __init__(self, nome, imagem, titulo, menu=None):
        self.nome = nome
        self.imagem = imagem
        self.titulo = titulo
        self.menu = menu
        self.parado = False
        self.rodou = False

    def run(self, setup=None):
        self.rodou = True
        if setup is not None:
            setup(self)

    def stop(self):
        self.parado = True


def _pystray_falso(monkeypatch, icone_classe=_IconeFalso):
    """Instala um módulo `pystray` de mentira e devolve a lista de ícones criados."""
    criados = []

    def fabricar(*args, **kwargs):
        icone = icone_classe(*args, **kwargs)
        criados.append(icone)
        return icone

    modulo = types.ModuleType("pystray")
    modulo.Icon = fabricar
    modulo.MenuItem = lambda rotulo, acao=None, **kw: types.SimpleNamespace(
        rotulo=rotulo, acao=acao, **kw
    )
    modulo.Menu = lambda *itens: list(itens)
    modulo.Menu.SEPARATOR = "---"
    monkeypatch.setitem(sys.modules, "pystray", modulo)
    monkeypatch.setattr(bandeja, "_carregar_icone", lambda: object())
    return criados


def _itens(icone):
    """Itens do menu, resolvendo o callable.

    O menu é montado como função, e não como lista, porque o pystray o reconstrói
    quando o usuário abre — é isso que faz o rótulo mostrar a versão disponível do
    momento em vez da do boot.
    """
    menu = icone.menu
    alvo = menu[0] if isinstance(menu, list) and len(menu) == 1 and callable(menu[0]) else menu
    return list(alvo() if callable(alvo) else alvo)


def _item(icone, rotulo):
    itens = _itens(icone)
    for it in itens:
        if getattr(it, "rotulo", None) == rotulo:
            return it
    raise AssertionError(f"item {rotulo!r} não está no menu: {itens}")


def test_menu_tem_os_tres_itens(monkeypatch):
    criados = _pystray_falso(monkeypatch)
    assert bandeja.executar("http://127.0.0.1:8004", ao_sair=lambda: None) is True
    rotulos = [getattr(i, "rotulo", i) for i in _itens(criados[0])]
    assert rotulos == ["Abrir Prisma", "Verificar atualização", "---", "Sair"]


def test_abrir_usa_a_url_do_servidor(monkeypatch):
    criados = _pystray_falso(monkeypatch)
    abertas = []
    monkeypatch.setattr(bandeja.webbrowser, "open", lambda u: abertas.append(u))
    bandeja.executar("http://127.0.0.1:8007", ao_sair=lambda: None)
    _item(criados[0], "Abrir Prisma").acao()
    assert abertas == ["http://127.0.0.1:8007"]


def test_verificar_leva_para_configuracoes(monkeypatch):
    """É lá que o resultado aparece e onde fica o botão de aplicar."""
    criados = _pystray_falso(monkeypatch)
    abertas = []
    monkeypatch.setattr(bandeja.webbrowser, "open", lambda u: abertas.append(u))
    chamou = []
    bandeja.executar(
        "http://127.0.0.1:8004",
        ao_sair=lambda: None,
        ao_verificar_atualizacao=lambda: chamou.append(True),
    )
    _item(criados[0], "Verificar atualização").acao()
    assert chamou == [True]
    assert abertas == ["http://127.0.0.1:8004/config"]


def test_sair_encerra_servidor_antes_de_remover_o_icone(monkeypatch):
    """Ordem importa: se o ícone sumisse primeiro, o usuário acharia que fechou
    enquanto o processo ainda estivesse servindo."""
    criados = _pystray_falso(monkeypatch)
    ordem = []
    bandeja.executar(
        "http://127.0.0.1:8004", ao_sair=lambda: ordem.append("servidor"),
    )
    icone = criados[0]

    class _Espia:
        def stop(self_):
            ordem.append("icone")

    _item(icone, "Sair").acao(_Espia())
    assert ordem == ["servidor", "icone"]


def test_sair_remove_o_icone_mesmo_se_encerrar_falhar(monkeypatch):
    """Sem o finally, uma exceção ao encerrar deixaria o ícone preso na bandeja."""
    criados = _pystray_falso(monkeypatch)

    def explodir():
        raise RuntimeError("falha ao encerrar")

    bandeja.executar("http://127.0.0.1:8004", ao_sair=explodir)
    parou = []

    class _Espia:
        def stop(self_):
            parou.append(True)

    with pytest.raises(RuntimeError):
        _item(criados[0], "Sair").acao(_Espia())
    assert parou == [True]


def test_sem_pystray_devolve_false(monkeypatch):
    """Sessão sem shell gráfico não pode impedir o servidor de subir."""
    def falhar(nome, *a, **kw):
        if nome == "pystray":
            raise ImportError("sem pystray")
        return __import__(nome, *a, **kw)

    monkeypatch.setattr("builtins.__import__", falhar)
    assert bandeja.executar("http://127.0.0.1:8004", ao_sair=lambda: None) is False


def test_sem_icone_devolve_false(monkeypatch):
    _pystray_falso(monkeypatch)
    monkeypatch.setattr(bandeja, "_carregar_icone", lambda: None)
    assert bandeja.executar("http://127.0.0.1:8004", ao_sair=lambda: None) is False


def test_falha_ao_criar_icone_devolve_false(monkeypatch):
    class _Explode:
        def __init__(self, *a, **kw):
            raise RuntimeError("shell indisponível")

    _pystray_falso(monkeypatch, icone_classe=_Explode)
    assert bandeja.executar("http://127.0.0.1:8004", ao_sair=lambda: None) is False


def test_rotulo_mostra_a_versao_quando_ha_atualizacao(monkeypatch):
    """O menu da bandeja é o único lugar onde o usuário do modo segundo plano olha
    sem abrir a interface — o rótulo precisa dizer que há versão nova."""
    criados = _pystray_falso(monkeypatch)
    bandeja.executar(
        "http://127.0.0.1:8004",
        ao_sair=lambda: None,
        versao_disponivel=lambda: "1.0.11",
    )
    rotulos = [getattr(i, "rotulo", i) for i in _itens(criados[0])]
    assert "Atualizar para 1.0.11" in rotulos
    assert "Verificar atualização" not in rotulos


def test_rotulo_generico_quando_nao_ha_atualizacao(monkeypatch):
    criados = _pystray_falso(monkeypatch)
    bandeja.executar(
        "http://127.0.0.1:8004", ao_sair=lambda: None, versao_disponivel=lambda: None,
    )
    rotulos = [getattr(i, "rotulo", i) for i in _itens(criados[0])]
    assert "Verificar atualização" in rotulos


def test_falha_ao_ler_versao_nao_derruba_o_menu(monkeypatch):
    """Se a consulta explodir, o menu ainda tem de abrir — é por ele que se sai do app."""
    criados = _pystray_falso(monkeypatch)

    def explodir():
        raise RuntimeError("cache indisponível")

    bandeja.executar(
        "http://127.0.0.1:8004", ao_sair=lambda: None, versao_disponivel=explodir,
    )
    rotulos = [getattr(i, "rotulo", i) for i in _itens(criados[0])]
    assert "Verificar atualização" in rotulos
    assert "Sair" in rotulos
