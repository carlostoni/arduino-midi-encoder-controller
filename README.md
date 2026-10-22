# Arduino MIDI Encoder Controller

Controlador MIDI caseiro feito com um **Arduino Pro Micro**: 16 teclas e 4 encoders (knobs) que também apertam. Este repositório tem duas partes:

- **Firmware do Arduino**: faz as teclas e os knobs mandarem sinais MIDI.
- **Programa para Windows (Controlador MIDI)**: dá uma função a cada tecla e knob, como mídia, atalhos, volume geral, volume de programa ou do microfone, troca da saída de som e perfis.

<p>
 <img src="https://img.shields.io/badge/Arduino_IDE-00979D?style=for-the-badge&logo=arduino&logoColor=white" />
 <img src="https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white" />
 <img src="https://img.shields.io/badge/Windows-0078D6?style=for-the-badge&logo=windows&logoColor=white" />
</p>

## Download

**[⬇ Baixar o programa para Windows (.zip)](https://github.com/carlostoni/arduino-midi-encoder-controller/releases/latest)**

Não precisa instalar nada, nem o Python:

1. Extraia o `.zip`.
2. Abra `Controlador MIDI.exe`.
3. Na primeira vez, clique em **Calibrar agora**.

Se o Windows SmartScreen avisar "Aplicativo não reconhecido", clique em **Mais informações → Executar assim mesmo**. O programa não é assinado.

## Projeto montado
![midi](https://github.com/carlostoni/ArduinoMIDIEncoderController/assets/80012970/8bffcd88-4fce-4e25-b3d2-687adfa83afe)

---

## Hardware

### Materiais
- 1x Arduino Pro Micro
- 4x encoder EC11 (com botão)
- 16x push button de 2 pinos
- 8x resistor de 10k

### Ligações
| Parte | Pinos do Pro Micro |
|---|---|
| Encoders: canal A | 1, 20, 4, 18 |
| Encoders: canal B | 2, 21, 3, 19 |
| Matriz: linhas | 5, 6, 7, 8, 9 |
| Matriz: colunas | 15, 14, 16, 10 |

A matriz 5x4 junta as 16 teclas e os 4 botões dos knobs. Só o pino 0 fica livre.

![Esquema de ligação](https://github.com/carlostoni/ArduinoMIDIEncoderController/assets/80012970/971fbe5a-fd81-4997-93f9-2a67fd259edc)

### Firmware
O firmware atual fica em [`firmware/ControladorMIDI/ControladorMIDI.ino`](firmware/ControladorMIDI/ControladorMIDI.ino). Abra na Arduino IDE; ele precisa da biblioteca [Control Surface](https://github.com/tttapa/Control-Surface).

- **Matriz:** manda as **notas 1 a 20** no canal 1 (16 teclas + os 4 botões dos knobs).
- **Encoders:** mandam **CC 21 a 24** em valor absoluto (0 a 127, passo 3). Param ao chegar em 0 ou 127 e mandam 90 uma vez, 1,5 s depois de ligar.
- **Leitura dos encoders:** por máquina de estados de quadratura, que volta a zero a cada clique (detent) e tolera uma transição perdida.

As versões anteriores ficam em [`encoder_matriz/`](encoder_matriz/):

| Arquivo | Versão |
|---|---|
| `encoder_matriz_V1.ino` | V1: primeira versão, encoders de volume + matriz de botões |
| `midi_new_V2.ino`, `midi_new_V3.ino` | V2 e V3: encoders tratados num laço só, matriz em laço e constantes no lugar de números soltos |
| `4.0.ino`, `5.0` | Versões 4 e 5 |
| `ControladorMIDI6.0.ino` | Versão 6.0, igual ao firmware atual em `firmware/` |

---

## Programa para Windows

Sem dependências pesadas: o MIDI, o teclado, o áudio, a bandeja e a barra de volume usam a API do Windows direto, via `ctypes`. Só a janela usa o [pywebview](https://pywebview.flowrl.com/).

### O que dá para fazer

**Teclas**
- Mídia: tocar/pausar, próxima, anterior, mudo, volume.
- Atalho de teclado, com gravador.
- Abrir um programa, arquivo ou site.
- Digitar um texto ou rodar um comando.
- Trocar de perfil.
- Trocar a saída de som (monitor, fone, caixa...).

**Encoders (knobs)**
- Volume geral do Windows.
- Volume de um ou mais programas (`chrome.exe`, `spotify.exe`...).
- Volume do microfone: o padrão ou um microfone específico.
- Uma ação para cada lado do giro.
- Apertar o knob liga/desliga o mudo do que ele controla. A tela mostra um risco vermelho no knob.

**Tela e extras**
- Perfis: criar, duplicar, renomear, exportar e importar (`.json`).
- Cor e ícone de cada controle. O ícone pode ser um emoji ou o ícone do próprio programa.
- Barra de volume flutuante no canto da tela ao girar um knob com o programa minimizado.
- Fica na bandeja do Windows: fechar no X só esconde a janela.
- Calibração guiada: descobre a ordem dos knobs e qual sinal o botão de cada um manda.
- Ajustes do aparelho: inverter o sentido de um knob e inverter a ordem das teclas.

### Como rodar

Precisa do Windows 10/11 e do Python 3.12 ou mais novo.

```bash
pip install pywebview
python controlador.py
```

Também dá para abrir com `Abrir Controlador MIDI.bat`.

- A tela abre numa janela própria. Se o pywebview não estiver instalado, ela abre no navegador, em `http://127.0.0.1:8800`.
- Com `--sem-janela`, só o servidor sobe.
- Com `--minimizado`, o programa começa escondido na bandeja.

As configurações ficam em `config.json`, ao lado do programa. Esse arquivo é criado sozinho e fica fora do Git.

### Gerar o .exe portátil

```bash
pip install pyinstaller pywebview pythonnet
python -m PyInstaller portatil.spec --noconfirm --clean
```

O resultado vai para a pasta `dist/Controlador MIDI/`: o `.exe` e a pasta `_internal`. Ele roda sem Python instalado; para levar a outro PC, copie a pasta inteira.

Se o `pip` falhar por caminho longo no Windows, crie o ambiente virtual num caminho curto, como `%TEMP%\venv`.

### Arquivos

| Arquivo | O que faz |
|---|---|
| `controlador.py` | Servidor HTTP local (porta 8800), `config.json`, perfis e a ligação entre os eventos MIDI e as ações |
| `midi_win.py` | Entrada MIDI pelo `winmm.dll`, com reconexão automática |
| `acoes.py` | Teclado (SendInput), volume, mudo, microfones e troca de saída de som (Core Audio via COM) |
| `bandeja.py` | Ícone na bandeja do Windows |
| `osd.py` | Barra de volume flutuante (GDI+) |
| `icones.py` | Ícone de um `.exe` em PNG, para usar no lugar do emoji |
| `web/index.html` | A tela inteira (HTML, CSS e JS num arquivo só) |
| `portatil.spec` | Receita do PyInstaller para o `.exe` |
| `CLAUDE.md` | Notas técnicas detalhadas do projeto |
