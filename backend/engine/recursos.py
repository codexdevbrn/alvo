"""
Resolução de caminhos usados em todo o sistema:

- recursos embutidos (logo) que funcionam tanto rodando `python app.py` em
  desenvolvimento quanto empacotado como .exe (PyInstaller extrai os dados
  para uma pasta temporária apontada por sys._MEIPASS);
- pasta de dados LOCAIS (perfil do usuário, logs) que fica ao lado do
  executável/script — cada instalação/cópia do .exe tem a sua própria,
  então compartilhar o executável com outra pessoa não compartilha o perfil.
"""

import os
import sys
import tempfile


def caminho_recurso(*partes_caminho):
    """Recurso embutido no pacote (ex.: assets/logo_2d.png). Somente leitura."""
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *partes_caminho)


def pasta_base_execucao():
    """Pasta onde o backend está rodando (um nível acima de engine/, para
    compartilhar dados_locais/ com main.py/db.py)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def pasta_dados_locais_ja_existe():
    """True se 'dados_locais' ou 'logs' já existem ao lado do executável (ou seja, não é a primeira execução aqui)."""
    base = pasta_base_execucao()
    return os.path.isdir(os.path.join(base, "dados_locais")) or os.path.isdir(os.path.join(base, "logs"))


# Definido por app.py na primeira execução, a partir da resposta do usuário
# ao diálogo de permissão. Enquanto não for definido, assume-se permitido
# (ex.: quando algum código chama isso fora do fluxo normal do app, como em
# testes) — só fica False se o usuário explicitamente recusar.
_PERMITIR_DADOS_LOCAIS = True


def definir_permissao_dados_locais(permitido):
    global _PERMITIR_DADOS_LOCAIS
    _PERMITIR_DADOS_LOCAIS = permitido


def pasta_logs():
    """Pasta de logs — mesma regra de permissão de caminho_dados_locais."""
    if _PERMITIR_DADOS_LOCAIS:
        pasta = os.path.join(pasta_base_execucao(), "logs")
    else:
        pasta = os.path.join(tempfile.gettempdir(), "Monitor2D_logs_temporarios")
    os.makedirs(pasta, exist_ok=True)
    return pasta


def caminho_dados_locais(*partes_caminho):
    """
    Arquivo de dados local (perfil, logs) — gravável, específico desta
    instalação. Se o usuário recusou a permissão de criar pastas ao lado do
    executável (ver definir_permissao_dados_locais), usa uma pasta temporária
    do Windows em vez disso — nada é gravado perto do .exe/script.
    """
    if _PERMITIR_DADOS_LOCAIS:
        pasta = os.path.join(pasta_base_execucao(), "dados_locais")
    else:
        pasta = os.path.join(tempfile.gettempdir(), "Monitor2D_dados_temporarios")
    os.makedirs(pasta, exist_ok=True)
    return os.path.join(pasta, *partes_caminho)


NOME_SISTEMA = "Monitor"
NOME_EMPRESA = "2D Consultores | Monitores"

# Versão embutida no executável — atualizada manualmente a cada release
# publicada no GitHub. Usada por atualizacoes.py para avisar o usuário
# quando existe uma versão mais nova disponível, e exibida na interface
# (título da janela, cabeçalho, "Sobre") para facilitar suporte.
VERSAO_ATUAL = "1.5.0"
REPOSITORIO_GITHUB = "erickxc/analisador-monitoria-2d"

TITULO_JANELA = f"{NOME_SISTEMA} v{VERSAO_ATUAL} - {NOME_EMPRESA}"

CAMINHO_LOGO = caminho_recurso("assets", "logo_2d.png")
CAMINHO_LOGO_ICO = caminho_recurso("assets", "logo_2d.ico")

# Só a marca (sem o texto "2D CONSULTORES"), quadrada — para usos pequenos
# (ícone da janela, logo inline no cabeçalho, logo por aba do Excel), onde
# o logo completo com texto fica ilegível/cortado ao ser reduzido.
CAMINHO_LOGO_ICONE = caminho_recurso("assets", "logo_2d_icone.png")
