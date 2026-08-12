"""Validação de horário, leitura do XML da tarefa e disponibilidade.

O que toca registro e Agendador de verdade foi verificado à mão nesta máquina
(criando e removendo entradas de teste); aqui ficam as partes puras, que são as
que erram silenciosamente.
"""

import subprocess

import pytest

import inicio_automatico as ia


@pytest.mark.parametrize("entrada,esperado", [
    ("08:30", "08:30"),
    ("8:5", "08:05"),
    (" 23:59 ", "23:59"),
    ("00:00", "00:00"),
])
def test_horarios_validos_sao_normalizados(entrada, esperado):
    assert ia.validar_horario(entrada) == esperado


@pytest.mark.parametrize("entrada", ["24:00", "08:60", "-1:00", "8h30", "0830", "", "8:", ":30", "08:30:00"])
def test_horarios_invalidos_sao_recusados(entrada):
    """O schtasks aceita entrada estranha e só falha depois, com mensagem própria
    dele — validar antes dá erro que o usuário entende."""
    with pytest.raises(ia.ErroInicioAutomatico):
        ia.validar_horario(entrada)


def test_le_horario_do_xml_ignorando_namespace(monkeypatch):
    """O XML do Agendador vem com namespace, e o rótulo da hora na saída em lista é
    traduzido — por isso a leitura é pelo XML e pelo nome local da tag."""
    xml = (
        '<?xml version="1.0" encoding="UTF-16"?>'
        '<Task xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">'
        "<Triggers><CalendarTrigger>"
        "<StartBoundary>2026-08-12T08:30:00</StartBoundary>"
        "<ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>"
        "</CalendarTrigger></Triggers></Task>"
    )
    monkeypatch.setattr(
        ia, "_schtasks",
        lambda *a: subprocess.CompletedProcess(a, 0, stdout=xml, stderr=""),
    )
    assert ia.horario_agendado() == "08:30"


def test_sem_tarefa_devolve_none(monkeypatch):
    monkeypatch.setattr(
        ia, "_schtasks",
        lambda *a: subprocess.CompletedProcess(a, 1, stdout="", stderr="não encontrada"),
    )
    assert ia.horario_agendado() is None


def test_xml_ilegivel_devolve_none(monkeypatch):
    monkeypatch.setattr(
        ia, "_schtasks",
        lambda *a: subprocess.CompletedProcess(a, 0, stdout="<isso nao fecha", stderr=""),
    )
    assert ia.horario_agendado() is None


def test_xml_sem_gatilho_devolve_none(monkeypatch):
    xml = '<Task xmlns="http://x"><Triggers/></Task>'
    monkeypatch.setattr(
        ia, "_schtasks",
        lambda *a: subprocess.CompletedProcess(a, 0, stdout=xml, stderr=""),
    )
    assert ia.horario_agendado() is None


def test_indisponivel_fora_do_executavel(monkeypatch):
    """Do fonte, o comando seria um interpretador e um diretório que podem mudar;
    agendar isso criaria uma entrada que quebra sem ninguém entender."""
    monkeypatch.setattr(ia.sys, "frozen", False, raising=False)
    estado = ia.estado()
    assert estado["disponivel"] is False
    assert estado["logon"] is False
    assert estado["horario"] is None
    assert "instalada" in estado["motivo"]


def test_comando_do_registro_vem_entre_aspas(monkeypatch):
    """O caminho de instalação tem espaço em quase toda máquina
    (AppData\\Local\\Prisma); sem aspas o Windows tentaria executar "C:\\Users\\...\\AppData"."""
    monkeypatch.setattr(ia, "caminho_executavel", lambda: r"C:\Users\a b\Prisma\Prisma.exe")
    comando = ia._comando_registro()
    assert comando.startswith('"') and comando.endswith('"')


def test_criar_tarefa_propaga_erro_do_schtasks(monkeypatch):
    monkeypatch.setattr(
        ia, "_schtasks",
        lambda *a: subprocess.CompletedProcess(a, 1, stdout="", stderr="ERRO: acesso negado"),
    )
    with pytest.raises(ia.ErroInicioAutomatico, match="acesso negado"):
        ia.definir_horario("08:30")


def test_remover_tarefa_inexistente_nao_levanta(monkeypatch):
    """Remover o que não existe é sucesso para quem chamou."""
    monkeypatch.setattr(
        ia, "_schtasks",
        lambda *a: subprocess.CompletedProcess(a, 1, stdout="", stderr="não encontrada"),
    )
    ia.definir_horario(None)
