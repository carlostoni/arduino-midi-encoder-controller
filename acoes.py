"""O que cada tecla/encoder pode fazer: atalhos, mídia, abrir coisas, digitar texto e volume.

Tudo via API do Windows com ctypes — não precisa instalar nada.
"""
import ctypes
import os
import queue
import subprocess
import threading
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_ole32 = ctypes.WinDLL("ole32")

# ======================================================================
# TECLADO (SendInput)
# ======================================================================
ULONG_PTR = ctypes.c_size_t
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("ki", _KEYBDINPUT), ("mi", _MOUSEINPUT), ("hi", _HARDWAREINPUT)]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(_INPUT), ctypes.c_int]

TECLAS = {
    "ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12, "win": 0x5B,
    "enter": 0x0D, "esc": 0x1B, "escape": 0x1B, "tab": 0x09, "space": 0x20, "espaco": 0x20,
    "backspace": 0x08, "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23, "pageup": 0x21, "pagedown": 0x22,
    "up": 0x26, "down": 0x28, "left": 0x25, "right": 0x27,
    "printscreen": 0x2C, "capslock": 0x14, "pause": 0x13, "menu": 0x5D,
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
    "playpause": 0xB3, "next": 0xB0, "prev": 0xB1, "stop": 0xB2,
    "mute": 0xAD, "volup": 0xAF, "voldown": 0xAE,
}
TECLAS.update({f"f{i}": 0x6F + i for i in range(1, 25)})
TECLAS.update({f"num{i}": 0x60 + i for i in range(10)})
TECLAS.update({chr(c).lower(): c for c in range(ord("A"), ord("Z") + 1)})
TECLAS.update({str(i): 0x30 + i for i in range(10)})

# Teclas que o Windows exige marcar como "estendidas"
_ESTENDIDAS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2C, 0x2D, 0x2E, 0x5B, 0x5D,
               0xAD, 0xAE, 0xAF, 0xB0, 0xB1, 0xB2, 0xB3}

MIDIA = {
    "playpause": "Tocar / pausar",
    "next": "Próxima faixa",
    "prev": "Faixa anterior",
    "stop": "Parar",
    "mute": "Mudo (sistema)",
    "volup": "Volume +",
    "voldown": "Volume −",
}


def _tecla(vk, soltar=False):
    flags = (KEYEVENTF_KEYUP if soltar else 0) | (KEYEVENTF_EXTENDEDKEY if vk in _ESTENDIDAS else 0)
    i = _INPUT(type=INPUT_KEYBOARD)
    i.ki = _KEYBDINPUT(wVk=vk, wScan=0, dwFlags=flags, time=0, dwExtraInfo=0)
    return i


def _enviar(entradas):
    if entradas:
        arr = (_INPUT * len(entradas))(*entradas)
        _user32.SendInput(len(entradas), arr, ctypes.sizeof(_INPUT))


def interpretar_atalho(texto):
    """'Ctrl+Shift+M' -> [0x11, 0x10, 0x4D]. Levanta ValueError se tiver tecla desconhecida."""
    vks = []
    for parte in texto.replace(" ", "").split("+"):
        if not parte:
            continue
        vk = TECLAS.get(parte.lower())
        if vk is None:
            raise ValueError(f"Tecla desconhecida: {parte}")
        vks.append(vk)
    if not vks:
        raise ValueError("Atalho vazio")
    return vks


def apertar_atalho(texto):
    vks = interpretar_atalho(texto)
    _enviar([_tecla(v) for v in vks] + [_tecla(v, True) for v in reversed(vks)])


def digitar(texto):
    entradas = []
    for ch in texto.replace("\r\n", "\n"):
        if ch == "\n":
            entradas += [_tecla(0x0D), _tecla(0x0D, True)]
            continue
        dados = ch.encode("utf-16-le")
        for k in range(0, len(dados), 2):   # emojis viram 2 unidades (par substituto)
            u = int.from_bytes(dados[k:k + 2], "little")
            for solta in (0, KEYEVENTF_KEYUP):
                i = _INPUT(type=INPUT_KEYBOARD)
                i.ki = _KEYBDINPUT(wVk=0, wScan=u, dwFlags=KEYEVENTF_UNICODE | solta, time=0, dwExtraInfo=0)
                entradas.append(i)
    _enviar(entradas)


# ======================================================================
# ÁUDIO (Core Audio via COM "na unha")
# ======================================================================
class _GUID(ctypes.Structure):
    _fields_ = [("d1", wintypes.DWORD), ("d2", wintypes.WORD), ("d3", wintypes.WORD), ("d4", ctypes.c_ubyte * 8)]


