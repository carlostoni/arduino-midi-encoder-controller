"""Ícone na bandeja do Windows (perto do relógio), feito com a API do Windows via ctypes.

Clique (esquerdo ou direito) abre o menu; clique duplo abre a janela direto.
"""
import ctypes
import threading
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_shell32 = ctypes.WinDLL("shell32")
_kernel32 = ctypes.WinDLL("kernel32")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_NULL = 0x0000
WM_LBUTTONUP = 0x0202
WM_LBUTTONDBLCLK = 0x0203
WM_RBUTTONUP = 0x0205
WM_APP = 0x8000
WM_BANDEJA = WM_APP + 1
WM_ATUALIZAR = WM_APP + 2

NIM_ADD, NIM_MODIFY, NIM_DELETE = 0, 1, 2
NIF_MESSAGE, NIF_ICON, NIF_TIP, NIF_INFO = 0x1, 0x2, 0x4, 0x10
MF_STRING, MF_CHECKED, MF_SEPARATOR, MF_GRAYED = 0x0, 0x8, 0x800, 0x1
TPM_RIGHTBUTTON, TPM_RETURNCMD, TPM_BOTTOMALIGN = 0x2, 0x100, 0x20
IMAGE_ICON, LR_LOADFROMFILE, LR_DEFAULTSIZE = 1, 0x10, 0x40
IDI_APPLICATION = 32512

ID_ABRIR, ID_ATIVO, ID_FECHAR = 1, 2, 3


class _WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wintypes.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR)]


class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]


class _NOTIFYICONDATAW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("hWnd", wintypes.HWND), ("uID", wintypes.UINT),
                ("uFlags", wintypes.UINT), ("uCallbackMessage", wintypes.UINT), ("hIcon", wintypes.HICON),
                ("szTip", wintypes.WCHAR * 128), ("dwState", wintypes.DWORD), ("dwStateMask", wintypes.DWORD),
                ("szInfo", wintypes.WCHAR * 256), ("uVersion", wintypes.UINT), ("szInfoTitle", wintypes.WCHAR * 64),
                ("dwInfoFlags", wintypes.DWORD), ("guidItem", _GUID), ("hBalloonIcon", wintypes.HICON)]


_user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DefWindowProcW.restype = LRESULT
_user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
_user32.CreateWindowExW.restype = wintypes.HWND
_user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
_user32.LoadImageW.restype = wintypes.HANDLE
_user32.LoadIconW.argtypes = [wintypes.HINSTANCE, wintypes.LPVOID]
_user32.LoadIconW.restype = wintypes.HICON
_user32.CreatePopupMenu.restype = wintypes.HMENU
_user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
_user32.SetMenuDefaultItem.argtypes = [wintypes.HMENU, wintypes.UINT, wintypes.UINT]
_user32.TrackPopupMenu.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.LPVOID]
_user32.DestroyMenu.argtypes = [wintypes.HMENU]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.DestroyWindow.argtypes = [wintypes.HWND]
_kernel32.GetModuleHandleW.restype = wintypes.HMODULE
_shell32.Shell_NotifyIconW.argtypes = [wintypes.DWORD, ctypes.POINTER(_NOTIFYICONDATAW)]


