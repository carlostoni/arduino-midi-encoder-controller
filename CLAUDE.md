# Controlador MIDI

Programa para Windows que dá funções às teclas e aos encoders de um controlador MIDI caseiro (Arduino Pro Micro). Ao abrir esta pasta numa conversa nova (por exemplo, em outro computador), este arquivo traz o contexto da conversa em que o projeto foi criado.

## O aparelho
- Caixa preta com **4 knobs (encoders) que também apertam** e **16 teclas 4x4**. As fileiras são, de cima para baixo: vermelha, azul, verde e amarela.
- Os knobs ficam em zigue-zague: cima-esq., cima-dir., baixo-meio, baixo-dir.
- O firmware fica em `firmware/ControladorMIDI/ControladorMIDI.ino` e usa a biblioteca Control_Surface.
  - Matriz 5x4 = notas 1..20 no canal 1, ou seja, 16 teclas + os 4 botões dos knobs.
  - Encoders = CC 21..24 em valor **absoluto** 0..127, com passo 3. Param de enviar ao chegar em 0 ou 127 e mandam 90 uma vez, 1,5 s após ligar.
  - O encoder volta a zero a cada detent (estado de repouso `11`) e tolera 1 transição perdida.
- Pinos: encoders A={1,20,4,18}, B={2,21,3,19}; linhas da matriz {5,6,7,8,9}, colunas {15,14,16,10}. Só o pino 0 está livre.

## Aparelho novo: 7x5 (23/10)
- Firmware, esquema elétrico e guia de montagem em `firmware/ControladorMIDI_7x5/`.
- Pro Micro + MCP23017 (I²C 0x20) + OLED SSD1306 128x64 (I²C 0x3C).
- Painel (2º desenho do usuário, 23/10):
  - à esquerda: o display em cima, 4 faders verticais e 4 botões redondos embaixo dos faders (`redondosNoLado`);
  - à direita: 5 knobs numa fileira e 25 pads 5x5;
  - tudo alinhado como no desenho: o display tem a altura do título + knobs, os faders a altura dos pads, e os botões redondos ficam na altura da última fileira de pads. É uma grade só (`.lado`/`.centro` com `display: contents`), e `--altura-pad` é medida em JS (`medirPad` + ResizeObserver). Na janela estreita (<760 px) o lado esquerdo vai para cima, sem alinhar;
  - cada botão redondo tem a função **"Mudo de um fader"** (`tipo: "mudo_fader"`, `valor` = "cc:30".."cc:33"). O padrão é o fader de cima (`faderDeCima`). O servidor resolve em `_acao_mudo_fader`, que dá o mudo do que o fader controla, e o OSD acompanha. Na tela o botão mostra "🔇 F1" e fica vermelho quando o fader está mudo;
  - o 5º botão redondo (nota 35) ficou dentro da caixa, desativado: `desativadas: [35]` no modelo (some da tela) e `NOTAS_DESATIVADAS` no servidor (ignorado).
- O que cada parte manda (canal 1):
  - knobs E1..E5 = CC 21..25 (A/B no MCP23017), com o botão de cada knob na linha 1 da matriz = notas 1..5;
  - pads = notas 6..30; botões redondos = notas 31..34 (a 35 está desativada);
  - faders F1..F4 = CC 30..33 (A0..A3, `CCPotentiometer`).
- O próprio Arduino escreve no OLED E1..E5 e P1..P4 (0..127). O PC não manda nada para o display.
- No programa, `config.modelo` escolhe o aparelho: `"original"` (padrão) ou `"7x5"`.
  - Tudo o que depende do hardware fica em `MODELOS` no `index.html`: encoders, notas, grade, redondos, faders, display, ordem visual, nomes das posições na calibração e botões padrão.
  - O seletor de modelo fica no topo. Trocar de modelo volta `layout` e `botoes` ao padrão daquele modelo. No 7x5, `calibrado` já fica true porque a fiação é documentada.
  - Se chegar um sinal que só o 7x5 manda (CC 25, CC 30..33 ou nota 21..35) com o modelo "original", a tela oferece trocar.
  - Faders: funções `TIPOS_FADER` (volume geral, de programa ou do microfone). Usam o mesmo caminho de volume dos knobs no servidor (qualquer CC com tipo em `TIPOS_VOLUME`) e aceitam "inverter o sentido" (`invertidos`).
  - Os pads ficam na grade 5x5; as notas livres depois da grade (31..35) são os botões redondos (`ehRedondo`).
  - A tela mostra uma imitação do OLED que acompanha os valores ao vivo.
  - `teclas_invertidas` vale só para o modelo original; o servidor também confere isso.