def _guid(texto):
    g = _GUID()
    _ole32.CLSIDFromString(ctypes.c_wchar_p(texto), ctypes.byref(g))
    return g


CLSID_MMDeviceEnumerator = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
IID_IMMDeviceEnumerator = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
IID_IAudioEndpointVolume = _guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")
IID_IAudioSessionManager2 = _guid("{77AA99A0-1BD6-484F-8BC7-2C654C9A9B6F}")
IID_IAudioSessionControl2 = _guid("{BFB7FF88-7239-4FC9-8FA2-07C950BE9C6D}")
IID_ISimpleAudioVolume = _guid("{87CE5498-68D6-44E5-9215-6DA47EF883D8}")
CLSCTX_ALL = 0x17
# IPolicyConfig: interface interna do Windows (a do painel de Som) para trocar a saída padrão
CLSID_PolicyConfig = _guid("{870AF99C-171D-4F9E-AF0D-E63DF40C2BC9}")
IID_IPolicyConfig = _guid("{F8679F50-850A-41CF-9C72-430F290290C8}")


class _PROPERTYKEY(ctypes.Structure):
    _fields_ = [("fmtid", _GUID), ("pid", wintypes.DWORD)]


class _PROPVARIANT(ctypes.Structure):
    _fields_ = [("vt", ctypes.c_ushort), ("r1", wintypes.WORD), ("r2", wintypes.WORD), ("r3", wintypes.WORD),
                ("ptr", ctypes.c_void_p), ("extra", ctypes.c_void_p)]


PKEY_Device_FriendlyName = _PROPERTYKEY(_guid("{A45C254E-DF1C-4EFD-8020-67D146A850E0}"), 14)
VT_LPWSTR = 31
_ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
_ole32.PropVariantClear.argtypes = [ctypes.POINTER(_PROPVARIANT)]


def _com(obj, indice, *argtypes):
    """Método nº `indice` da vtable do objeto COM `obj` (HRESULT de erro vira OSError)."""
    vtbl = ctypes.cast(ctypes.c_void_p(obj), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    f = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtbl[indice])
    return lambda *a: f(obj, *a)


def _liberar(obj):
    if obj:
        vtbl = ctypes.cast(ctypes.c_void_p(obj), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(obj)


def _criar(clsid, iid):
    obj = ctypes.c_void_p()
    _ole32.CoCreateInstance(ctypes.byref(clsid), None, CLSCTX_ALL, ctypes.byref(iid), ctypes.byref(obj))
    if not obj.value:
        raise OSError("Não consegui acessar o áudio do Windows")
    return obj.value


SAIDA, ENTRADA = 0, 1    # eRender (alto-falantes) e eCapture (microfones)


def _dispositivo(fluxo=SAIDA, ident=""):
    """Aparelho de som pelo id; sem id, o padrão do Windows daquele fluxo."""
    enum = _criar(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    try:
        dev = ctypes.c_void_p()
        if ident:
            try:
                _com(enum, 5, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_void_p))(ident, ctypes.byref(dev))  # GetDevice
            except OSError:
                raise OSError("Aparelho de som não encontrado (desligado?)")
        else:
            # GetDefaultAudioEndpoint(fluxo, papel): eMultimedia=1 na saída, eConsole=0 no microfone
            _com(enum, 4, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
                fluxo, 1 if fluxo == SAIDA else 0, ctypes.byref(dev))
        return dev.value
    finally:
        _liberar(enum)


def _dispositivo_padrao():
    return _dispositivo(SAIDA)


def _ativar(dev, iid):
    obj = ctypes.c_void_p()
    _com(dev, 3, ctypes.POINTER(_GUID), wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p))(
        ctypes.byref(iid), CLSCTX_ALL, None, ctypes.byref(obj))
    return obj.value


def _qi(obj, iid):
    out = ctypes.c_void_p()
    _com(obj, 0, ctypes.POINTER(_GUID), ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(iid), ctypes.byref(out))
    return out.value


def _nome_processo(pid):
    if not pid:
        return ""
    h = _kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        tam = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(tam)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        _kernel32.CloseHandle(h)


