"""Barra de volume flutuante (OSD) no canto de cima, à esquerda da tela.

Aparece ao girar/apertar um encoder de volume e some sozinha. Janela nativa do Windows
(ctypes + GDI+, sem pip): não rouba o foco, o mouse passa através dela e não aparece na
barra de tarefas. Fundo com transparência de verdade (UpdateLayeredWindow, alfa por pixel).
"""
import ctypes
import threading
from ctypes import wintypes

import icones

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32")
_kernel32 = ctypes.WinDLL("kernel32")
_gdip = ctypes.WinDLL("gdiplus")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
REAL = ctypes.c_float

WM_TIMER, WM_CLOSE, WM_DESTROY = 0x0113, 0x0010, 0x0002
WM_MOSTRAR = 0x8000 + 10
WS_POPUP = 0x80000000
WS_EX = 0x80000 | 0x80 | 0x8 | 0x08000000 | 0x20   # LAYERED, TOOLWINDOW, TOPMOST, NOACTIVATE, TRANSPARENT
SW_HIDE, SW_SHOWNOACTIVATE = 0, 4
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x1, 0x2, 0x10
ULW_ALPHA, AC_SRC_ALPHA = 0x2, 0x1
SPI_GETWORKAREA = 0x30
T_ESPERA, T_SUMIR = 1, 2
TEMPO_VISIVEL = 1500    # ms parada na tela antes de começar a sumir
PASSOS_SUMIR = 8        # quadros do esmaecimento (30 ms cada)

# Tamanho em pixels "lógicos" (multiplicado pela escala do Windows)
LARG, ALT = 320, 72


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]


class _BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


class _GdiplusStartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", wintypes.BOOL), ("SuppressExternalCodecs", wintypes.BOOL)]


class _RectF(ctypes.Structure):
    _fields_ = [("X", REAL), ("Y", REAL), ("Width", REAL), ("Height", REAL)]


_P = ctypes.c_void_p
_PP = ctypes.POINTER(ctypes.c_void_p)


def _decl(dll, nome, *args, res=ctypes.c_int):
    f = getattr(dll, nome)
    f.argtypes, f.restype = list(args), res
    return f


_decl(_user32, "DefWindowProcW", wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, res=LRESULT)
_decl(_user32, "CreateWindowExW", wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
      ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU,
      wintypes.HINSTANCE, wintypes.LPVOID, res=wintypes.HWND)
_decl(_user32, "PostMessageW", wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM, res=wintypes.BOOL)
_decl(_user32, "ShowWindow", wintypes.HWND, ctypes.c_int, res=wintypes.BOOL)
_decl(_user32, "SetWindowPos", wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int,
      ctypes.c_int, wintypes.UINT, res=wintypes.BOOL)
_decl(_user32, "SetTimer", wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p, res=ctypes.c_size_t)
_decl(_user32, "KillTimer", wintypes.HWND, ctypes.c_size_t, res=wintypes.BOOL)
_decl(_user32, "GetDC", wintypes.HWND, res=wintypes.HDC)
_decl(_user32, "ReleaseDC", wintypes.HWND, wintypes.HDC)
_decl(_user32, "UpdateLayeredWindow", wintypes.HWND, wintypes.HDC, ctypes.POINTER(wintypes.POINT),
      ctypes.POINTER(wintypes.SIZE), wintypes.HDC, ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
      ctypes.POINTER(_BLENDFUNCTION), wintypes.DWORD, res=wintypes.BOOL)
_decl(_user32, "SystemParametersInfoW", wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT, res=wintypes.BOOL)
_decl(_user32, "DestroyWindow", wintypes.HWND, res=wintypes.BOOL)
_decl(_gdi32, "CreateCompatibleDC", wintypes.HDC, res=wintypes.HDC)
_decl(_gdi32, "CreateDIBSection", wintypes.HDC, ctypes.POINTER(_BITMAPINFOHEADER), wintypes.UINT, _PP,
      wintypes.HANDLE, wintypes.DWORD, res=wintypes.HBITMAP)
_decl(_gdi32, "SelectObject", wintypes.HDC, wintypes.HGDIOBJ, res=wintypes.HGDIOBJ)
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE

