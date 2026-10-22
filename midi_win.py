"""Leitura de MIDI pela API do próprio Windows (winmm.dll) — sem bibliotecas extras."""
import ctypes
import threading
import time
from ctypes import wintypes

_winmm = ctypes.WinDLL("winmm")

CALLBACK_FUNCTION = 0x30000
MIM_DATA = 0x3C3


class _MIDIINCAPSW(ctypes.Structure):
    _fields_ = [
        ("wMid", wintypes.WORD),
        ("wPid", wintypes.WORD),
        ("vDriverVersion", wintypes.UINT),
        ("szPname", wintypes.WCHAR * 32),
        ("dwSupport", wintypes.DWORD),
    ]


_MidiInProc = ctypes.WINFUNCTYPE(None, wintypes.HANDLE, wintypes.UINT,
                                 ctypes.c_size_t, ctypes.c_size_t, ctypes.c_size_t)

_winmm.midiInOpen.argtypes = [ctypes.POINTER(wintypes.HANDLE), wintypes.UINT,
                              _MidiInProc, ctypes.c_size_t, wintypes.DWORD]
_winmm.midiInStart.argtypes = [wintypes.HANDLE]
_winmm.midiInStop.argtypes = [wintypes.HANDLE]
_winmm.midiInReset.argtypes = [wintypes.HANDLE]
_winmm.midiInClose.argtypes = [wintypes.HANDLE]


def listar_dispositivos():
    """Nomes das entradas MIDI, na ordem do Windows (o índice é o id do dispositivo)."""
    nomes = []
    for i in range(_winmm.midiInGetNumDevs()):
        caps = _MIDIINCAPSW()
        if _winmm.midiInGetDevCapsW(i, ctypes.byref(caps), ctypes.sizeof(caps)) == 0:
            nomes.append(caps.szPname)
        else:
            nomes.append(f"Dispositivo {i}")
    return nomes


class EntradaMIDI:
    """Mantém um dispositivo MIDI aberto e reconecta sozinho quando ele é plugado de novo.

    `ao_receber(tipo, numero, valor)` é chamado para cada mensagem:
      tipo 'note_on' / 'note_off' / 'cc', numero = nota ou nº do CC, valor = 0..127.
    """

    def __init__(self, ao_receber):
        self.ao_receber = ao_receber
        self.nome_desejado = ""      # "" = primeiro dispositivo encontrado
        self.nome_aberto = None
        self.erro = ""
        self._handle = None
        self._callback = _MidiInProc(self._ao_chegar)  # referência viva enquanto aberto
        self._trava = threading.Lock()
        self._parar = threading.Event()

    # --- callback do Windows (roda em thread do driver: só repassa rápido) ---
    def _ao_chegar(self, _h, msg, _inst, p1, _p2):
        if msg != MIM_DATA:
            return
        status = p1 & 0xF0
        d1 = (p1 >> 8) & 0x7F
        d2 = (p1 >> 16) & 0x7F
        try:
            if status == 0x90:
                self.ao_receber("note_on" if d2 > 0 else "note_off", d1, d2)
            elif status == 0x80:
                self.ao_receber("note_off", d1, d2)
            elif status == 0xB0:
                self.ao_receber("cc", d1, d2)
        except Exception:
            pass

    @property
    def conectado(self):
        return self._handle is not None

    def escolher(self, nome):
        with self._trava:
            self.nome_desejado = nome or ""
            self._fechar()
        self._tentar_abrir()

    def _fechar(self):
        if self._handle is not None:
            _winmm.midiInStop(self._handle)
            _winmm.midiInReset(self._handle)
            _winmm.midiInClose(self._handle)
            self._handle = None
            self.nome_aberto = None

    def _tentar_abrir(self):
        with self._trava:
            nomes = listar_dispositivos()
            if self._handle is not None:
                if self.nome_aberto in nomes:
                    return
                self._fechar()          # foi desplugado
            if not nomes:
                self.erro = "Nenhum dispositivo MIDI encontrado. O controlador está plugado?"
                return
            if self.nome_desejado:
                if self.nome_desejado not in nomes:
                    self.erro = f"“{self.nome_desejado}” não está conectado."
                    return
                idx = nomes.index(self.nome_desejado)
            else:
                idx = 0
            h = wintypes.HANDLE()
            r = _winmm.midiInOpen(ctypes.byref(h), idx, self._callback, 0, CALLBACK_FUNCTION)
            if r != 0:
                self.erro = (f"Não consegui abrir “{nomes[idx]}” (erro {r}). "
                             "Outro programa (DAW, etc.) pode estar usando o controlador.")
                return
            _winmm.midiInStart(h)
            self._handle = h
            self.nome_aberto = nomes[idx]
            self.erro = ""

    def iniciar(self):
        def vigiar():
            while not self._parar.is_set():
                try:
                    self._tentar_abrir()
                except Exception as e:
                    self.erro = str(e)
                self._parar.wait(2)
        threading.Thread(target=vigiar, daemon=True).start()

    def parar(self):
        self._parar.set()
        with self._trava:
            self._fechar()
