# -*- mode: python ; coding: utf-8 -*-
"""Empacota o Controlador MIDI como app nativo e portátil do Windows.

Gera a pasta dist/Controlador MIDI/ com o .exe e tudo embutido (Python + janela
pywebview/WebView2). Não precisa instalar nada no computador.

    python -m PyInstaller portatil.spec --noconfirm --clean
"""
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = [("web", "web"), ("icone.ico", ".")]   # o ícone também é usado na bandeja
binaries = []
hiddenimports = ["clr"]

# Janela nativa: pywebview + ponte .NET (WebView2 já vem no Windows 11)
for pacote in ("webview", "clr_loader"):
    d, b, h = collect_all(pacote)
    datas += d
    binaries += b
    hiddenimports += h

try:
    datas += copy_metadata("pythonnet")
except Exception:
    pass

a = Analysis(
    ["controlador.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Controlador MIDI",
    icon="icone.ico",
    console=False,          # sem janelinha preta
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Controlador MIDI",
)
