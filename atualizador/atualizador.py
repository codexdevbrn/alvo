"""
Atualizador do Prisma: troca os arquivos da instalação e religa o app.

Existe como executável separado por uma limitação do Windows — um binário em uso
não pode sobrescrever a si mesmo. Também é de propósito um programa mínimo, sem
pandas nem FastAPI: ele precisa subir em instantes e não pode falhar por causa de
uma dependência do app que está justamente sendo substituída.

Uso (quem chama é POST /api/atualizacoes/aplicar):

    atualizador.exe --pid <pid> --zip <pacote.zip> --destino <pasta>
        --versao 1.0.1 --versao-anterior 1.0.0

Sequência, com rollback em qualquer tropeço depois da troca:

    espera o pid morrer -> extrai ao lado -> preserva dados -> troca as pastas
    -> religa -> confirma que respondeu -> apaga o backup

Nunca apaga o backup antes de confirmar que a versão nova respondeu: o pior
resultado possível seria deixar a máquina sem Prisma nenhum.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import zipfile

NOME_EXECUTAVEL = "Prisma.exe"

# Preservados na troca: são dados do usuário ou desta instalação, não código.
# app.db em especial guarda o login e os caminhos fonte/trabalho — perder isso
# obrigaria a reconfigurar tudo a cada atualização, que é o oposto do objetivo.
ITENS_PRESERVADOS = (
    "dados_locais",
    "logs",
    "data",
    "base_de_dados.xlsx",
)

SEGUNDOS_ESPERANDO_PID = 60
SEGUNDOS_ESPERANDO_SUBIR = 90
INTERVALO = 0.5
PORTAS_PROVAVEIS = range(8003, 8013)


def _caminho_log(destino: str) -> str:
    """Log fora da pasta que vai ser trocada.

    Gravar dentro de `destino` significaria escrever num diretório que está sendo
    renomeado no meio da operação — justamente quando o registro é mais útil.
    """
    pai = os.path.dirname(os.path.abspath(destino))
    return os.path.join(pai, "Prisma-atualizacao.log")


class Registro:
    def __init__(self, caminho: str):
        self.caminho = caminho

    def __call__(self, mensagem: str) -> None:
        linha = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {mensagem}"
        print(linha)
        try:
            with open(self.caminho, "a", encoding="utf-8") as arquivo:
                arquivo.write(linha + "\n")
        except OSError:
            # Um log inacessível não pode abortar uma atualização em andamento.
            pass


def _processo_vivo(pid: int) -> bool:
    if sys.platform == "win32":
        saida = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, check=False,
        ).stdout
        return str(pid) in saida
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def esperar_pid_morrer(pid: int, log: Registro) -> bool:
    log(f"Esperando o Prisma (pid {pid}) encerrar.")
    limite = int(SEGUNDOS_ESPERANDO_PID / INTERVALO)
    for _ in range(limite):
        if not _processo_vivo(pid):
            log("Processo encerrado.")
            return True
        time.sleep(INTERVALO)
    log(f"O processo {pid} não encerrou em {SEGUNDOS_ESPERANDO_PID}s. Abortando.")
    return False


def _versoes_no_ar() -> set[str]:
    """Versões de todos os Prisma que respondem nas portas prováveis.

    Devolve o conjunto, e não a primeira encontrada, porque pode haver mais de uma
    instância na máquina e o chamador precisa saber se a SUA está entre elas.
    """
    versoes = set()
    for porta in PORTAS_PROVAVEIS:
        try:
            with urllib.request.urlopen(  # noqa: S310 (localhost)
                f"http://127.0.0.1:{porta}/api/versao", timeout=1
            ) as resposta:
                dados = json.load(resposta)
            if dados.get("app") == "Prisma":
                versoes.add(str(dados.get("versao", "")))
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return versoes


def religar(destino: str, log: Registro, versao_esperada: str = "") -> bool:
    """Sobe o Prisma de `destino` e confirma que foi ELE que atendeu.

    A confirmação é dupla de propósito. Aceitar "algum Prisma respondeu" seria
    perigoso: a máquina pode ter outra instância no ar — a instalação servida pelo
    Apache atende na 8003 — e aí uma versão nova que não sobe passaria por
    sucesso, o backup seria apagado e sobraria uma instalação quebrada sem volta.
    Por isso exige-se que o processo lançado continue vivo e, quando a versão
    esperada é conhecida, que ela esteja entre as que responderam.
    """
    executavel = os.path.join(destino, NOME_EXECUTAVEL)
    if not os.path.isfile(executavel):
        log(f"{NOME_EXECUTAVEL} não está em {destino}.")
        return False
    alvo = f" (esperando {versao_esperada})" if versao_esperada else ""
    log(f"Religando {executavel}{alvo}.")
    try:
        processo = subprocess.Popen(
            [executavel], cwd=destino, close_fds=True,
            # CREATE_NEW_CONSOLE, e não DETACHED_PROCESS: o Prisma é uma aplicação
            # de console e DETACHED_PROCESS a deixa sem console nenhum, o que mata
            # o bootloader do PyInstaller antes de o servidor subir. Além de
            # corrigir isso, a janela nova é a interface do app ("mantenha esta
            # janela aberta"), e ela sobrevive à morte deste atualizador.
            creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        )
    except OSError as exc:
        log(f"Falha ao religar: {exc}")
        return False

    for _ in range(int(SEGUNDOS_ESPERANDO_SUBIR / INTERVALO)):
        if processo.poll() is not None:
            log(f"O processo do Prisma encerrou sozinho (código {processo.returncode}).")
            return False
        versoes = _versoes_no_ar()
        if versao_esperada and versao_esperada in versoes:
            log(f"Prisma respondeu, versão {versao_esperada}.")
            return True
        if not versao_esperada and versoes:
            # Religamento de rollback: não há versão nova a exigir, e o processo
            # lançado continua vivo, então responder já basta.
            log(f"Prisma respondeu ({', '.join(sorted(versoes))}).")
            return True
        if versoes:
            # Alguém respondeu, mas não é a versão recém-instalada: provavelmente
            # outra instância. Segue esperando a certa em vez de dar sucesso.
            log(f"Respondeu {', '.join(sorted(versoes))} — ainda não {versao_esperada}.")
        time.sleep(INTERVALO)
    log(f"O Prisma não respondeu em {SEGUNDOS_ESPERANDO_SUBIR}s.")
    return False


def religar_versao_anterior(destino: str, log: Registro, versao_anterior: str) -> bool:
    """Religa rollback sem aceitar outra instância do Prisma como sucesso.

    A máquina pode ter builds de teste em outras portas. Sem a versão esperada,
    qualquer um deles faria o atualizador declarar rollback concluído enquanto
    o executável realmente restaurado já tivesse encerrado ou sido bloqueado.
    """
    if not versao_anterior:
        log("Versão anterior desconhecida; rollback não pode ser confirmado com segurança.")
        return False
    return religar(destino, log, versao_esperada=versao_anterior)


def _remover(caminho: str, log: Registro) -> None:
    if not os.path.exists(caminho):
        return
    log(f"Removendo {caminho}.")
    shutil.rmtree(caminho, ignore_errors=True)


def _preservar(origem: str, destino: str, log: Registro) -> None:
    """Copia os dados da instalação antiga para a nova."""
    for item in ITENS_PRESERVADOS:
        de = os.path.join(origem, item)
        para = os.path.join(destino, item)
        if not os.path.exists(de):
            continue
        # A versão nova pode trazer o mesmo nome; o dado do usuário manda.
        if os.path.isdir(de):
            if os.path.exists(para):
                shutil.rmtree(para, ignore_errors=True)
            shutil.copytree(de, para)
        else:
            shutil.copy2(de, para)
        log(f"Preservado: {item}")


def aplicar(
    pid: int,
    zip_pacote: str,
    destino: str,
    versao: str,
    versao_anterior: str,
    log: Registro,
) -> int:
    destino = os.path.abspath(destino)
    novo = destino + "_novo"
    backup = destino + "_backup"

    if not os.path.isfile(zip_pacote):
        log(f"Pacote não encontrado: {zip_pacote}")
        return 2
    if not os.path.isdir(destino):
        log(f"Instalação não encontrada: {destino}")
        return 2
    if not esperar_pid_morrer(pid, log):
        return 3

    _remover(novo, log)
    log(f"Extraindo {zip_pacote} em {novo}.")
    try:
        with zipfile.ZipFile(zip_pacote) as pacote:
            pacote.extractall(novo)
    except (OSError, zipfile.BadZipFile) as exc:
        # Nada foi trocado ainda: a instalação atual segue intacta. Religar aqui
        # devolve o usuário à versão antiga funcionando.
        log(f"Pacote inválido ({exc}). Nada foi alterado; religando a versão atual.")
        _remover(novo, log)
        religar_versao_anterior(destino, log, versao_anterior)
        return 4

    if not os.path.isfile(os.path.join(novo, NOME_EXECUTAVEL)):
        log(f"O pacote não contém {NOME_EXECUTAVEL}. Nada foi alterado.")
        _remover(novo, log)
        religar_versao_anterior(destino, log, versao_anterior)
        return 4

    try:
        _preservar(destino, novo, log)
    except OSError as exc:
        log(f"Falha ao preservar dados ({exc}). Nada foi trocado; religando a versão atual.")
        _remover(novo, log)
        religar_versao_anterior(destino, log, versao_anterior)
        return 5

    _remover(backup, log)
    log(f"Trocando: {destino} -> {backup}, {novo} -> {destino}")
    try:
        os.rename(destino, backup)
    except OSError as exc:
        log(f"Não foi possível mover a instalação atual ({exc}). Nada foi trocado.")
        _remover(novo, log)
        religar_versao_anterior(destino, log, versao_anterior)
        return 6
    try:
        os.rename(novo, destino)
    except OSError as exc:
        log(f"Falha ao pôr a versão nova no lugar ({exc}). Desfazendo.")
        os.rename(backup, destino)
        _remover(novo, log)
        religar_versao_anterior(destino, log, versao_anterior)
        return 6

    if religar(destino, log, versao_esperada=versao):
        log(f"Atualização para {versao or 'a nova versão'} concluída.")
        _remover(backup, log)
        return 0

    log("A versão nova não subiu. Voltando para a anterior.")
    try:
        _remover(novo, log)
        os.rename(destino, novo)
        os.rename(backup, destino)
    except OSError as exc:
        # Estado ruim de verdade: as pastas ficaram no meio do caminho. O log é a
        # única pista que sobra, então precisa dizer exatamente o que restaurar.
        log(
            f"ROLLBACK FALHOU ({exc}). Restaure manualmente: renomeie "
            f"'{backup}' de volta para '{destino}'."
        )
        return 7
    if religar_versao_anterior(destino, log, versao_anterior):
        log(f"Rollback concluído: versão {versao_anterior} está no ar.")
        return 7
    log(
        "ROLLBACK RESTAUROU OS ARQUIVOS, MAS O PRISMA NÃO SUBIU. "
        "Verifique antivírus e reinstale a última versão válida."
    )
    return 8


def _reconectar_console() -> None:
    """Religa stdout/stderr ao console que este processo recebeu.

    O Prisma lança o atualizador com as saídas em DEVNULL — obrigatório, porque
    depois de fechar o próprio console ele não tem handles válidos para repassar.
    Consequência: sem isto a janela do atualizador ficaria em branco enquanto ele
    troca os arquivos, e é justamente a janela que o usuário olha para saber que a
    atualização está andando.
    """
    if sys.platform != "win32":
        return
    for nome, fluxo in (("stdout", sys.stdout), ("stderr", sys.stderr)):
        try:
            if fluxo is not None and fluxo.isatty():
                continue
        except (OSError, ValueError):
            pass
        try:
            setattr(sys, nome, open("CONOUT$", "w", encoding="utf-8", buffering=1))
        except OSError:
            # Sem console (ex.: rodado por um agendador): o log em arquivo basta.
            pass


def main() -> int:
    _reconectar_console()
    analisador = argparse.ArgumentParser(description="Atualizador do Prisma.")
    analisador.add_argument("--pid", type=int, required=True)
    analisador.add_argument("--zip", dest="zip_pacote", required=True)
    analisador.add_argument("--destino", required=True)
    analisador.add_argument("--versao", default="")
    analisador.add_argument("--versao-anterior", required=True)
    args = analisador.parse_args()

    log = Registro(_caminho_log(args.destino))
    log("=" * 70)
    log(f"Atualizador iniciado. destino={args.destino} versao={args.versao or '?'}")
    try:
        codigo = aplicar(
            args.pid,
            args.zip_pacote,
            args.destino,
            args.versao,
            args.versao_anterior,
            log,
        )
    except Exception as exc:  # noqa: BLE001 - último recurso: registrar e sair
        log(f"Erro inesperado: {exc!r}")
        codigo = 1
    finally:
        # Limpa o temporário com o pacote. A cópia deste próprio executável mora
        # na mesma pasta (o Prisma a põe ali para não travar a instalação que vai
        # ser trocada), e o Windows não deixa apagar um binário em execução —
        # então o zip vai embora e o exe fica, para o %TEMP% do Windows recolher
        # depois. Autoexcluir-se exigiria um terceiro processo, o que é caro
        # demais para ~10 MB.
        shutil.rmtree(os.path.dirname(args.zip_pacote), ignore_errors=True)
    log(f"Atualizador encerrado com código {codigo}.")
    return codigo


if __name__ == "__main__":
    sys.exit(main())
