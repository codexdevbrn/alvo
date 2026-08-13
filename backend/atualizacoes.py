"""
Canal de atualização: uma pasta compartilhada (na prática o OneDrive da empresa,
o mesmo lugar de onde já vêm os dados) contendo

    version.json          metadados da release publicada
    Prisma-<versao>.zip   o pacote

O `version.json` é escrito por `build.ps1`:

    {"versao": "1.0.1", "arquivo": "Prisma-1.0.1.zip",
     "sha256": "...", "tamanho": 73400320, "data": "2026-08-12", "notas": "..."}

Nada aqui levanta exceção para o chamador: canal não configurado, pasta fora do
ar, JSON quebrado e zip pela metade são estados normais de operação e viram um
`motivo` legível. Um erro no canal não pode derrubar o app — o usuário está ali
para trabalhar, não para atualizar.
"""

import hashlib
import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from versao import VERSAO, versao_mais_nova

NOME_ARQUIVO_MANIFESTO = "version.json"

# O sha256 é lido em blocos porque o pacote tem dezenas de MB: ler tudo de uma
# vez para memória só para conferir o hash é desperdício.
BLOCO_LEITURA = 1024 * 1024


@dataclass
class StatusAtualizacao:
    """O que a interface precisa saber sobre o canal, num objeto só."""

    versao_atual: str = VERSAO
    versao_disponivel: Optional[str] = None
    atualizavel: bool = False
    motivo: str = ""
    notas: str = ""
    data: str = ""
    caminho_pacote: Optional[str] = None
    detalhes: dict = field(default_factory=dict)

    def como_dicionario(self) -> dict:
        return {
            "versao_atual": self.versao_atual,
            "versao_disponivel": self.versao_disponivel,
            "atualizavel": self.atualizavel,
            "motivo": self.motivo,
            "notas": self.notas,
            "data": self.data,
        }


def sha256_do_arquivo(caminho: str) -> str:
    digest = hashlib.sha256()
    with open(caminho, "rb") as arquivo:
        for bloco in iter(lambda: arquivo.read(BLOCO_LEITURA), b""):
            digest.update(bloco)
    return digest.hexdigest()


def _subpasta_com_manifesto(canal: str) -> Optional[str]:
    r"""Nome da subpasta imediata que tem o manifesto, se houver.

    Serve para uma confusão real: a pasta que o usuário navega até (`...\Prisma`)
    contém o instalador, e o canal é a subpasta (`...\Prisma\Atualizações`).
    Apontar o erro com o caminho certo é mais útil que só dizer que falta o arquivo.
    """
    try:
        entradas = os.listdir(canal)
    except OSError:
        return None
    for nome in sorted(entradas):
        sub = os.path.join(canal, nome)
        if os.path.isdir(sub) and os.path.isfile(os.path.join(sub, NOME_ARQUIVO_MANIFESTO)):
            return nome
    return None


def _ler_manifesto(canal: str) -> tuple[Optional[dict], str]:
    """`(manifesto, motivo_do_erro)` — exatamente um dos dois vem preenchido."""
    caminho = os.path.join(canal, NOME_ARQUIVO_MANIFESTO)
    if not os.path.isfile(caminho):
        sub = _subpasta_com_manifesto(canal)
        if sub:
            return None, (
                f"Esta pasta não tem {NOME_ARQUIVO_MANIFESTO}, mas a subpasta "
                f"\"{sub}\" tem. Aponte o canal para ela."
            )
        return None, f"O canal não tem {NOME_ARQUIVO_MANIFESTO}."
    try:
        with open(caminho, "r", encoding="utf-8") as arquivo:
            manifesto = json.load(arquivo)
    except OSError as exc:
        # Placeholder do OneDrive ainda não baixado cai aqui.
        return None, f"Não foi possível ler {NOME_ARQUIVO_MANIFESTO}: {exc}"
    except json.JSONDecodeError as exc:
        return None, f"{NOME_ARQUIVO_MANIFESTO} está corrompido: {exc}"
    if not isinstance(manifesto, dict):
        return None, f"{NOME_ARQUIVO_MANIFESTO} não é um objeto JSON."
    for campo in ("versao", "arquivo", "sha256", "tamanho"):
        if not manifesto.get(campo):
            return None, f"{NOME_ARQUIVO_MANIFESTO} não informa '{campo}'."
    return manifesto, ""