_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                 ctypes.POINTER(wintypes.DWORD)]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def definir_volume_sistema(fracao):
    dev = _dispositivo_padrao()
    try:
        vol = _ativar(dev, IID_IAudioEndpointVolume)
        try:
            # SetMasterVolumeLevelScalar(float, LPCGUID)
            _com(vol, 7, ctypes.c_float, ctypes.c_void_p)(max(0.0, min(1.0, fracao)), None)
        finally:
            _liberar(vol)
    finally:
        _liberar(dev)


def _sessoes(funcao):
    """Chama funcao(nome_exe, sessao_control2) para cada sessão de áudio da saída padrão."""
    dev = _dispositivo_padrao()
    try:
        mgr = _ativar(dev, IID_IAudioSessionManager2)
        try:
            enum = ctypes.c_void_p()
            _com(mgr, 5, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(enum))
            try:
                n = ctypes.c_int()
                _com(enum.value, 3, ctypes.POINTER(ctypes.c_int))(ctypes.byref(n))
                for i in range(n.value):
                    ctl = ctypes.c_void_p()
                    _com(enum.value, 4, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(ctl))
                    try:
                        ctl2 = _qi(ctl.value, IID_IAudioSessionControl2)
                        try:
                            pid = wintypes.DWORD()
                            _com(ctl2, 14, ctypes.POINTER(wintypes.DWORD))(ctypes.byref(pid))
                            nome = _nome_processo(pid.value)
                            if nome:
                                funcao(nome, ctl2)
                        finally:
                            _liberar(ctl2)
                    except OSError:
                        pass
                    finally:
                        _liberar(ctl.value)
            finally:
                _liberar(enum.value)
        finally:
            _liberar(mgr)
    finally:
        _liberar(dev)


def _lista_nomes(texto):
    nomes = set()
    for n in texto.replace(";", ",").split(","):
        n = n.strip().lower()
        if n:
            nomes.add(n if n.endswith(".exe") else n + ".exe")
    return nomes


def definir_volume_apps(nomes_texto, fracao):
    alvo = _lista_nomes(nomes_texto)
    fracao = max(0.0, min(1.0, fracao))

    def ajustar(nome, ctl2):
        if nome in alvo:
            vol = _qi(ctl2, IID_ISimpleAudioVolume)
            try:
                _com(vol, 3, ctypes.c_float, ctypes.c_void_p)(fracao, None)   # SetMasterVolume
            finally:
                _liberar(vol)

    _sessoes(ajustar)


def alternar_mudo_sistema():
    dev = _dispositivo_padrao()
    try:
        vol = _ativar(dev, IID_IAudioEndpointVolume)
        try:
            mudo = wintypes.BOOL()
            _com(vol, 15, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(mudo))       # GetMute
            _com(vol, 14, wintypes.BOOL, ctypes.c_void_p)(not mudo.value, None)  # SetMute
        finally:
            _liberar(vol)
    finally:
        _liberar(dev)


def alternar_mudo_apps(nomes_texto):
    """Liga/desliga o mudo dos programas; todos seguem o estado da primeira sessão encontrada."""
    alvo = _lista_nomes(nomes_texto)
    novo = []

    def alternar(nome, ctl2):
        if nome in alvo:
            vol = _qi(ctl2, IID_ISimpleAudioVolume)
            try:
                if not novo:
                    mudo = wintypes.BOOL()
                    _com(vol, 6, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(mudo))   # GetMute
                    novo.append(not mudo.value)
                _com(vol, 5, wintypes.BOOL, ctypes.c_void_p)(novo[0], None)          # SetMute
            finally:
                _liberar(vol)

    _sessoes(alternar)


def volume_sistema():
    """Volume geral atual, de 0.0 a 1.0."""
    dev = _dispositivo_padrao()
    try:
        vol = _ativar(dev, IID_IAudioEndpointVolume)
        try:
            nivel = ctypes.c_float()
            _com(vol, 9, ctypes.POINTER(ctypes.c_float))(ctypes.byref(nivel))   # GetMasterVolumeLevelScalar
            return nivel.value
        finally:
            _liberar(vol)
    finally:
        _liberar(dev)


def esta_mudo_sistema():
    dev = _dispositivo_padrao()
    try:
        vol = _ativar(dev, IID_IAudioEndpointVolume)
        try:
            mudo = wintypes.BOOL()
            _com(vol, 15, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(mudo))   # GetMute
            return bool(mudo.value)
        finally:
            _liberar(vol)
    finally:
        _liberar(dev)


