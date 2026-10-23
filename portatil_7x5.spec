# -*- mode: python ; coding: utf-8 -*-
"""Empacota o Controlador MIDI 7x5 (o aparelho com display, faders e pads 5x5).

Mesmo código do original; muda só o edicoes/7x5/edicao.json (nome, porta 8801,
modelo e perfil inicial) e o ícone. Gera a pasta dist/Controlador MIDI 7x5/ com o .exe e tudo embutido (Python + janela
pywebview/WebView2). Não precisa instalar nada no computador.

    python -m PyInstaller portatil_7x5.spec --noconfirm --clean
"""
from PyInstaller.utils.hooks import collect_all, copy_metadata

datas = [("web", "web"), ("edicoes/7x5/icone.ico", "."), ("edicoes/7x5/edicao.json", ".")]
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
    name="Controlador MIDI 7x5",
    icon="edicoes/7x5/icone.ico",
    console=False,          # sem janelinha preta
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="Controlador MIDI 7x5",
)