def consultar_canal(canal: Optional[str]) -> StatusAtualizacao:
    """Estado do canal de atualização, sem baixar nem verificar o hash.

    A verificação do sha256 fica de fora de propósito: ler 70 MB do OneDrive a
    cada abertura de tela travaria a interface. Aqui basta o tamanho do arquivo
    em disco, que já pega os dois casos comuns (placeholder de 0 byte e download
    parcial). O hash é conferido na hora de aplicar, em `preparar_pacote`.
    """
    status = StatusAtualizacao()

    if not canal:
        status.motivo = "Canal de atualização não configurado."
        return status
    if not os.path.isdir(canal):
        status.motivo = "A pasta do canal de atualização não está acessível."
        return status

    manifesto, erro = _ler_manifesto(canal)
    if erro:
        status.motivo = erro
        return status

    status.versao_disponivel = str(manifesto["versao"])
    status.notas = str(manifesto.get("notas") or "")
    status.data = str(manifesto.get("data") or "")

    if not versao_mais_nova(status.versao_disponivel):
        status.motivo = "Você já está na versão mais recente."
        return status

    pacote = os.path.join(canal, str(manifesto["arquivo"]))
    if not os.path.isfile(pacote):
        status.motivo = f"O canal anuncia a {status.versao_disponivel}, mas o pacote não está lá."
        return status

    tamanho_esperado = int(manifesto["tamanho"])
    try:
        tamanho_real = os.path.getsize(pacote)
    except OSError as exc:
        status.motivo = f"Não foi possível ler o pacote: {exc}"
        return status

    if tamanho_real != tamanho_esperado:
        # Files On-Demand deixa placeholder de 0 byte; sync interrompido deixa
        # o arquivo curto. Nos dois casos aplicar agora instalaria um zip
        # quebrado, então é melhor esperar.
        status.motivo = (
            f"A versão {status.versao_disponivel} está disponível, mas o pacote "
            "ainda não terminou de sincronizar. Tente de novo em alguns minutos."
        )
        status.detalhes = {"tamanho_esperado": tamanho_esperado, "tamanho_real": tamanho_real}
        return status

    status.atualizavel = True
    status.motivo = f"Versão {status.versao_disponivel} disponível."
    status.caminho_pacote = pacote
    status.detalhes = {"sha256": str(manifesto["sha256"]).lower(), "tamanho": tamanho_esperado}
    return status


# ---------------------------------------------------------------------------
# Cache da consulta
#
# A sidebar mostra um indicador em todas as telas, então a consulta deixa de ser
# um evento raro. Sem cache, cada navegação bateria no OneDrive — que pode ser
# lento, porque pasta remota com Files On-Demand não é leitura de disco local.
# ---------------------------------------------------------------------------

VALIDADE_CACHE_S = 15 * 60

_cache_status: Optional[StatusAtualizacao] = None
_cache_em: float = 0.0
_cache_canal: Optional[str] = None
_trava_cache = threading.Lock()


def consultar_canal_cacheado(canal: Optional[str], *, forcar: bool = False) -> StatusAtualizacao:
    """`consultar_canal` com cache por tempo, invalidado se o canal mudar.

    `forcar=True` para quando o usuário pede explicitamente (botão "Salvar e
    verificar"): ali ele está esperando um resultado novo, não o de 10 minutos
    atrás.
    """
    global _cache_status, _cache_em, _cache_canal

    with _trava_cache:
        valido = (
            _cache_status is not None
            and _cache_canal == canal
            and (time.monotonic() - _cache_em) < VALIDADE_CACHE_S
        )
        if valido and not forcar:
            return _cache_status

    # Fora da trava: consultar_canal toca o disco/rede e não deve bloquear quem
    # só quer ler o cache.
    status = consultar_canal(canal)

    with _trava_cache:
        _cache_status = status
        _cache_em = time.monotonic()
        _cache_canal = canal
    return status


def invalidar_cache() -> None:
    """Esquece o resultado guardado. Chamado quando o canal é reconfigurado."""
    global _cache_status, _cache_em, _cache_canal
    with _trava_cache:
        _cache_status = None
        _cache_em = 0.0
        _cache_canal = None


def aquecer_em_background(canal: Optional[str]) -> None:
    """Consulta o canal numa thread, para o boot não esperar pelo OneDrive.

    Chamado no startup: quando o usuário abre qualquer tela, o resultado já está
    no cache e o indicador aparece sem espera. Falha aqui é irrelevante — a
    próxima consulta tenta de novo.
    """
    def tarefa():
        try:
            consultar_canal_cacheado(canal, forcar=True)
        except Exception:  # noqa: BLE001 - thread de conveniência, não pode derrubar o app
            pass

    threading.Thread(target=tarefa, daemon=True, name="aquecer-atualizacoes").start()


def preparar_pacote(status: StatusAtualizacao, pasta_temporaria: str) -> tuple[Optional[str], str]:
    """Copia o pacote do canal para o disco local e confere o sha256.

    `(caminho_local, motivo_do_erro)` — exatamente um dos dois vem preenchido.

    A cópia acontece antes da troca de arquivos de propósito: extrair lendo
    direto do OneDrive deixaria a atualização à mercê de uma reconexão de rede no
    pior momento possível, com a instalação já desmontada. O hash é conferido
    depois da cópia, e não no canal, porque é a cópia que vai ser instalada.
    """
    if not status.atualizavel or not status.caminho_pacote:
        return None, status.motivo or "Não há atualização a aplicar."

    origem = status.caminho_pacote
    destino = os.path.join(pasta_temporaria, os.path.basename(origem))
    try:
        shutil.copyfile(origem, destino)
    except OSError as exc:
        return None, f"Não foi possível copiar o pacote do canal: {exc}"

    esperado = str(status.detalhes.get("sha256", "")).lower()
    obtido = sha256_do_arquivo(destino)
    if obtido != esperado:
        # Chega aqui quando o arquivo mudou entre a consulta e a cópia, ou quando
        # o OneDrive entregou bytes diferentes dos que o build publicou.
        try:
            os.remove(destino)
        except OSError:
            pass
        return None, (
            "O pacote baixado não confere com o publicado (sha256 diferente). "
            "Tente de novo mais tarde."
        )
    return destino, ""