def esta_mudo_apps(nomes_texto):
    """Mudo da primeira sessão dos programas (o mesmo critério do alternar); None se nenhum toca."""
    alvo = _lista_nomes(nomes_texto)
    estado = []

    def ler(nome, ctl2):
        if nome in alvo and not estado:
            vol = _qi(ctl2, IID_ISimpleAudioVolume)
            try:
                mudo = wintypes.BOOL()
                _com(vol, 6, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(mudo))   # GetMute
                estado.append(bool(mudo.value))
            finally:
                _liberar(vol)

    _sessoes(ler)
    return estado[0] if estado else None


# --- microfone (volume de entrada) ---
def _volume_do(fluxo, ident, funcao):
    """Chama funcao(IAudioEndpointVolume) do aparelho e devolve o resultado."""
    dev = _dispositivo(fluxo, ident)
    try:
        vol = _ativar(dev, IID_IAudioEndpointVolume)
        try:
            return funcao(vol)
        finally:
            _liberar(vol)
    finally:
        _liberar(dev)


def _ler_mudo(vol):
    mudo = wintypes.BOOL()
    _com(vol, 15, ctypes.POINTER(wintypes.BOOL))(ctypes.byref(mudo))           # GetMute
    return bool(mudo.value)


def definir_volume_microfone(ident, fracao):
    _volume_do(ENTRADA, ident, lambda v: _com(v, 7, ctypes.c_float, ctypes.c_void_p)(
        max(0.0, min(1.0, fracao)), None))                                       # SetMasterVolumeLevelScalar


def alternar_mudo_microfone(ident):
    _volume_do(ENTRADA, ident, lambda v: _com(v, 14, wintypes.BOOL, ctypes.c_void_p)(not _ler_mudo(v), None))


def esta_mudo_microfone(ident):
    return _volume_do(ENTRADA, ident, _ler_mudo)


def volume_microfone(ident):
    def ler(v):
        nivel = ctypes.c_float()
        _com(v, 9, ctypes.POINTER(ctypes.c_float))(ctypes.byref(nivel))        # GetMasterVolumeLevelScalar
        return nivel.value
    return _volume_do(ENTRADA, ident, ler)


def listar_apps_audio():
    nomes = set()
    _sessoes(lambda nome, _ctl: nomes.add(nome))
    return sorted(nomes)


# --- saídas de som (alto-falante, fone, monitor/TV por HDMI...) ---
def _id_do(dev):
    p = ctypes.c_void_p()
    _com(dev, 5, ctypes.POINTER(ctypes.c_void_p))(ctypes.byref(p))      # IMMDevice::GetId
    try:
        return ctypes.wstring_at(p.value)
    finally:
        _ole32.CoTaskMemFree(p)


def _nome_do(dev):
    loja = ctypes.c_void_p()
    _com(dev, 4, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(0, ctypes.byref(loja))   # OpenPropertyStore(STGM_READ)
    try:
        pv = _PROPVARIANT()
        _com(loja.value, 5, ctypes.POINTER(_PROPERTYKEY), ctypes.POINTER(_PROPVARIANT))(
            ctypes.byref(PKEY_Device_FriendlyName), ctypes.byref(pv))                       # GetValue
        try:
            nome = ctypes.wstring_at(pv.ptr) if pv.vt == VT_LPWSTR and pv.ptr else ""
            return " ".join(nome.split()).replace(" )", ")")    # "Samson C03U      )" -> "Samson C03U)"
        finally:
            _ole32.PropVariantClear(ctypes.byref(pv))
    finally:
        _liberar(loja.value)


def listar_microfones():
    return listar_saidas(ENTRADA)


def listar_saidas(fluxo=SAIDA):
    """Aparelhos ligados (saídas ou, com ENTRADA, microfones): [{'id', 'nome', 'padrao'}],
    com o nome que aparece no Windows."""
    try:
        padrao = _dispositivo(fluxo)
        try:
            id_padrao = _id_do(padrao)
        finally:
            _liberar(padrao)
    except OSError:
        id_padrao = ""       # nenhum aparelho padrão (ex.: sem microfone)
    enum = _criar(CLSID_MMDeviceEnumerator, IID_IMMDeviceEnumerator)
    try:
        col = ctypes.c_void_p()
        # EnumAudioEndpoints(fluxo, DEVICE_STATE_ACTIVE=1)
        _com(enum, 3, ctypes.c_int, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p))(fluxo, 1, ctypes.byref(col))
        try:
            n = ctypes.c_uint()
            _com(col.value, 3, ctypes.POINTER(ctypes.c_uint))(ctypes.byref(n))
            saidas = []
            for i in range(n.value):
                dev = ctypes.c_void_p()
                _com(col.value, 4, ctypes.c_uint, ctypes.POINTER(ctypes.c_void_p))(i, ctypes.byref(dev))
                try:
                    ident = _id_do(dev.value)
                    saidas.append({"id": ident, "nome": _nome_do(dev.value), "padrao": ident == id_padrao})
                finally:
                    _liberar(dev.value)
            return saidas
        finally:
            _liberar(col.value)
    finally:
        _liberar(enum)