_decl(_gdip, "GdiplusStartup", ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(_GdiplusStartupInput), _P)
_decl(_gdip, "GdipCreateBitmapFromScan0", ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, _P, _PP)
_decl(_gdip, "GdipGetImageGraphicsContext", _P, _PP)
_decl(_gdip, "GdipDeleteGraphics", _P)
_decl(_gdip, "GdipSetSmoothingMode", _P, ctypes.c_int)
_decl(_gdip, "GdipSetTextRenderingHint", _P, ctypes.c_int)
_decl(_gdip, "GdipGraphicsClear", _P, ctypes.c_uint32)
_decl(_gdip, "GdipCreateSolidFill", ctypes.c_uint32, _PP)
_decl(_gdip, "GdipDeleteBrush", _P)
_decl(_gdip, "GdipCreatePen1", ctypes.c_uint32, REAL, ctypes.c_int, _PP)
_decl(_gdip, "GdipSetPenStartCap", _P, ctypes.c_int)
_decl(_gdip, "GdipSetPenEndCap", _P, ctypes.c_int)
_decl(_gdip, "GdipDeletePen", _P)
_decl(_gdip, "GdipFillEllipse", _P, _P, REAL, REAL, REAL, REAL)
_decl(_gdip, "GdipDrawLine", _P, _P, REAL, REAL, REAL, REAL)
_decl(_gdip, "GdipCreatePath", ctypes.c_int, _PP)
_decl(_gdip, "GdipAddPathArc", _P, REAL, REAL, REAL, REAL, REAL, REAL)
_decl(_gdip, "GdipClosePathFigure", _P)
_decl(_gdip, "GdipFillPath", _P, _P, _P)
_decl(_gdip, "GdipDrawPath", _P, _P, _P)
_decl(_gdip, "GdipDeletePath", _P)
_decl(_gdip, "GdipCreateFontFamilyFromName", wintypes.LPCWSTR, _P, _PP)
_decl(_gdip, "GdipDeleteFontFamily", _P)
_decl(_gdip, "GdipCreateFont", _P, REAL, ctypes.c_int, ctypes.c_int, _PP)
_decl(_gdip, "GdipDeleteFont", _P)
_decl(_gdip, "GdipCreateStringFormat", ctypes.c_int, wintypes.WORD, _PP)
_decl(_gdip, "GdipSetStringFormatAlign", _P, ctypes.c_int)
_decl(_gdip, "GdipSetStringFormatLineAlign", _P, ctypes.c_int)
_decl(_gdip, "GdipSetStringFormatFlags", _P, ctypes.c_int)
_decl(_gdip, "GdipSetStringFormatTrimming", _P, ctypes.c_int)
_decl(_gdip, "GdipDeleteStringFormat", _P)
_decl(_gdip, "GdipDrawString", _P, wintypes.LPCWSTR, ctypes.c_int, _P, ctypes.POINTER(_RectF), _P, _P)
_decl(_gdip, "GdipSetInterpolationMode", _P, ctypes.c_int)
_decl(_gdip, "GdipDrawImageRectI", _P, _P, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
_decl(_gdip, "GdipDisposeImage", _P)


def _argb(hex_cor, alfa=255):
    try:
        h = hex_cor.lstrip("#")
        return (alfa << 24) | int(h[:6], 16)
    except (AttributeError, ValueError):
        return (alfa << 24) | 0x3B82F6


class Osd:
    """mostrar({'nome', 'pct', 'mudo', 'cor', 'icone'}) pode ser chamado de qualquer thread."""

    def __init__(self):
        self.hwnd = None
        self._dados = None
        self._alfa = 0
        self._wndproc = WNDPROC(self._proc)     # manter referência viva
        self._pronto = threading.Event()

    def iniciar(self):
        threading.Thread(target=self._rodar, daemon=True).start()
        self._pronto.wait(5)

    def mostrar(self, dados):
        self._dados = dict(dados)
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_MOSTRAR, 0, 0)

    # --- thread da barra ---
    def _rodar(self):
        try:
            self._preparar()
        finally:
            self._pronto.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _preparar(self):
        ctypes.WinDLL("ole32").CoInitializeEx(None, 0)    # o ícone de atalho (.lnk) vem do Shell
        token = ctypes.c_size_t()
        entrada = _GdiplusStartupInput(1, None, False, False)
        _gdip.GdiplusStartup(ctypes.byref(token), ctypes.byref(entrada), None)
        try:
            dpi = _user32.GetDpiForSystem()
        except AttributeError:
            dpi = 96
        self.esc = (dpi or 96) / 96
        self.larg, self.alt = round(LARG * self.esc), round(ALT * self.esc)

        hinst = _kernel32.GetModuleHandleW(None)
        cls = _WNDCLASSW()
        cls.lpfnWndProc = self._wndproc
        cls.hInstance = hinst
        cls.lpszClassName = "ControladorMIDIOsd"
        _user32.RegisterClassW(ctypes.byref(cls))
        area = wintypes.RECT()
        _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(area), 0)
        margem = round(24 * self.esc)
        self.pos = wintypes.POINT(area.left + margem, area.top + margem)
        self.hwnd = _user32.CreateWindowExW(WS_EX, cls.lpszClassName, "Controlador MIDI - volume", WS_POPUP,
                                            self.pos.x, self.pos.y, self.larg, self.alt, None, None, hinst, None)

        # Imagem 32 bits com alfa, compartilhada entre o GDI (janela) e o GDI+ (desenho)
        bmi = _BITMAPINFOHEADER(ctypes.sizeof(_BITMAPINFOHEADER), self.larg, -self.alt, 1, 32, 0, 0, 0, 0, 0, 0)
        self.bits = ctypes.c_void_p()
        tela = _user32.GetDC(None)
        self.dc = _gdi32.CreateCompatibleDC(tela)
        _user32.ReleaseDC(None, tela)
        hbmp = _gdi32.CreateDIBSection(self.dc, ctypes.byref(bmi), 0, ctypes.byref(self.bits), None, 0)
        _gdi32.SelectObject(self.dc, hbmp)
        self.img = ctypes.c_void_p()
        _gdip.GdipCreateBitmapFromScan0(self.larg, self.alt, self.larg * 4, 0x000E200B,   # 32bpp PARGB
                                        self.bits, ctypes.byref(self.img))

    def _fonte(self, nomes, tam, negrito=False):
        for nome in nomes:
            fam = ctypes.c_void_p()
            if _gdip.GdipCreateFontFamilyFromName(nome, None, ctypes.byref(fam)) == 0:
                fonte = ctypes.c_void_p()
                _gdip.GdipCreateFont(fam, tam * self.esc, 1 if negrito else 0, 2, ctypes.byref(fonte))  # 2 = pixel
                _gdip.GdipDeleteFontFamily(fam)
                return fonte
        return None

    def _texto(self, g, texto, fonte, cor, x, y, w, h, alinhar=0):
        if not fonte:
            return
        fmt, pincel = ctypes.c_void_p(), ctypes.c_void_p()
        _gdip.GdipCreateStringFormat(0x1000, 0, ctypes.byref(fmt))     # sem quebra de linha
        _gdip.GdipSetStringFormatAlign(fmt, alinhar)
        _gdip.GdipSetStringFormatLineAlign(fmt, 1)                     # centro na vertical
        _gdip.GdipSetStringFormatTrimming(fmt, 3)                      # "..." se não couber
        _gdip.GdipCreateSolidFill(cor, ctypes.byref(pincel))
        e = self.esc
        _gdip.GdipDrawString(g, texto, -1, fonte, ctypes.byref(_RectF(x * e, y * e, w * e, h * e)), fmt, pincel)
        _gdip.GdipDeleteBrush(pincel)
        _gdip.GdipDeleteStringFormat(fmt)

    def _arredondado(self, g, cor, x, y, w, h, r, borda=None):
        e = self.esc
        x, y, w, h, d = x * e, y * e, w * e, h * e, 2 * r * e
        caminho, pincel = ctypes.c_void_p(), ctypes.c_void_p()
        _gdip.GdipCreatePath(0, ctypes.byref(caminho))
        _gdip.GdipAddPathArc(caminho, x, y, d, d, 180, 90)
        _gdip.GdipAddPathArc(caminho, x + w - d, y, d, d, 270, 90)
        _gdip.GdipAddPathArc(caminho, x + w - d, y + h - d, d, d, 0, 90)
        _gdip.GdipAddPathArc(caminho, x, y + h - d, d, d, 90, 90)
        _gdip.GdipClosePathFigure(caminho)
        _gdip.GdipCreateSolidFill(cor, ctypes.byref(pincel))
        _gdip.GdipFillPath(g, pincel, caminho)
        _gdip.GdipDeleteBrush(pincel)
        if borda:
            caneta = ctypes.c_void_p()
            _gdip.GdipCreatePen1(borda, 1.0 * e, 2, ctypes.byref(caneta))
            _gdip.GdipDrawPath(g, caneta, caminho)
            _gdip.GdipDeletePen(caneta)
        _gdip.GdipDeletePath(caminho)

    def _desenhar(self, d):
        g = ctypes.c_void_p()
        _gdip.GdipGetImageGraphicsContext(self.img, ctypes.byref(g))
        _gdip.GdipSetSmoothingMode(g, 4)          # antisserrilhado
        _gdip.GdipSetTextRenderingHint(g, 4)
        _gdip.GdipGraphicsClear(g, 0)
        e = self.esc
        pct, mudo = max(0, min(100, int(d.get("pct", 0)))), bool(d.get("mudo"))
        cor = _argb(d.get("cor") or "#3b82f6")

        # fundo
        self._arredondado(g, 0xF5202329, 0.5, 0.5, LARG - 1, ALT - 1, 14, borda=0x33FFFFFF)

        # círculo com o ícone (do programa, o emoji escolhido ou o alto-falante do Windows)
        app = icones.carregar(d["icone_app"]) if d.get("icone_app") else None
        pincel = ctypes.c_void_p()
        fundo = 0x26FFFFFF if app else _argb(d.get("cor") or "#3b82f6", 120 if mudo else 255)
        _gdip.GdipCreateSolidFill(fundo, ctypes.byref(pincel))
        _gdip.GdipFillEllipse(g, pincel, 12 * e, 12 * e, 48 * e, 48 * e)
        _gdip.GdipDeleteBrush(pincel)
        icone = d.get("icone") or ""
        fonte = None
        if app:
            w, h, bgra = app
            buf = ctypes.create_string_buffer(bgra, len(bgra))    # vivo enquanto a imagem é usada
            imagem = ctypes.c_void_p()
            _gdip.GdipCreateBitmapFromScan0(w, h, w * 4, 0x0026200A, buf, ctypes.byref(imagem))   # 32bpp ARGB
            _gdip.GdipSetInterpolationMode(g, 7)                   # bicúbica de alta qualidade
            lado = round(32 * e)
            _gdip.GdipDrawImageRectI(g, imagem, round(36 * e - lado / 2), round(36 * e - lado / 2), lado, lado)
            _gdip.GdipDisposeImage(imagem)
        elif icone and not mudo:
            fonte = self._fonte(["Segoe UI Emoji"], 22)
            self._texto(g, icone, fonte, 0xFFFFFFFF, 12, 12, 48, 48, 1)
        else:
            if d.get("mic"):
                glifo = ""     # microfone (no mudo, o risco vermelho vai por cima)
            elif mudo:
                glifo = ""
            else:
                glifo = "" if pct == 0 else "" if pct < 34 else "" if pct < 67 else ""
            fonte = self._fonte(["Segoe Fluent Icons", "Segoe MDL2 Assets"], 22)
            self._texto(g, glifo, fonte, 0xFFFFFFFF, 12, 12, 48, 48, 1)
        if fonte:
            _gdip.GdipDeleteFont(fonte)
        if mudo:   # risco vermelho, igual ao da tela do programa
            caneta = ctypes.c_void_p()
            _gdip.GdipCreatePen1(0xFFE5484D, 4 * e, 2, ctypes.byref(caneta))
            _gdip.GdipSetPenStartCap(caneta, 2)
            _gdip.GdipSetPenEndCap(caneta, 2)
            _gdip.GdipDrawLine(g, caneta, 18 * e, 54 * e, 54 * e, 18 * e)
            _gdip.GdipDeletePen(caneta)

        # nome e porcentagem
        fonte = self._fonte(["Segoe UI Semibold", "Segoe UI"], 14)
        self._texto(g, d.get("nome") or "Volume", fonte, 0xFFFFFFFF, 72, 10, LARG - 72 - 70, 26)
        self._texto(g, "Mudo" if mudo else f"{pct}", fonte, 0xFFE5484D if mudo else 0xFFFFFFFF,
                    LARG - 70, 10, 56, 26, 2)
        if fonte:
            _gdip.GdipDeleteFont(fonte)

        # barra
        bx, by, bw, bh = 72, 44, LARG - 72 - 16, 8
        self._arredondado(g, 0x40FFFFFF, bx, by, bw, bh, 4)
        if pct > 0:
            preench = 0x80FFFFFF if mudo else (cor | 0xFF000000)
            self._arredondado(g, preench, bx, by, max(bh, bw * pct / 100), bh, 4)
        _gdip.GdipDeleteGraphics(g)              # grava o desenho na imagem

    def _aplicar(self):
        tela = _user32.GetDC(None)
        mistura = _BLENDFUNCTION(0, 0, max(0, min(255, self._alfa)), AC_SRC_ALPHA)
        _user32.UpdateLayeredWindow(self.hwnd, tela, ctypes.byref(self.pos), ctypes.byref(wintypes.SIZE(self.larg, self.alt)),
                                    self.dc, ctypes.byref(wintypes.POINT(0, 0)), 0, ctypes.byref(mistura), ULW_ALPHA)
        _user32.ReleaseDC(None, tela)

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_MOSTRAR and self._dados is not None:
                self._desenhar(self._dados)
                self._alfa = 255
                self._aplicar()
                _user32.KillTimer(hwnd, T_SUMIR)
                _user32.SetTimer(hwnd, T_ESPERA, TEMPO_VISIVEL, None)
                _user32.ShowWindow(hwnd, SW_SHOWNOACTIVATE)
                _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                return 0
            if msg == WM_TIMER:
                if wparam == T_ESPERA:
                    _user32.KillTimer(hwnd, T_ESPERA)
                    _user32.SetTimer(hwnd, T_SUMIR, 30, None)
                elif wparam == T_SUMIR:
                    self._alfa -= 255 // PASSOS_SUMIR
                    if self._alfa <= 0:
                        _user32.KillTimer(hwnd, T_SUMIR)
                        _user32.ShowWindow(hwnd, SW_HIDE)
                    else:
                        self._aplicar()
                return 0
            if msg == WM_CLOSE:
                _user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                _user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
