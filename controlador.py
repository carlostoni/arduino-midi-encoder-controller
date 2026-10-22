"""Controlador MIDI — atribui funções às teclas e encoders do controlador Arduino.

Abre uma janela de configuração (servidor local na porta 8800). Enquanto ela estiver
aberta, apertar uma tecla do controlador executa a função escolhida.
"""
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import acoes
import icones
from midi_win import EntradaMIDI, listar_dispositivos

PORTA = 8800
# Como .exe (PyInstaller), os dados do usuário ficam ao lado do .exe (portátil de verdade)
# e a tela vem de dentro do pacote (sys._MEIPASS).
EMPACOTADO = getattr(sys, "frozen", False)
PASTA = os.path.dirname(sys.executable if EMPACOTADO else os.path.abspath(__file__))
PASTA_RECURSOS = getattr(sys, "_MEIPASS", PASTA)
ARQ_CONFIG = os.path.join(PASTA, "config.json")
ARQ_INDEX = os.path.join(PASTA_RECURSOS, "web", "index.html")
ARQ_LOG = os.path.join(PASTA, "erro.log")

PASTA_EXPORTADOS = os.path.join(PASTA, "Perfis exportados")
FORMATO_EXPORT = "controlador-midi-perfis"

# O aparelho tem 16 teclas + 4 knobs que também apertam: a matriz 5x4 do firmware
# manda 20 notas, e 4 delas são os botões dos knobs. Até o usuário calibrar,
# supõe a última fileira (17..20); o assistente "Calibrar" da tela corrige.
#
# O que é do APARELHO (layout, botoes, calibrado) é global; o que cada tecla FAZ
# fica nos perfis. Em memória, config["controles"] aponta para o perfil ativo.
CONFIG_PADRAO = {
    "dispositivo": "",
    "ativo": True,
    "selecionar_ao_apertar": False,   # apertar no controlador abre o painel daquela tecla
    "barra_volume": True,             # barra flutuante no canto da tela ao girar/apertar um encoder de volume
    "calibrado": False,
    "layout": [21, 22, 23, 24],   # CC do knob em cada posição física (cima-esq., cima-dir., baixo-meio, baixo-dir.)
    "botoes": {"cc:21": 17, "cc:22": 18, "cc:23": 19, "cc:24": 20},   # nota do botão de cada knob
    "invertidos": [],                 # CC dos knobs que giram ao contrário (valor vira 127 - valor)
    "teclas_invertidas": False,       # matriz montada ao contrário: nota 1..16 vira 17 - nota
    "perfil_ativo": "Padrão",
    "perfis": {
        "Padrão": {
            "cc:21": {"nome": "Volume geral", "tipo": "volume_sistema", "botao": {"tipo": "mudo_encoder"}},
            "cc:22": {"tipo": "nenhum", "botao": {"tipo": "mudo_encoder"}},
            "cc:23": {"tipo": "nenhum", "botao": {"tipo": "mudo_encoder"}},
            "cc:24": {"tipo": "nenhum", "botao": {"tipo": "mudo_encoder"}},
            "note:1": {"nome": "Play / pause", "tipo": "midia", "valor": "playpause"},
            "note:2": {"nome": "Próxima", "tipo": "midia", "valor": "next"},
            "note:3": {"nome": "Anterior", "tipo": "midia", "valor": "prev"},
            "note:4": {"nome": "Mudo", "tipo": "midia", "valor": "mute"},
        },
    },
}


# Funções de encoder que mexem num volume (valor absoluto do knob -> volume)
TIPOS_VOLUME = ("volume_sistema", "volume_app", "volume_microfone")


def _copia(obj):
    return json.loads(json.dumps(obj))


def _controles_validos(controles):
    """Filtra um perfil vindo de fora: só chaves 'note:N'/'cc:N' com dicionário."""
    if not isinstance(controles, dict):
        raise ValueError("perfil inválido")
    limpo = {}
    for k, v in controles.items():
        tipo, _, num = str(k).partition(":")
        if tipo in ("note", "cc") and num.isdigit() and isinstance(v, dict):
            v = _copia(v)
            if isinstance(v.get("botao"), dict):
                v["botao"].pop("nota", None)      # a nota do botão é do aparelho, não do perfil
            limpo[f"{tipo}:{int(num)}"] = v
    return limpo


