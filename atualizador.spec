# -*- mode: python ; coding: utf-8 -*-
"""
Empacotamento do atualizador (PyInstaller, onefile).

onefile aqui, ao contrário do Prisma: o script usa só a biblioteca padrão, então
o executável fica na casa dos 10 MB e o custo de extrair para %TEMP% é
irrelevante. Em troca, é um arquivo único ao lado do Prisma.exe, sem uma segunda
pasta `_internal` para o atualizador confundir com a do app.

`excludes` é agressivo de propósito: se pandas ou FastAPI entrarem aqui por
descuido, o atualizador passa a poder falhar por causa de uma dependência do
próprio app que ele está substituindo.

Rodar com:  pyinstaller atualizador.spec --noconfirm
Preferir:   .\build.ps1
"""

import os

RAIZ = os.path.abspath(os.getcwd())

analise = Analysis(
    [os.path.join(RAIZ, "atualizador", "atualizador.py")],
    pathex=[os.path.join(RAIZ, "atualizador")],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pandas",
        "numpy",
        "fastapi",
        "starlette",
        "uvicorn",
        "openpyxl",
        "reportlab",
        "docx",
        "tkinter",
        "matplotlib",
        "IPython",
        "pytest",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analise.pure)

exe = EXE(
    pyz,
    analise.scripts,
    analise.binaries,
    analise.datas,
    [],
    name="atualizador",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX costuma disparar falso positivo de antivírus.
    runtime_tmpdir=None,
    console=True,  # A janela mostra o andamento da troca para o usuário.
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(RAIZ, "backend", "engine", "assets", "logo_2d.ico"),
)