def trocar_saida(ident, nome=""):
    """Faz a saída virar a padrão do Windows (som, multimídia e chamadas).

    Procura pelo id; se ele mudou (driver reinstalado), pelo nome. Sem id nem nome = próxima da lista.
    """
    saidas = listar_saidas()
    if not saidas:
        raise OSError("Nenhuma saída de som ligada")
    alvo = next((s for s in saidas if ident and s["id"] == ident), None) \
        or next((s for s in saidas if nome and s["nome"].lower() == nome.lower()), None)
    if alvo is None and (ident or nome):
        raise OSError(f"Saída de som não encontrada (desligada?): {nome or ident}")
    if alvo is None:
        atual = next((i for i, s in enumerate(saidas) if s["padrao"]), -1)
        alvo = saidas[(atual + 1) % len(saidas)]
    pol = _criar(CLSID_PolicyConfig, IID_IPolicyConfig)
    try:
        for papel in (0, 1, 2):   # eConsole, eMultimedia, eCommunications
            _com(pol, 13, ctypes.c_wchar_p, ctypes.c_int)(alvo["id"], papel)   # SetDefaultEndpoint
    finally:
        _liberar(pol)
    return alvo["nome"]


# ======================================================================
# EXECUÇÃO
# ======================================================================
def executar(acao, valor=None):
    """Executa uma ação de tecla ({'tipo','valor'}) ou de volume (com valor MIDI 0..127)."""
    tipo = (acao or {}).get("tipo", "nenhum")
    alvo = (acao or {}).get("valor", "")
    if tipo == "atalho":
        apertar_atalho(alvo)
    elif tipo == "midia":
        apertar_atalho(alvo)
    elif tipo == "abrir":
        os.startfile(alvo.strip().strip('"'))
    elif tipo == "texto":
        digitar(alvo)
    elif tipo == "comando":
        subprocess.Popen(alvo, shell=True, creationflags=subprocess.CREATE_NO_WINDOW)
    elif tipo == "volume_sistema":
        definir_volume_sistema((valor if valor is not None else 127) / 127)
    elif tipo == "volume_app":
        definir_volume_apps(alvo, (valor if valor is not None else 127) / 127)
    elif tipo == "mudo_sistema":
        alternar_mudo_sistema()
    elif tipo == "mudo_app":
        alternar_mudo_apps(alvo)
    elif tipo == "volume_microfone":
        definir_volume_microfone(alvo, (valor if valor is not None else 127) / 127)
    elif tipo == "mudo_microfone":
        alternar_mudo_microfone(alvo)
    elif tipo == "saida_som":
        trocar_saida(alvo, acao.get("saida", ""))


class Executor:
    """Fila numa thread própria (o COM precisa ser iniciado nela).

    Se o encoder gira rápido, junta os pedidos de volume e aplica só o último de cada alvo.
    """

    def __init__(self, ao_erro=None, depois=None):
        self.fila = queue.Queue()
        self.ao_erro = ao_erro or (lambda msg: None)
        self.depois = depois or (lambda acao: None)   # avisado depois de cada ação feita
        threading.Thread(target=self._rodar, daemon=True).start()

    def enviar(self, acao, valor=None):
        self.fila.put((acao, valor))

    def _rodar(self):
        _ole32.CoInitializeEx(None, 0)
        while True:
            pendentes = [self.fila.get()]
            while not self.fila.empty():
                pendentes.append(self.fila.get_nowait())
            ultimo_volume = {}
            for i, (acao, _v) in enumerate(pendentes):
                if acao.get("tipo", "").startswith("volume_"):
                    ultimo_volume[(acao["tipo"], acao.get("valor", ""))] = i
            for i, (acao, valor) in enumerate(pendentes):
                chave = (acao.get("tipo", ""), acao.get("valor", ""))
                if chave in ultimo_volume and ultimo_volume[chave] != i:
                    continue
                try:
                    executar(acao, valor)
                except Exception as e:
                    self.ao_erro(f"{acao.get('tipo')}: {e}")
                self.depois(acao)
