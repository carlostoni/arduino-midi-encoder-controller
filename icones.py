"""Ícone de um programa (.exe) ou arquivo, para usar no lugar do emoji.

Acha o programa pelo nome ("chrome.exe") ou pelo caminho, extrai o ícone com a API do
Windows (ctypes) e devolve os pixels BGRA (para a barra flutuante) ou um PNG (para a tela).
O PNG é montado à mão com zlib — sem Pillow.
"""
import ctypes
import os
import shutil
import struct
import threading
import time
import winreg
import zlib
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
_gdi32 = ctypes.WinDLL("gdi32")
_kernel32 = ctypes.WinDLL("kernel32")
_shell32 = ctypes.WinDLL("shell32")

TAMANHO = 64     # pixels; a tela e a barra reduzem


class _ICONINFO(ctypes.Structure):
    _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                ("hbmMask", wintypes.HBITMAP), ("hbmColor", wintypes.HBITMAP)]


class _BITMAP(ctypes.Structure):
    _fields_ = [("bmType", wintypes.LONG), ("bmWidth", wintypes.LONG), ("bmHeight", wintypes.LONG),
                ("bmWidthBytes", wintypes.LONG), ("bmPlanes", wintypes.WORD), ("bmBitsPixel", wintypes.WORD),
                ("bmBits", ctypes.c_void_p)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _SHFILEINFOW(ctypes.Structure):
    _fields_ = [("hIcon", wintypes.HICON), ("iIcon", ctypes.c_int), ("dwAttributes", wintypes.DWORD),
                ("szDisplayName", wintypes.WCHAR * 260), ("szTypeName", wintypes.WCHAR * 80)]


_user32.PrivateExtractIconsW.argtypes = [wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
                                         wintypes.UINT, wintypes.UINT]
_user32.PrivateExtractIconsW.restype = wintypes.UINT
_user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
_user32.DestroyIcon.argtypes = [wintypes.HICON]
_user32.GetDC.restype = wintypes.HDC
_user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
_gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
_gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p,
                             ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT]
_gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_shell32.SHGetFileInfoW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(_SHFILEINFOW),
                                    wintypes.UINT, wintypes.UINT]
_shell32.SHGetFileInfoW.restype = ctypes.c_size_t
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

_trava = threading.Lock()
_cache = {}          # nome -> (instante, (largura, altura, bgra) ou None)
FALHA_VALE = 20      # s até tentar de novo um programa que não achei (pode ter sido aberto depois)