class Bandeja:
    """Ícone da bandeja. Os callbacks rodam na thread da bandeja: devem ser rápidos.

    ao_abrir(), ao_fechar(), ao_alternar_ativo() e esta_ativo() -> bool.
    """

    def __init__(self, dica, arquivo_icone, ao_abrir, ao_fechar, ao_alternar_ativo, esta_ativo):
        self.dica = dica
        self.arquivo_icone = arquivo_icone
        self.ao_abrir, self.ao_fechar = ao_abrir, ao_fechar
        self.ao_alternar_ativo, self.esta_ativo = ao_alternar_ativo, esta_ativo
        self.hwnd = None
        self._wndproc = WNDPROC(self._proc)    # manter referência viva
        self._pronto = threading.Event()
        self._msg_taskbar = _user32.RegisterWindowMessageW("TaskbarCreated")

    # --- ciclo de vida ---
    def iniciar(self):
        threading.Thread(target=self._rodar, daemon=True).start()
        self._pronto.wait(5)

    def parar(self):
        if self.hwnd:
            _user32.PostMessageW(self.hwnd, WM_CLOSE, 0, 0)

    def avisar(self, titulo, texto):
        """Balãozinho de notificação saindo do ícone."""
        if self.hwnd:
            self._pendente_aviso = (titulo, texto)
            _user32.PostMessageW(self.hwnd, WM_ATUALIZAR, 0, 0)

    # --- thread da bandeja ---
    def _rodar(self):
        hinst = _kernel32.GetModuleHandleW(None)
        cls = _WNDCLASSW()
        cls.lpfnWndProc = self._wndproc
        cls.hInstance = hinst
        cls.lpszClassName = "ControladorMIDIBandeja"
        _user32.RegisterClassW(ctypes.byref(cls))
        self.hwnd = _user32.CreateWindowExW(0, cls.lpszClassName, "Controlador MIDI", 0,
                                            0, 0, 0, 0, None, None, hinst, None)
        self.hicon = None
        if self.arquivo_icone:
            self.hicon = _user32.LoadImageW(None, self.arquivo_icone, IMAGE_ICON, 0, 0,
                                            LR_LOADFROMFILE | LR_DEFAULTSIZE)
        if not self.hicon:
            self.hicon = _user32.LoadIconW(None, ctypes.c_void_p(IDI_APPLICATION))
        self._pendente_aviso = None
        self._icone(NIM_ADD)
        self._pronto.set()
        msg = wintypes.MSG()
        while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            _user32.TranslateMessage(ctypes.byref(msg))
            _user32.DispatchMessageW(ctypes.byref(msg))

    def _dados(self):
        nid = _NOTIFYICONDATAW()
        nid.cbSize = ctypes.sizeof(_NOTIFYICONDATAW)
        nid.hWnd = self.hwnd
        nid.uID = 1
        return nid

    def _icone(self, operacao):
        nid = self._dados()
        nid.uFlags = NIF_MESSAGE | NIF_ICON | NIF_TIP
        nid.uCallbackMessage = WM_BANDEJA
        nid.hIcon = self.hicon
        nid.szTip = self.dica[:127]
        _shell32.Shell_NotifyIconW(operacao, ctypes.byref(nid))

    def _menu(self):
        menu = _user32.CreatePopupMenu()
        _user32.AppendMenuW(menu, MF_STRING, ID_ABRIR, "Abrir Controlador MIDI")
        ativo = self.esta_ativo()
        _user32.AppendMenuW(menu, MF_STRING | (MF_CHECKED if ativo else 0), ID_ATIVO, "Funções ligadas")
        _user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
        _user32.AppendMenuW(menu, MF_STRING, ID_FECHAR, "Fechar (encerrar o programa)")
        _user32.SetMenuDefaultItem(menu, ID_ABRIR, 0)
        pt = wintypes.POINT()
        _user32.GetCursorPos(ctypes.byref(pt))
        _user32.SetForegroundWindow(self.hwnd)       # sem isso o menu não some ao clicar fora
        escolha = _user32.TrackPopupMenu(menu, TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_BOTTOMALIGN,
                                         pt.x, pt.y, 0, self.hwnd, None)
        _user32.PostMessageW(self.hwnd, WM_NULL, 0, 0)
        _user32.DestroyMenu(menu)
        if escolha == ID_ABRIR:
            self.ao_abrir()
        elif escolha == ID_ATIVO:
            self.ao_alternar_ativo()
        elif escolha == ID_FECHAR:
            self.ao_fechar()

    def _proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == WM_BANDEJA:
                evento = lparam & 0xFFFF
                if evento == WM_LBUTTONDBLCLK:
                    self.ao_abrir()
                elif evento in (WM_LBUTTONUP, WM_RBUTTONUP):
                    self._menu()
                return 0
            if msg == WM_ATUALIZAR and self._pendente_aviso:
                titulo, texto = self._pendente_aviso
                self._pendente_aviso = None
                nid = self._dados()
                nid.uFlags = NIF_INFO
                nid.szInfoTitle = titulo[:63]
                nid.szInfo = texto[:255]
                nid.dwInfoFlags = 0x1       # NIIF_INFO
                _shell32.Shell_NotifyIconW(NIM_MODIFY, ctypes.byref(nid))
                return 0
            if msg == self._msg_taskbar:    # o Explorer reiniciou: põe o ícone de volta
                self._icone(NIM_ADD)
                return 0
            if msg == WM_CLOSE:
                _user32.DestroyWindow(hwnd)
                return 0
            if msg == WM_DESTROY:
                _shell32.Shell_NotifyIconW(NIM_DELETE, ctypes.byref(self._dados()))
                _user32.PostQuitMessage(0)
                return 0
        except Exception:
            pass
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)