def _nome_arquivo(nome):
    return "".join("_" if c in '<>:"/\\|?*' else c for c in nome).strip(" .") or "perfil"


class Controlador:
    def __init__(self):
        self.trava = threading.Lock()
        self.config = self._carregar()
        self.eventos = []          # últimos eventos p/ a tela acender as teclas
        self.seq = 0
        self.valores_cc = {}       # último valor recebido de cada CC
        self.ultimo_erro = ""
        self.mudos = {}            # {"cc:N": True} encoders cujo alvo está no mudo (risco vermelho na tela)
        self._reler_mudo = threading.Event()
        self.osd = None            # barra de volume flutuante (osd.Osd), ligada no main()
        self._osd_esperando = None # encoder cujo botão de mudo foi apertado: mostra a barra depois de ler o mudo
        self._osd_pendente = None
        self.executor = acoes.Executor(self._erro, self._depois_da_acao)
        self.midi = EntradaMIDI(self._ao_receber)
        self.midi.nome_desejado = self.config.get("dispositivo", "")
        threading.Thread(target=self._vigiar_mudo, daemon=True).start()

    # --- mudo dos encoders ---
    def _depois_da_acao(self, acao):
        if acao.get("tipo", "").startswith("mudo_"):
            self._osd_pendente, self._osd_esperando = self._osd_esperando, None
        if acao.get("tipo", "").startswith("mudo_") or acao.get("tipo") in ("saida_som", "midia"):
            self._reler_mudo.set()     # mostra o risco na hora, sem esperar a próxima leitura

    def _mostrar_osd(self, chave, valor=None):
        """Barra flutuante do encoder. Não aparece com a janela do programa em foco (lá já tem o knob)."""
        if not self.osd or not self.config.get("barra_volume", True):
            return
        janela = _hwnd_da_janela()
        if janela and _user32.GetForegroundWindow() == janela:
            return
        c = self.config["controles"].get(chave) or {}
        if valor is None:
            valor = self.valores_cc.get(chave)
        mic = c.get("tipo") == "volume_microfone"
        if valor is None and c.get("tipo") in ("volume_sistema", "volume_microfone"):
            try:     # knob ainda não mandou nada: mostra o volume real (aqui é a thread do mudo, com COM)
                valor = (acoes.volume_microfone(c.get("valor", "")) if mic else acoes.volume_sistema()) * 127
            except Exception:
                pass
        if mic:   # "Microfone (Samson C03U)" -> "Samson C03U"
            padrao = re.sub(r"^(Microfone|Microphone)\s*\((.+)\)$", r"\2", c.get("microfone") or "Microfone")
        elif c.get("tipo") == "volume_sistema":
            padrao = "Volume geral"
        else:
            padrao = (c.get("valor") or "Volume").replace(".exe", "")
        self.osd.mostrar({"nome": c.get("nome") or padrao, "pct": round((valor or 0) * 100 / 127),
                          "mudo": bool(self.mudos.get(chave)), "cor": c.get("cor"), "icone": c.get("icone", ""),
                          "icone_app": c.get("icone_app", ""), "mic": mic})

    def _vigiar_mudo(self):
        """Lê do Windows o mudo do que cada encoder controla (também pega mudo feito fora do app)."""
        acoes._ole32.CoInitializeEx(None, 0)
        while True:
            with self.trava:
                encoders = {k: (c.get("tipo"), c.get("valor", "")) for k, c in self.config["controles"].items()
                            if k.startswith("cc:") and c.get("tipo") in TIPOS_VOLUME}
            mudos = {}
            for k, (tipo, valor) in encoders.items():
                try:
                    if tipo == "volume_sistema":
                        mudo = acoes.esta_mudo_sistema()
                    elif tipo == "volume_microfone":
                        mudo = acoes.esta_mudo_microfone(valor)
                    else:
                        mudo = acoes.esta_mudo_apps(valor)
                    if mudo:
                        mudos[k] = True
                except Exception:
                    pass
            self.mudos = mudos
            if self._osd_pendente:
                pendente, self._osd_pendente = self._osd_pendente, None
                self._mostrar_osd(pendente)
            self._reler_mudo.wait(0.5)
            self._reler_mudo.clear()

    # --- configuração ---
    def _carregar(self):
        try:
            with open(ARQ_CONFIG, encoding="utf-8") as f:
                lido = json.load(f)
        except (OSError, ValueError):
            lido = {}
        cfg = {**_copia(CONFIG_PADRAO), **lido}
        if "perfis" not in lido:                  # config antiga, de antes dos perfis
            cfg["perfis"] = {"Padrão": lido.get("controles") or _copia(CONFIG_PADRAO["perfis"]["Padrão"])}
            cfg["perfil_ativo"] = "Padrão"
        if "botoes" not in lido and "controles" in lido:   # a nota do botão ficava dentro do controle
            cfg["botoes"] = {k: c["botao"]["nota"] for k, c in lido["controles"].items()
                             if k.startswith("cc:") and (c.get("botao") or {}).get("nota") is not None}
        cfg.pop("controles", None)
        cfg["perfis"] = {n: _controles_validos(c) for n, c in cfg["perfis"].items()} or {"Padrão": {}}
        if cfg.get("perfil_ativo") not in cfg["perfis"]:
            cfg["perfil_ativo"] = next(iter(cfg["perfis"]))
        cfg["controles"] = cfg["perfis"][cfg["perfil_ativo"]]
        return cfg

    def _gravar(self):
        """Grava o config.json (chamar com a trava)."""
        self.config["controles"] = self.config["perfis"][self.config["perfil_ativo"]]
        tmp = ARQ_CONFIG + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({k: v for k, v in self.config.items() if k != "controles"}, f, ensure_ascii=False, indent=2)
        os.replace(tmp, ARQ_CONFIG)

    def salvar(self, cfg):
        cfg = dict(cfg)
        with self.trava:
            # A tela diz de qual perfil são os controles: se o perfil foi trocado por uma
            # tecla no meio da edição, a gravação ainda vai para o perfil certo.
            destino = cfg.pop("perfil", None)
            if destino not in self.config["perfis"]:
                destino = self.config["perfil_ativo"]
            if "controles" in cfg:
                self.config["perfis"][destino] = _controles_validos(cfg.pop("controles"))
            cfg.pop("perfis", None)               # perfis só mudam pelas rotas de perfil
            cfg.pop("perfil_ativo", None)
            self.config.update(cfg)
            self._gravar()
        if "dispositivo" in cfg:
            self.midi.escolher(cfg["dispositivo"])

    # --- perfis ---
    def perfil(self, acao, nome="", novo=""):
        """Gerencia os perfis. Levanta ValueError com mensagem para a tela."""
        with self.trava:
            perfis = self.config["perfis"]
            novo = (novo or "").strip()
            if acao in ("criar", "duplicar", "renomear"):
                if not novo:
                    raise ValueError("Dê um nome ao perfil")
                if novo in perfis and not (acao == "renomear" and novo == nome):
                    raise ValueError(f"Já existe um perfil chamado “{novo}”")
            if acao != "criar" and nome not in perfis:
                raise ValueError(f"Perfil “{nome}” não existe")

            if acao == "trocar":
                self.config["perfil_ativo"] = nome
            elif acao == "criar":
                perfis[novo] = {}
                self.config["perfil_ativo"] = novo
            elif acao == "duplicar":
                perfis[novo] = _copia(perfis[nome])
                self.config["perfil_ativo"] = novo
            elif acao == "renomear":
                self.config["perfis"] = {(novo if n == nome else n): c for n, c in perfis.items()}
                if self.config["perfil_ativo"] == nome:
                    self.config["perfil_ativo"] = novo
            elif acao == "excluir":
                if len(perfis) == 1:
                    raise ValueError("Precisa sobrar pelo menos um perfil")
                del perfis[nome]
                if self.config["perfil_ativo"] == nome:
                    self.config["perfil_ativo"] = next(iter(perfis))
            else:
                raise ValueError("ação desconhecida")
            self._gravar()

    def _trocar_por_tecla(self, alvo):
        """Função de tecla 'perfil': vai para o perfil escolhido, ou para o próximo da lista."""
        nomes = list(self.config["perfis"])
        if alvo not in nomes:
            atual = nomes.index(self.config["perfil_ativo"])
            alvo = nomes[(atual + 1) % len(nomes)]
        self.perfil("trocar", alvo)

    def exportar(self, nomes):
        """Grava os perfis num .json em 'Perfis exportados' e mostra o arquivo no Explorer."""
        with self.trava:
            perfis = {n: _copia(self.config["perfis"][n]) for n in nomes if n in self.config["perfis"]}
        if not perfis:
            raise ValueError("Nenhum perfil para exportar")
        os.makedirs(PASTA_EXPORTADOS, exist_ok=True)
        base = _nome_arquivo(nomes[0]) if len(perfis) == 1 else "Todos os perfis"
        caminho = os.path.join(PASTA_EXPORTADOS, base + ".json")
        n = 2
        while os.path.exists(caminho):
            caminho = os.path.join(PASTA_EXPORTADOS, f"{base} ({n}).json")
            n += 1
        with open(caminho, "w", encoding="utf-8") as f:
            json.dump({"formato": FORMATO_EXPORT, "versao": 1, "perfis": perfis}, f, ensure_ascii=False, indent=2)
        subprocess.Popen(["explorer", "/select,", caminho])
        return caminho

    def importar(self, dados):
        """Adiciona os perfis de um arquivo exportado; nomes repetidos ganham ' (2)', ' (3)'..."""
        if not isinstance(dados, dict) or dados.get("formato") != FORMATO_EXPORT or not isinstance(dados.get("perfis"), dict):
            raise ValueError("Este arquivo não é um perfil exportado pelo Controlador MIDI")
        novos = []
        with self.trava:
            for nome, controles in dados["perfis"].items():
                nome = str(nome).strip() or "Importado"
                final, n = nome, 2
                while final in self.config["perfis"]:
                    final = f"{nome} ({n})"
                    n += 1
                self.config["perfis"][final] = _controles_validos(controles)
                novos.append(final)
            if novos:
                self._gravar()
        return novos

    def _erro(self, msg):
        self.ultimo_erro = f"{time.strftime('%H:%M:%S')} — {msg}"

    # --- MIDI chegando ---
    def _encoder_do_botao(self, nota):
        """Encoder ('cc:N') cujo botão de apertar foi ligado a essa nota, ou None."""
        for k, n in self.config.get("botoes", {}).items():
            if n == nota:
                return k
        return None

    @staticmethod
    def _acao_do_botao(encoder):
        """A ação do botão do encoder; 'mudo_encoder' vira o mudo do que o encoder controla."""
        botao = encoder.get("botao") or {}
        if botao.get("tipo") != "mudo_encoder":
            return botao
        if encoder.get("tipo") == "volume_sistema":
            return {"tipo": "mudo_sistema"}
        if encoder.get("tipo") == "volume_app":
            return {"tipo": "mudo_app", "valor": encoder.get("valor", "")}
        if encoder.get("tipo") == "volume_microfone":
            return {"tipo": "mudo_microfone", "valor": encoder.get("valor", "")}
        return {}

    def _ao_receber(self, tipo, numero, valor):
        with self.trava:
            # Correções do aparelho, antes de tudo: o resto do programa só vê o sinal já certo
            if tipo == "cc" and numero in self.config.get("invertidos", []):
                valor = 127 - valor
            elif tipo != "cc" and self.config.get("teclas_invertidas") and 1 <= numero <= 16:
                numero = 17 - numero
            chave = f"{'cc' if tipo == 'cc' else 'note'}:{numero}"
            dono = self._encoder_do_botao(numero) if tipo != "cc" else None
            self.seq += 1
            self.eventos.append({"seq": self.seq, "tipo": tipo, "chave": chave, "valor": valor, "dono": dono})
            del self.eventos[:-200]
            anterior = self.valores_cc.get(chave)
            if tipo == "cc":
                self.valores_cc[chave] = valor
            if dono:
                acao = self._acao_do_botao(self.config["controles"].get(dono) or {})
            else:
                acao = self.config["controles"].get(chave)
            ativo = self.config.get("ativo", True)
        if not ativo or not acao:
            return
        t = acao.get("tipo", "nenhum")
        if tipo == "cc" and t in TIPOS_VOLUME:
            self._mostrar_osd(chave, valor)
        elif tipo == "note_on" and dono and t.startswith("mudo_"):
            self._osd_esperando = dono
        if tipo == "note_on" and t == "perfil":
            try:
                self._trocar_por_tecla(acao.get("valor", ""))
            except ValueError as e:
                self._erro(str(e))
        elif tipo == "note_on" and t not in ("nenhum", "direcao", *TIPOS_VOLUME):
            self.executor.enviar(acao)
        elif tipo == "cc":
            if t in TIPOS_VOLUME:
                self.executor.enviar(acao, valor)
            elif t == "direcao" and anterior is not None and valor != anterior:
                lado = acao.get("direita" if valor > anterior else "esquerda") or {}
                if lado.get("tipo", "nenhum") != "nenhum":
                    self.executor.enviar(lado)

    def estado(self):
        with self.trava:
            return {
                "config": self.config,
                "dispositivos": listar_dispositivos(),
                "conectado": self.midi.conectado,
                "dispositivo_aberto": self.midi.nome_aberto,
                "erro_midi": self.midi.erro,
                "ultimo_erro": self.ultimo_erro,
                "valores_cc": self.valores_cc,
                "mudos": self.mudos,
                "seq": self.seq,
                "midia": acoes.MIDIA,
            }

    def eventos_desde(self, n):
        with self.trava:
            return {"seq": self.seq, "eventos": [e for e in self.eventos if e["seq"] > n],
                    "perfil_ativo": self.config["perfil_ativo"], "ativo": self.config.get("ativo", True),
                    "mudos": self.mudos,
                    "conectado": self.midi.conectado, "dispositivo_aberto": self.midi.nome_aberto,
                    "erro_midi": self.midi.erro, "ultimo_erro": self.ultimo_erro}