# --- achar o .exe ---
def _processos_abertos():
    """{nome.exe: caminho completo} dos programas abertos."""
    ids = (wintypes.DWORD * 4096)()
    usado = wintypes.DWORD()
    if not _kernel32.K32EnumProcesses(ids, ctypes.sizeof(ids), ctypes.byref(usado)):
        return {}
    achados = {}
    for pid in ids[:usado.value // ctypes.sizeof(wintypes.DWORD)]:
        h = _kernel32.OpenProcess(0x1000, False, pid)     # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            continue
        try:
            buf, tam = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
                achados.setdefault(os.path.basename(buf.value).lower(), buf.value)
        finally:
            _kernel32.CloseHandle(h)
    return achados


def _app_paths(nome):
    """Registro "App Paths": onde o Windows guarda o caminho de programas como chrome.exe."""
    for raiz in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(raiz, rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{nome}") as k:
                caminho = os.path.expandvars(winreg.QueryValue(k, None).strip('"'))
                if os.path.isfile(caminho):
                    return caminho
        except OSError:
            pass
    return None


def _menu_iniciar(nome):
    """Atalho do Menu Iniciar com o mesmo nome (Discord, Spotify... ficam fora do PATH).
    O ícone de um .lnk é o do programa para onde ele aponta."""
    base = os.path.splitext(nome)[0].lower()
    for pasta in (os.path.expandvars(r"%APPDATA%\Microsoft\Windows\Start Menu\Programs"),
                  os.path.expandvars(r"%PROGRAMDATA%\Microsoft\Windows\Start Menu\Programs")):
        for raiz, _pastas, arquivos in os.walk(pasta):
            for arq in arquivos:
                if arq.lower() == base + ".lnk":
                    return os.path.join(raiz, arq)
    return None


def achar(alvo):
    """Caminho do arquivo a partir de "chrome", "chrome.exe" ou de um caminho completo."""
    alvo = (alvo or "").strip().strip('"')
    if not alvo:
        return None
    if os.path.isfile(os.path.expandvars(alvo)):
        return os.path.expandvars(alvo)
    nome = os.path.basename(alvo).lower()
    if not nome.endswith(".exe"):
        nome += ".exe"
    return _processos_abertos().get(nome) or _app_paths(nome) or shutil.which(nome) or _menu_iniciar(nome)


# --- extrair os pixels ---
def _hicon(caminho):
    h, ident = wintypes.HICON(), wintypes.UINT()
    if _user32.PrivateExtractIconsW(caminho, 0, TAMANHO, TAMANHO, ctypes.byref(h), ctypes.byref(ident), 1, 0) == 1 and h:
        return h
    info = _SHFILEINFOW()      # não é .exe (atalho, documento...): ícone do tipo do arquivo
    if _shell32.SHGetFileInfoW(caminho, 0, ctypes.byref(info), ctypes.sizeof(info), 0x100 | 0x0) and info.hIcon:
        return info.hIcon      # SHGFI_ICON | SHGFI_LARGEICON
    return None


def _pixels(hicon):
    """(largura, altura, BGRA de cima para baixo) do ícone."""
    ii = _ICONINFO()
    if not _user32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    try:
        bm = _BITMAP()
        _gdi32.GetObjectW(ii.hbmColor or ii.hbmMask, ctypes.sizeof(bm), ctypes.byref(bm))
        w, h = bm.bmWidth, bm.bmHeight if ii.hbmColor else bm.bmHeight // 2
        bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
        dc = _user32.GetDC(None)
        try:
            cor = (ctypes.c_ubyte * (w * h * 4))()
            if ii.hbmColor:
                _gdi32.GetDIBits(dc, ii.hbmColor, 0, h, cor, ctypes.byref(bmi), 0)
            if not any(cor[3::4]):          # ícone antigo sem alfa: a máscara diz o que é transparente
                masc = (ctypes.c_ubyte * (w * h * 4))()
                bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)
                _gdi32.GetDIBits(dc, ii.hbmMask, 0, h, masc, ctypes.byref(bmi), 0)
                for i in range(0, w * h * 4, 4):
                    cor[i + 3] = 0 if masc[i] else 255
        finally:
            _user32.ReleaseDC(None, dc)
        return w, h, bytes(cor)
    finally:
        if ii.hbmColor:
            _gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            _gdi32.DeleteObject(ii.hbmMask)


def carregar(alvo):
    """(largura, altura, BGRA) do ícone do programa, ou None. Guarda em memória."""
    chave = (alvo or "").strip().lower()
    with _trava:
        if chave in _cache:
            quando, img = _cache[chave]
            if img or time.time() - quando < FALHA_VALE:
                return img
    img = None
    caminho = achar(alvo)
    if caminho:
        h = _hicon(caminho)
        if h:
            try:
                img = _pixels(h)
            finally:
                _user32.DestroyIcon(h)
    with _trava:
        _cache[chave] = (time.time(), img)
    return img


def png(alvo):
    """Bytes de um PNG com o ícone, ou None."""
    img = carregar(alvo)
    if not img:
        return None
    w, h, bgra = img
    linhas = bytearray()
    for y in range(h):
        linha = bytearray(bgra[y * w * 4:(y + 1) * w * 4])
        linha[0::4], linha[2::4] = linha[2::4], linha[0::4]     # BGRA -> RGBA
        linhas += b"\x00" + linha                                # filtro 0 em cada linha

    def bloco(tipo, dados):
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))

    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(bytes(linhas), 9)) + bloco(b"IEND", b""))
