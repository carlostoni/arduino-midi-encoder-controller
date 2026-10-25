"""Iniciar junto com o Windows.

Um valor em HKCU\\...\\CurrentVersion\\Run com o nome do programa: vale só para o usuário
e não pede administrador. O programa abre escondido na bandeja (--minimizado).
O Windows também tem um liga/desliga próprio para isso (Configurações > Aplicativos >
Inicialização), guardado em StartupApproved: ele é respeitado na leitura e limpo ao ligar.
"""
import os
import sys
import winreg

CHAVE_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"
CHAVE_APROVADO = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


def comando():
    """Linha que o Windows roda ao entrar: o .exe (ou o Python + o script) já escondido na bandeja."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --minimizado'
    pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")   # sem janela preta
    if not os.path.isfile(pythonw):
        pythonw = sys.executable
    return f'"{pythonw}" "{os.path.abspath(sys.argv[0])}" --minimizado'


def _ler(chave, nome):
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, chave) as k:
            return winreg.QueryValueEx(k, nome)[0]
    except OSError:
        return None


def _desligado_nas_configuracoes(nome):
    """No StartupApproved, o 1º byte ímpar (3, 7...) quer dizer desligado pelo usuário no Windows."""
    valor = _ler(CHAVE_APROVADO, nome)
    return isinstance(valor, bytes) and len(valor) > 0 and valor[0] & 1 == 1


def ligado(nome):
    return _ler(CHAVE_RUN, nome) is not None and not _desligado_nas_configuracoes(nome)


def definir(nome, ligar):
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, CHAVE_RUN, 0, winreg.KEY_SET_VALUE) as k:
        if ligar:
            winreg.SetValueEx(k, nome, 0, winreg.REG_SZ, comando())
        else:
            try:
                winreg.DeleteValue(k, nome)
            except FileNotFoundError:
                pass
    try:   # tira o "desligado" das Configurações do Windows, senão ele continuaria sem abrir
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, CHAVE_APROVADO, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, nome)
    except OSError:
        pass


def corrigir_caminho(nome):
    """Se a pasta do programa mudou de lugar, aponta o início automático para o lugar novo."""
    atual = _ler(CHAVE_RUN, nome)
    if atual is not None and atual != comando() and not _desligado_nas_configuracoes(nome):
        definir(nome, True)