CTRL = None
MOSTRAR_JANELA = None     # abre a janela escondida na bandeja (quando o app é aberto de novo)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, dados, codigo=200):
        corpo = json.dumps(dados, ensure_ascii=False).encode("utf-8")
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def _corpo(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            with open(ARQ_INDEX, "rb") as f:
                corpo = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        elif url.path == "/api/estado":
            self._json(CTRL.estado())
        elif url.path == "/api/eventos":
            desde = int(parse_qs(url.query).get("desde", ["0"])[0])
            self._json(CTRL.eventos_desde(desde))
        elif url.path == "/api/apps-audio":
            self._json(self._com_em_thread("apps", acoes.listar_apps_audio))
        elif url.path == "/api/saidas-som":
            self._json(self._com_em_thread("saidas", acoes.listar_saidas))
        elif url.path == "/api/microfones":
            self._json(self._com_em_thread("microfones", acoes.listar_microfones))
        elif url.path == "/api/icone":     # ícone de um programa, em PNG
            corpo = icones.png(parse_qs(url.query).get("app", [""])[0])
            if not corpo:
                self._json({"erro": "ícone não encontrado"}, 404)
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Cache-Control", "max-age=3600")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
        else:
            self._json({"erro": "não encontrado"}, 404)

    @staticmethod
    def _com_em_thread(chave, funcao):
        """Roda `funcao` numa thread própria (o COM do áudio precisa ser iniciado nela)."""
        resultado = {}
        evento = threading.Event()

        def rodar():
            acoes._ole32.CoInitializeEx(None, 0)
            try:
                resultado[chave] = funcao()
            except Exception as e:
                resultado["erro"] = str(e)
            evento.set()
        threading.Thread(target=rodar, daemon=True).start()
        evento.wait(5)
        return resultado

    @staticmethod
    def _acao_teste_encoder(chave):
        return Controlador._acao_do_botao(CTRL.config["controles"].get(chave) or {})

    def do_POST(self):
        try:
            dados = self._corpo()
            if self.path == "/api/config":
                CTRL.salvar(dados)
                self._json({"ok": True})
            elif self.path == "/api/testar":
                acao = dados.get("acao") or {}
                if dados.get("encoder"):    # testar o botão de um encoder
                    acao = self._acao_teste_encoder(dados["encoder"])
                if acao.get("tipo") == "atalho":
                    acoes.interpretar_atalho(acao.get("valor", ""))   # valida antes
                if acao.get("tipo") == "perfil":
                    CTRL._trocar_por_tecla(acao.get("valor", ""))
                else:
                    time.sleep(float(dados.get("atraso", 0)))         # tempo p/ trocar de janela
                    CTRL.executor.enviar(acao, dados.get("valor"))
                self._json({"ok": True})
            elif self.path == "/api/mostrar":
                if MOSTRAR_JANELA:
                    threading.Thread(target=MOSTRAR_JANELA, daemon=True).start()
                self._json({"ok": bool(MOSTRAR_JANELA)})
            elif self.path == "/api/perfil":
                CTRL.perfil(dados.get("acao", ""), dados.get("nome", ""), dados.get("novo", ""))
                self._json({"ok": True, "config": CTRL.estado()["config"]})
            elif self.path == "/api/perfil/exportar":
                self._json({"ok": True, "caminho": CTRL.exportar(list(dados.get("nomes") or []))})
            elif self.path == "/api/perfil/importar":
                novos = CTRL.importar(dados.get("dados"))
                self._json({"ok": True, "novos": novos, "config": CTRL.estado()["config"]})
            elif self.path == "/api/simular":                          # p/ testar sem o controlador
                CTRL._ao_receber(dados["tipo"], int(dados["numero"]), int(dados.get("valor", 127)))
                self._json({"ok": True})
            else:
                self._json({"erro": "não encontrado"}, 404)
        except Exception as e:
            self._json({"erro": str(e)}, 400)


def porta_ocupada():
    with socket.socket() as s:
        return s.connect_ex(("127.0.0.1", PORTA)) == 0


def _log_erro(texto):
    """Sem console no .exe, os erros vão para erro.log ao lado dele."""
    try:
        with open(ARQ_LOG, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {texto}\n")
    except OSError:
        pass


def _aviso(texto):
    import ctypes
    ctypes.windll.user32.MessageBoxW(None, texto, "Controlador MIDI", 0x40)   # ícone de informação


def main():
    global CTRL
    url = f"http://127.0.0.1:{PORTA}"
    if porta_ocupada():
        try:     # já está aberto (talvez escondido na bandeja): pede para ele aparecer
            import urllib.request
            ctypes.windll.user32.AllowSetForegroundWindow(-1)   # deixa a outra cópia vir para a frente
            pedido = urllib.request.Request(url + "/api/mostrar", data=b"{}", method="POST")
            if json.load(urllib.request.urlopen(pedido, timeout=3)).get("ok"):
                return
        except Exception:
            pass
        if EMPACOTADO:
            _aviso("O Controlador MIDI já está aberto.\n\nProcure a janela dele na barra de tarefas.")
        else:
            print("O Controlador MIDI já está aberto — trazendo a tela.")
            webbrowser.open(url)
        return
    CTRL = Controlador()
    try:
        import osd
        CTRL.osd = osd.Osd()
        CTRL.osd.iniciar()
    except Exception as e:
        _log_erro(f"barra de volume indisponível: {e!r}")
    CTRL.midi.iniciar()
    servidor = ThreadingHTTPServer(("127.0.0.1", PORTA), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    print(f"Controlador MIDI rodando em {url}")

    if "--sem-janela" in sys.argv:
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
    else:
        abrir_com_bandeja(url, comecar_escondido="--minimizado" in sys.argv)
    CTRL.midi.parar()


import ctypes
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32")
_user32.ShowWindowAsync.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.IsIconic.argtypes = [wintypes.HWND]
_user32.IsWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
_ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
_user32.EnumWindows.argtypes = [_ENUMPROC, wintypes.LPARAM]
SW_HIDE, SW_SHOW, SW_RESTORE, WM_CLOSE = 0, 5, 9, 0x0010
_HWND_JANELA = [None]


def _hwnd_da_janela():
    """HWND da janela principal (a do pywebview) deste processo."""
    h = _HWND_JANELA[0]
    if h and _user32.IsWindow(h):
        return h
    pid, achado = os.getpid(), []

    def ver(hwnd, _):
        dono = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(dono))
        if dono.value == pid:
            titulo, classe = ctypes.create_unicode_buffer(256), ctypes.create_unicode_buffer(256)
            _user32.GetWindowTextW(hwnd, titulo, 256)
            _user32.GetClassNameW(hwnd, classe, 256)
            if titulo.value == "Controlador MIDI" and classe.value.startswith("WindowsForms"):
                achado.append(hwnd)
                return False
        return True

    _user32.EnumWindows(_ENUMPROC(ver), 0)
    _HWND_JANELA[0] = achado[0] if achado else None
    return _HWND_JANELA[0]


def abrir_com_bandeja(url, comecar_escondido=False):
    """Janela própria + ícone na bandeja. Minimizar ou fechar no X só esconde a janela
    (as teclas continuam funcionando); para encerrar, use "Fechar" no menu da bandeja."""
    from bandeja import Bandeja

    sair = threading.Event()
    estado = {"janela": None, "avisou": False}

    def alternar_ativo():
        CTRL.salvar({"ativo": not CTRL.config.get("ativo", True)})

    # Mostrar/esconder/fechar a janela vai por mensagens ASSÍNCRONAS do Windows (ctypes),
    # não pelos métodos do pywebview: aqueles esperam a thread da janela enquanto seguram
    # o Python, e a janela, por sua vez, espera o Python para avisar os eventos dela ->
    # as duas ficavam esperando uma pela outra e o programa congelava.
    def esconder():
        h = _hwnd_da_janela()
        if h:
            _user32.ShowWindowAsync(h, SW_HIDE)
        if not estado["avisou"]:
            estado["avisou"] = True
            bandeja.avisar("O Controlador MIDI continua ligado",
                           "As teclas seguem funcionando. Clique neste ícone para abrir ou fechar.")

    global MOSTRAR_JANELA

    def abrir():
        h = _hwnd_da_janela() if estado["janela"] is not None else None
        if not h:
            webbrowser.open(url)
            return
        _user32.ShowWindowAsync(h, SW_RESTORE if _user32.IsIconic(h) else SW_SHOW)
        _user32.SetForegroundWindow(h)

    def fechar():
        sair.set()
        h = _hwnd_da_janela() if estado["janela"] is not None else None
        if h:
            _user32.PostMessageW(h, WM_CLOSE, 0, 0)    # o evento closing vê `sair` e deixa fechar

    MOSTRAR_JANELA = abrir
    bandeja = Bandeja("Controlador MIDI", os.path.join(PASTA_RECURSOS, "icone.ico"),
                      ao_abrir=abrir, ao_fechar=fechar, ao_alternar_ativo=alternar_ativo,
                      esta_ativo=lambda: CTRL.config.get("ativo", True))
    bandeja.iniciar()
    try:
        import webview
        janela = webview.create_window("Controlador MIDI", url, width=1100, height=760,
                                       min_size=(380, 460), hidden=comecar_escondido)
        estado["janela"] = janela

        def ao_fechar_janela():
            if sair.is_set():
                return True
            esconder()           # assíncrono: pode chamar daqui mesmo
            return False

        janela.events.closing += ao_fechar_janela
        janela.events.minimized += esconder
        webview.start()
    except Exception as e:
        print(f"Janela própria indisponível ({e}); abrindo no navegador.")
        _log_erro(f"janela própria indisponível: {e!r}")
        estado["janela"] = None
        if not comecar_escondido:
            webbrowser.open(url)
        try:
            sair.wait()
        except KeyboardInterrupt:
            pass
    bandeja.parar()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        _log_erro(traceback.format_exc())
        if EMPACOTADO:
            _aviso(f"O Controlador MIDI fechou por um erro.\n\nDetalhes em:\n{ARQ_LOG}")
        raise