- **Dois programas separados** (pedido do usuário), mesmo código:
  - `Controlador MIDI - Portatil\` = o original. Foi regerado a partir do commit `e41ca42` do GitHub (o mesmo de antes do 7x5), porta 8800.
  - `Controlador MIDI 7x5 - Portatil\` = `portatil_7x5.spec`, que embute `edicoes/7x5/edicao.json` e o ícone próprio.
  - `edicao.json`: `titulo` (nome da janela, da bandeja e do .exe), `porta` (8801) e `padrao` (vai por cima do `CONFIG_PADRAO`: modelo 7x5, layout, botões e o perfil inicial com mídia nos pads 6..9 e volume geral no fader 1).
  - Com portas diferentes, os dois podem ficar abertos juntos. Cada um tem o seu `config.json`. Com os dois aparelhos plugados, escolha a entrada MIDI em cada um, porque "Automático" pega a primeira.
  - Para gerar: `python -m PyInstaller portatil_7x5.spec --noconfirm --clean --distpath <tmp>\dist --workpath <tmp>\build` e copie `dist\Controlador MIDI 7x5\` para a pasta Portatil do 7x5.

## O programa
- Para abrir: `Abrir Controlador MIDI.bat`. Ele roda `python controlador.py`, que abre uma janela pywebview (ou o navegador, se ela falhar) na porta **8800**.
- Com `--sem-janela`, só sobe o servidor (usado nos testes).
- **Não usa pacotes pip** (só o pywebview, para a janela). Todo o resto é API do Windows via ctypes:
  - `midi_win.py`: entrada MIDI pelo winmm.dll; tenta reconectar a cada 2 s.
  - `acoes.py`: teclado via SendInput, mais volume e mudo (geral ou por .exe) via Core Audio COM chamado direto pela vtable. Tem uma fila numa thread própria que junta os eventos de volume.
  - `controlador.py`: servidor HTTP, `config.json` e a ligação entre os eventos e as ações.
  - `web/index.html`: a tela inteira (HTML/CSS/JS num arquivo só, sem cache).
- Funções das teclas: mídia, atalho (com gravador), abrir programa/arquivo/site, digitar texto e rodar comando.
- Funções dos encoders: volume geral, volume de programa(s) por nome do .exe e "uma função para cada lado" (calcula o lado pela diferença entre dois valores seguidos).
- Botão do encoder: `controles["cc:N"].botao = {tipo, nota}`. O tipo `mudo_encoder` vira o mudo do que aquele encoder controla.
- **Calibrar**: assistente na tela. Para cada posição física, você gira o knob e depois aperta. O programa grava `layout` (o CC de cada posição), `botao.nota` e `calibrado`. As funções ficam desligadas durante a calibração. Antes de calibrar, o padrão supõe que as notas 17-20 são os botões dos knobs.
- Aparência por controle (fica no perfil, vai junto ao exportar): `cor` (#rrggbb, texto preto/branco automático) e `icone` (emoji). Fica na seção "🎨 Aparência na tela" do painel.
- Tela: knobs em zigue-zague e as teclas livres em 4x4 coloridas. O painel de função desliza da direita ao clicar num controle e recolhe ao clicar de novo, clicar fora, apertar Esc ou no ✕.
- "Selecionar ao apertar" (apertar no controlador abre o painel daquela tecla) vem **desligado** e fica gravado em `config.json` como `selecionar_ao_apertar` (22/10: o usuário achou incômodo o painel abrir sozinho). Não usar localStorage para isso: o pywebview roda em modo privado e esquece ao fechar.
- O número no knob da tela vai de 0 a 100 (`knobSVG` mostra `valor * 100 / 127`). O sinal continua 0..127 e o volume chega ao máximo; só a exibição mudou.
- Botão "🗑 Limpar tudo" no fim do painel: pede um 2º clique em até 3 s e volta o controle a `{tipo:"nenhum"}`, apagando nome, cor e ícone. No encoder, o botão continua como `mudo_encoder`.
- Função de tecla **"Trocar saída de som"** (`tipo: "saida_som"`, `valor` = id do aparelho, `saida` = nome, para achar de novo se o id mudar; sem os dois = próxima saída):
  - `acoes.listar_saidas()` usa IMMDeviceEnumerator.EnumAudioEndpoints e PKEY_Device_FriendlyName; a rota é `GET /api/saidas-som`.
  - `acoes.trocar_saida()` usa a interface interna **IPolicyConfig** (vtable 13 = SetDefaultEndpoint) nos papéis console, multimídia e chamadas.
  - No notebook: "LG ULTRAWIDE (NVIDIA High Definition Audio)", "Alto-falantes (UG-05)", 27G2G5, 22MP55, S/PDIF e "Alto-falantes (High Definition Audio Device)".
- **Risco vermelho de mudo no encoder**:
  - A thread `_vigiar_mudo` lê do Windows a cada 0,5 s o mudo do que cada encoder de volume controla (`esta_mudo_sistema` / `esta_mudo_apps`), e também logo após cada ação de mudo (`Executor(depois=...)`).
  - Guarda em `self.mudos` e manda em `/api/eventos`. A tela põe a classe `mudo` no knob, que mostra o `<line class="risco">` do `knobSVG`.
  - Por ler do Windows, o risco aparece também quando o mudo é feito fora do app.
- **Barra de volume flutuante** (`osd.py`, `config.barra_volume`, caixinha "Barra de volume na tela" no topo):
  - Janela nativa ctypes + GDI+, desenhada numa imagem 32 bits com alfa e mostrada por UpdateLayeredWindow. Não rouba o foco, o mouse atravessa e ela não vai para a barra de tarefas.
  - Fica a 24 px do canto de cima à esquerda da área de trabalho. Some depois de 1,5 s, esmaecendo.
  - Aparece ao girar um encoder de volume e ao apertar o botão de mudo dele. No mudo, ela espera o `_vigiar_mudo` ler o estado novo: `_osd_esperando` → `_depois_da_acao` → `_osd_pendente`.
  - Não aparece quando a janela do programa está em foco.
  - Mostra o ícone de alto-falante (Segoe Fluent Icons) ou o emoji do controle, este em uma cor só (o GDI+ não pinta emoji colorido), e a cor do controle.
  - Se o knob ainda não mandou valor, o volume geral é lido do Windows (`acoes.volume_sistema`).
- **Encoder "Volume do microfone"** (`tipo: "volume_microfone"`, `valor` = id do microfone, vazio = o padrão do Windows; `microfone` = nome):
  - `acoes._dispositivo(fluxo, id)` serve para saída (SAIDA) e microfone (ENTRADA); o microfone padrão usa o papel eConsole.
  - O botão do knob vira `mudo_microfone`; o risco vermelho e a barra flutuante (ícone de microfone) funcionam igual.
  - A rota é `GET /api/microfones`. `TIPOS_VOLUME` no controlador lista os tipos de encoder que são volume.
  - No notebook: Samson C03U (padrão), HD Pro Webcam C920 e UG-05.
- **Ícone de programa no lugar do emoji** (`icone_app` no controle, nome como "chrome.exe" ou caminho; tem prioridade sobre `icone`):
  - `icones.py` acha o .exe nesta ordem: programas abertos, registro App Paths, PATH e atalhos `.lnk` do Menu Iniciar.
  - Extrai o ícone de 64 px (PrivateExtractIcons, ou SHGetFileInfo para outros arquivos) e monta o PNG à mão com zlib, sem Pillow.
  - Guarda em cache; uma falha é tentada de novo depois de 20 s.
  - A rota é `GET /api/icone?app=...`. A barra flutuante desenha os mesmos pixels BGRA com GDI+.
  - Na tela, as sugestões são o ícone em uso, o programa do próprio controle (volume de programa / abrir) e os que estão tocando som.
  - As sugestões repetidas viram uma só por `chaveApp`, que tira aspas, pasta e .exe/.lnk: `"C:\...\chrome.exe"` = `chrome`.
  - O × de cada sugestão a esconde em `config.sugestoes_ocultas` (global). Se ela estava em uso, também tira o ícone do controle. O botão "↺ Mostrar escondidos" limpa a lista.
- Mudou só o `web/index.html`? No portátil basta copiar o arquivo para `_internal\web\` (não precisa regerar o .exe).
- **Correções do aparelho** (globais, fora dos perfis), aplicadas no começo de `_ao_receber`, antes de tudo:
  - `invertidos`: lista de CC dos knobs que giram ao contrário (o valor vira 127 - valor). Caixinha "Girar ao contrário" no painel do encoder.
  - `teclas_invertidas`: a nota 1..16 vira 17 - nota (as notas 17-20 dos botões dos knobs não mudam). Caixinha "Teclas na ordem inversa" no painel de qualquer tecla.
  - No aparelho real (22/10): E2 (CC 24) e E3 (CC 23) giravam ao contrário e a tecla física 1 mandava a nota 16, então os dois ajustes ficaram ligados no `config.json` do portátil.
- Regerar o .exe no notebook (usuário `carlo`, Python 3.12): o pip falha em pastas com caminho longo, então o venv fica em `%TEMP%\mbv` (`pip install pyinstaller pywebview pythonnet`) e o build em `%TEMP%\mbb`.
- **Perfis**:
  - No `config.json` ficam `perfis` (`{nome: controles}`) e `perfil_ativo`.
  - O que é do aparelho fica fora dos perfis e vale para todos: `layout`, `botoes` (`{"cc:N": nota}`) e `calibrado`.
  - Em memória, `config["controles"]` aponta para o perfil ativo e não é gravado no disco.
  - A barra de perfis na tela tem: trocar, novo, duplicar, renomear e excluir. Ela recolhe com ▲ e vira uma abinha "▼ Perfil: nome"; começa recolhida e lembra a escolha (localStorage).
  - **Exportar** grava em `Perfis exportados\` e abre o Explorer com o arquivo selecionado. Não usa diálogo nativo, porque eles já falharam nesta máquina.
  - **Importar** aceita escolher o arquivo ou arrastar o `.json` para a janela. Formato: `{"formato":"controlador-midi-perfis","versao":1,"perfis":{...}}`. Nomes repetidos ganham " (2)".
  - A função de tecla `perfil` troca para um perfil específico ou para o próximo da lista.
  - As gravações da tela levam `perfil`, para não cair no perfil errado se ele trocar por uma tecla no meio da edição.
- `POST /api/simular {tipo:'note_on'|'note_off'|'cc', numero, valor}` injeta um evento, para testar sem o aparelho.

## Situação
- Até agora tudo foi testado **só com eventos simulados**: o controlador não estava plugado no PC onde o projeto foi feito.
- O mudo e o volume reais do Windows foram testados.
- Ainda não confirmado no aparelho real:
  - se a ordem das teclas na tela bate com a física;
  - qual fileira da matriz são os botões dos knobs (a calibração resolve isso).
- Ideias pedidas ou oferecidas e ainda não feitas:
  - iniciar com o Windows (bandeja);
  - trocar de perfil sozinho conforme o programa em foco;
  - firmware em CC relativo (para "uma função para cada lado" não travar em 0/127);
  - layout configurável para um controlador futuro com mais botões, potenciômetros, faders e display (display = saída MIDI do PC para o Arduino).
- O usuário prefere apps locais em Python com servidor HTTP + janela própria, explicações em português e nada de dependências pesadas.

## Cópia para o GitHub
- Fica em `..\Controlador MIDI - GitHub\`: um clone de https://github.com/carlostoni/arduino-midi-encoder-controller, o repositório original do usuário (branch `main`).
  - As versões antigas do firmware ficam em `encoder_matriz/`.
  - O `.gitignore` deixa de fora `config.json`, `Perfis exportados\`, `erro.log`, `build\` e `dist\`.
- Ela **não é atualizada sozinha**. Depois de mudar o projeto, copie os arquivos alterados para lá, faça o commit e o push.

## Versão nativa (.exe portátil)
- Fica em `..\Controlador MIDI - Portatil\`, com `Controlador MIDI.exe`, `_internal\`, `firmware\` e `LEIA-ME.txt` (~27 MB).
- Roda sem Python instalado, sem console, numa janela pywebview (WebView2).
- **Bandeja** (`bandeja.py`, ctypes puro, sem pystray):
  - minimizar ou fechar no X só esconde a janela (o evento `closing` devolve False e o hide roda numa thread);
  - clicar no ícone abre o menu Abrir / Funções ligadas / Fechar; clique duplo abre direto;
  - abrir o app de novo chama `POST /api/mostrar` na cópia que já está rodando;
  - `--minimizado` começa escondido (pensado para iniciar com o Windows).
  - **IMPORTANTE (congelamento corrigido em 21/10):** NÃO mostrar/esconder/fechar a janela pelos métodos do pywebview (`hide()`, `show()`, `restore()`, `on_top`, `destroy()`) a partir de outras threads. Eles bloqueiam esperando a thread da janela enquanto seguram o Python, e a janela espera o Python para disparar os eventos dela: deadlock (travava no 3º ciclo de esconder/mostrar). Use `_hwnd_da_janela()` + `ShowWindowAsync`/`PostMessage(WM_CLOSE)` via ctypes, que são assíncronos.
- A tela é responsiva até ~380 px (`min_size` 380x460).
- Quando é .exe (`EMPACOTADO`):
  - `config.json`, `Perfis exportados\` e `erro.log` ficam ao lado do .exe;
  - a tela vem de `sys._MEIPASS/web`;
  - se o programa já estiver aberto, avisa com MessageBox.
- Para gerar de novo, dentro desta pasta (precisa de pyinstaller, pywebview e pythonnet):
  `python -m PyInstaller portatil.spec --noconfirm --clean --distpath <tmp>\dist --workpath <tmp>\build`
  Depois, copie `dist\Controlador MIDI\` para a pasta Portatil, mantendo `firmware\` e `LEIA-ME.txt`.
- O ícone é `icone.ico`, desenhado com Pillow: 2 knobs e teclas nas 4 cores.
