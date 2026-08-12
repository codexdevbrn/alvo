# -*- mode: python ; coding: utf-8 -*-
"""
Empacotamento do Prisma (PyInstaller, modo onedir).

onedir e não onefile: onefile extrai pandas/numpy/reportlab (centenas de MB)
para %TEMP% a cada execução, o que custa dezenas de segundos de startup e
provoca varredura de antivírus todas as vezes.

Rodar com:  pyinstaller prisma.spec --noconfirm
Preferir:   .\build.ps1  (garante que o dist do frontend está atualizado)
"""

import os

# SPECPATH é injetado pelo PyInstaller e aponta para a pasta deste .spec.
# `os.getcwd()` seria a pasta de onde o comando foi chamado, então rodar o build
# de outro diretório resolveria todos os caminhos abaixo para o lugar errado.
RAIZ = os.path.abspath(SPECPATH)  # noqa: F821 (injetado pelo PyInstaller)
BACKEND = os.path.join(RAIZ, "backend")
DIST_WEB = os.path.join(RAIZ, "dashboard", "dist")

if not os.path.isfile(os.path.join(DIST_WEB, "index.html")):
    raise SystemExit(
        "dashboard/dist/index.html não encontrado. Rode `npm run build` em "
        "dashboard/ (ou use build.ps1) antes de empacotar."
    )

# O build do frontend vai embutido como `web/`, de onde recursos.pasta_web() o
# lê quando congelado. `data/` fica de fora: é o summary.json do modo estático
# (~20 MB), um retrato congelado que o executável não usa — no pacote ele só
# engordaria todo release. O modo por empresa busca o summary do backend.
# Destino "assets" na raiz do bundle, e NÃO "engine/assets": `recursos.caminho_recurso`
# resolve a partir de `sys._MEIPASS`, então é ali que o código procura o logo. Com o
# destino errado, todo PDF e Excel saía sem logo e a bandeja não achava o ícone — sem
# erro nenhum, porque quem lê o logo o trata como opcional (`if os.path.exists`).
datas = [
    (os.path.join(BACKEND, "engine", "assets"), "assets"),
]
for pasta_atual, _subpastas, arquivos in os.walk(DIST_WEB):
    relativo = os.path.relpath(pasta_atual, DIST_WEB)
    if relativo == "data" or relativo.startswith("data" + os.sep):
        continue
    destino = "web" if relativo == "." else os.path.join("web", relativo)
    for arquivo in arquivos:
        datas.append((os.path.join(pasta_atual, arquivo), destino))

# Módulos que só são alcançados por import dinâmico ou por string, invisíveis
# para a análise estática do PyInstaller.
hiddenimports = [
    # Scripts da raiz importados por main.py via sys.path.
    "normalizar_base",
    "normalizar_liquidez",
    "harmonizar_descricoes",
    # uvicorn resolve estes por nome em tempo de execução.
    "uvicorn.logging",
    "uvicorn.loops.auto",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan.on",
    # Engines de leitura/escrita que pandas importa sob demanda.
    "openpyxl",
    "openpyxl.cell._writer",
    # Extensão compilada resolvida por nome pelo pandas (engine="calamine"), então
    # a análise estática não a encontra sozinha.
    "python_calamine",
    # O pystray escolhe o backend em tempo de execução pelo sistema operacional.
    "pystray._win32",
]

# Pesados e sem uso aqui. tkinter em especial arrasta DLLs de GUI inteiras.
excludes = [
    "tkinter",
    "matplotlib",
    "IPython",
    "pytest",
    "notebook",
    "PyQt5",
    "PySide6",
]

analise = Analysis(
    [os.path.join(BACKEND, "servidor.py")],
    pathex=[BACKEND, RAIZ],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analise.pure)

exe = EXE(
    pyz,
    analise.scripts,
    [],
    exclude_binaries=True,
    name="Prisma",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX costuma disparar falso positivo de antivírus.
    console=True,  # O console é a janela que o usuário mantém aberta.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(BACKEND, "engine", "assets", "logo_2d.ico"),
)

coll = COLLECT(
    exe,
    analise.binaries,
    analise.datas,
    strip=False,
    upx=False,
    name="Prisma",
)
