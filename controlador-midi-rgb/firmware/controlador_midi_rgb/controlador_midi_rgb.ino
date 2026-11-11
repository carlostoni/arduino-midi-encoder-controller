#include <Control_Surface.h>
#include <Wire.h>
#include <U8x8lib.h>

// =====================================================================
// Controlador MIDI RGB: Arduino Pro Micro + MCP23017 + PCA9685 + OLED
// ---------------------------------------------------------------------
// Pro Micro (18 I/O, todos usados):
//   I2C (MCP23017, PCA9685, OLED) -> 2 (SDA), 3 (SCL)
//   Faders                        -> A0 (18), A1 (19), A2 (20), A3 (21)
//   Matriz 6x5 - linhas           -> 1, 4, 5, 6, 7, 8
//   Matriz 6x5 - colunas          -> 9, 10, 14, 15, 16
//   Botão do encoder 5 (SW5)      -> 0
//
// MCP23017 (endereço 0x20):
//   Encoder n: A = GPA n, B = GPB n   (n = 0..4)
//   SW1 = GPA5, SW2 = GPA6, SW3 = GPB5, SW4 = GPB6
//   GPA7/GPB7 livres (somente saída nas revisões atuais do chip)
//
// PCA9685 (endereço 0x40) -> LEDs RGB dos encoders
//   Encoder n: R = canal 3n, G = canal 3n+1, B = canal 3n+2  (canais 0..14)
//   Canal 15 livre
//
// OLED SSD1306 128x64 (endereço 0x3C), modo texto U8x8
//
// MIDI (canal 1):
//   Botões dos encoders -> notas 1..5
//   Matriz 6x5          -> notas 6..35
//   Encoders            -> CC 21..25
//   Faders              -> CC 30..33
//
// Bibliotecas: Control Surface e U8g2.
// O MCP23017 e o PCA9685 são acessados direto pelo Wire, sem biblioteca,
// para o programa caber na memória do ATmega32U4.
// =====================================================================

// ===============================
// CONFIGURAÇÃO DO SEU HARDWARE
// ===============================

// Encoder EC12 com 12 pulsos e 24 cliques por volta = 2 transições por clique.
// Se o valor andar 2 vezes por clique, troque para 4.
constexpr int8_t pulsesPerDetent = 2;

// LED RGB do encoder:
//   true  = ânodo comum (perna comum no 5V; cada cor vai para a saída do PCA9685)
//   false = cátodo comum (perna comum no GND)
constexpr bool LED_COMMON_ANODE = true;

// Botão do encoder:
//   true  = o botão fecha contra o 5V (comum do LED). Precisa de resistor
//           de 10 kΩ do pino para o GND (pull-down).
//   false = o botão fecha contra o GND. Usa o pull-up interno, sem resistor.
constexpr bool SW_ACTIVE_HIGH = true;

// Como o LED acompanha o giro:
//   0 = a cor muda com o valor: vermelho (0) -> amarelo -> verde -> ciano -> azul (127)
//   1 = cada encoder tem uma cor fixa e o brilho acompanha o valor
constexpr uint8_t LED_MODE = 0;

// Brilho máximo dos LEDs (0..4095). Mais baixo = menos consumo e menos ofuscante.
constexpr uint16_t LED_MAX = 2500;

// Cores fixas do modo 1 (matiz em graus: 0 vermelho, 60 amarelo, 120 verde,
// 180 ciano, 240 azul, 300 magenta)
constexpr uint16_t fixedHue[] = {0, 40, 120, 200, 280};

// Ao apertar o botão do encoder, o LED fica branco enquanto estiver apertado.
constexpr bool FLASH_ON_PRESS = true;

// ===============================
// Interface MIDI USB
// ===============================
USBMIDI_Interface midi;

// ===============================
// OLED
// ===============================
U8X8_SSD1306_128X64_NONAME_HW_I2C u8x8(U8X8_PIN_NONE);
// Display de 1,3" (SH1106): use esta linha no lugar da de cima
// U8X8_SH1106_128X64_NONAME_HW_I2C u8x8(U8X8_PIN_NONE);

// ===============================
// Acesso direto aos chips I2C
// ===============================
constexpr uint8_t MCP_ADDR = 0x20;
constexpr uint8_t PCA_ADDR = 0x40;

bool i2cPresent(uint8_t addr) {
  Wire.beginTransmission(addr);
  return Wire.endTransmission() == 0;
}

void i2cWrite8(uint8_t addr, uint8_t reg, uint8_t val) {
  Wire.beginTransmission(addr);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

// MCP23017 (IOCON.BANK = 0)
constexpr uint8_t MCP_GPPUA = 0x0C;
constexpr uint8_t MCP_GPPUB = 0x0D;
constexpr uint8_t MCP_GPIOA = 0x12;

// Lê GPIOA e GPIOB de uma vez: GPA nos bits 0..7, GPB nos bits 8..15
uint16_t mcpReadAB() {
  Wire.beginTransmission(MCP_ADDR);
  Wire.write(MCP_GPIOA);
  if (Wire.endTransmission(false) != 0) return 0xFFFF;
  if (Wire.requestFrom(MCP_ADDR, (uint8_t)2) != 2) return 0xFFFF;
  uint8_t a = Wire.read();
  uint8_t b = Wire.read();
  return a | (uint16_t(b) << 8);
}

// PCA9685
constexpr uint8_t PCA_MODE1    = 0x00;
constexpr uint8_t PCA_MODE2    = 0x01;
constexpr uint8_t PCA_LED0     = 0x06;
constexpr uint8_t PCA_PRESCALE = 0xFE;

void pcaBegin() {
  i2cWrite8(PCA_ADDR, PCA_MODE1, 0x10);   // dormir para poder mudar a frequência
  i2cWrite8(PCA_ADDR, PCA_PRESCALE, 5);   // ~1 kHz: sem cintilação
  i2cWrite8(PCA_ADDR, PCA_MODE1, 0x20);   // acordar, auto-incremento ligado
  delay(1);
  // OUTDRV = totem pole. INVRT = 1 quando o LED vai com o catodo na saída
  // (ânodo comum): a saída vai a LOW para acender.
  i2cWrite8(PCA_ADDR, PCA_MODE2, LED_COMMON_ANODE ? 0x14 : 0x04);
}

// Escreve os 3 canais de um LED RGB numa única transmissão (valores 0..4095)
void pcaWriteRGB(uint8_t led, uint16_t r, uint16_t g, uint16_t b) {
  const uint16_t v[3] = {r, g, b};
  Wire.beginTransmission(PCA_ADDR);
  Wire.write(PCA_LED0 + 4 * (3 * led));
  for (uint8_t c = 0; c < 3; c++) {
    uint16_t on = 0, off = v[c];
    if (v[c] == 0)         { off = 0x1000; }          // totalmente apagado
    else if (v[c] >= 4095) { on = 0x1000; off = 0; }  // totalmente aceso
    Wire.write(on & 0xFF);
    Wire.write(on >> 8);
    Wire.write(off & 0xFF);
    Wire.write(off >> 8);
  }
  Wire.endTransmission();
}

bool mcpOk = false;
bool pcaOk = false;

// ===============================
// ENCODERS (giro no MCP23017)
// ===============================
constexpr uint8_t numEncoders = 5;
constexpr uint8_t ccNumber[numEncoders] = {21, 22, 23, 24, 25};

constexpr int8_t  step          = 3;     // passo por clique
constexpr uint8_t restState     = 0b11;  // estado parado no clique (pull-up)
constexpr uint8_t initialVolume = 90;

uint8_t prevState[numEncoders];
int8_t  accum[numEncoders] = {0};
uint8_t volume[numEncoders];

const int8_t transitionTable[4][4] = {
  { 0, -1,  1,  0},  // prev 00
  { 1,  0,  0, -1},  // prev 01
  {-1,  0,  0,  1},  // prev 10
  { 0,  1, -1,  0}   // prev 11
};

inline uint8_t readEncoderState(uint8_t i, uint16_t gpio) {
  uint8_t a = (gpio >> i) & 1;
  uint8_t b = (gpio >> (8 + i)) & 1;
  return (a << 1) | b;
}

inline bool isRestState(uint8_t state) {
  return state == restState ||
         (pulsesPerDetent == 2 && state == (restState ^ 0b11));
}

// ===============================
// BOTÕES DOS ENCODERS
// ===============================
// Bits do MCP (GPA nos bits 0..7, GPB nos bits 8..15). 255 = pino do Pro Micro.
constexpr uint8_t swBit[numEncoders] = {5, 6, 13, 14, 255};
constexpr uint8_t SW5_PIN = 0;
constexpr uint8_t firstSwNote = 1;          // notas 1..5
constexpr unsigned long DEBOUNCE_MS = 10;

bool swState[numEncoders]   = {false};      // estável: true = apertado
bool swLastRaw[numEncoders] = {false};
unsigned long swChanged[numEncoders] = {0};

// ===============================
// LEDs RGB
// ===============================
uint8_t ledDirty = 0;                       // 1 bit por encoder
inline void markLed(uint8_t i) { ledDirty |= (1 << i); }

// Converte matiz (0..359) e nível (0..4095) em R, G, B
void hueToRGB(uint16_t hue, uint16_t level, uint16_t &r, uint16_t &g, uint16_t &b) {
  uint8_t  sector = hue / 60;
  uint16_t up     = (uint32_t)(hue % 60) * level / 60;
  uint16_t down   = level - up;
  switch (sector) {
    case 0:  r = level; g = up;    b = 0;     break;  // vermelho -> amarelo
    case 1:  r = down;  g = level; b = 0;     break;  // amarelo -> verde
    case 2:  r = 0;     g = level; b = up;    break;  // verde -> ciano
    case 3:  r = 0;     g = down;  b = level; break;  // ciano -> azul
    case 4:  r = up;    g = 0;     b = level; break;  // azul -> magenta
    default: r = level; g = 0;     b = down;  break;  // magenta -> vermelho
  }
}

void showLed(uint8_t i) {
  uint16_t r, g, b;
  if (FLASH_ON_PRESS && swState[i]) {
    r = g = b = LED_MAX;                                    // branco
  } else if (LED_MODE == 0) {
    uint16_t hue = (uint16_t)volume[i] * 240 / 127;   // 0 vermelho .. 240 azul
    hueToRGB(hue, LED_MAX, r, g, b);
  } else {
    // brilho com curva quadrática (parece linear ao olho), com um mínimo aceso
    uint32_t lvl = (uint32_t)LED_MAX * volume[i] * volume[i] / (127UL * 127UL);
    if (lvl < LED_MAX / 40) lvl = LED_MAX / 40;
    hueToRGB(fixedHue[i], (uint16_t)lvl, r, g, b);
  }
  pcaWriteRGB(i, r, g, b);
}

// ===============================
// FADERS (no Pro Micro)
// ===============================
CCPotentiometer pots[] = {
  {A0, {30, Channel_1}},
  {A1, {31, Channel_1}},
  {A2, {32, Channel_1}},
  {A3, {33, Channel_1}},
};
constexpr uint8_t numPots = sizeof(pots) / sizeof(pots[0]);
uint8_t potShown[numPots];

// ===============================
// MATRIZ 6x5 (no Pro Micro)
// ===============================
const AddressMatrix<6, 5> addresses = {{
  { 6,  7,  8,  9, 10},   // pads, 1ª fileira
  {11, 12, 13, 14, 15},
  {16, 17, 18, 19, 20},
  {21, 22, 23, 24, 25},
  {26, 27, 28, 29, 30},   // pads, 5ª fileira
  {31, 32, 33, 34, 35},   // botões de baixo
}};

NoteButtonMatrix<6, 5> buttonmatrix = {
  {1, 4, 5, 6, 7, 8},     // linhas
  {9, 10, 14, 15, 16},    // colunas
  addresses,
  Channel_1,
};

// ===============================
// TELA
// ===============================
constexpr uint8_t numItems = numEncoders + numPots;
uint16_t dirty = 0;
unsigned long lastDraw = 0;
constexpr unsigned long DRAW_INTERVAL = 15;

inline void markDirty(uint8_t item) { dirty |= (1u << item); }

// Monta "E1: 90" sem snprintf (economiza ~1,5 KB de memória de programa)
void drawItem(uint8_t item) {
  char buf[7];
  bool enc = item < numEncoders;
  uint8_t n = enc ? item : item - numEncoders;
  uint8_t v = enc ? volume[n] : potShown[n];
  buf[0] = enc ? 'E' : 'P';
  buf[1] = '1' + n;
  buf[2] = ':';
  buf[3] = v >= 100 ? '0' + v / 100 : ' ';
  buf[4] = v >= 10 ? '0' + (v / 10) % 10 : ' ';
  buf[5] = '0' + v % 10;
  buf[6] = '\0';
  u8x8.drawString(enc ? 0 : 9, 2 + n, buf);
}

// A cada volta do loop escreve no máximo 1 item na tela ou 1 LED,
// para o I2C não atrasar a leitura dos encoders.
unsigned long lastLed = 0;
constexpr unsigned long LED_INTERVAL = 4;

void updateOutputs() {
  unsigned long now = millis();
  if (ledDirty && pcaOk && now - lastLed >= LED_INTERVAL) {
    for (uint8_t i = 0; i < numEncoders; i++) {
      if (ledDirty & (1 << i)) {
        showLed(i);
        ledDirty &= ~(1 << i);
        lastLed = now;
        return;
      }
    }
  }
  if (!dirty || now - lastDraw < DRAW_INTERVAL) return;
  for (uint8_t item = 0; item < numItems; item++) {
    if (dirty & (1u << item)) {
      drawItem(item);
      dirty &= ~(1u << item);
      lastDraw = now;
      return;
    }
  }
}

// ===============================
// ENVIO MIDI
// ===============================
void sendVolume(uint8_t i) {
  midi.sendControlChange({ccNumber[i], Channel_1}, volume[i]);
}

void handleEncoder(uint8_t i, uint16_t gpio) {
  uint8_t state = readEncoderState(i, gpio);
  if (state == prevState[i]) return;

  accum[i] += transitionTable[prevState[i]][state];
  prevState[i] = state;

  if (!isRestState(state)) return;

  if (accum[i] >= (pulsesPerDetent + 1) / 2 || accum[i] <= -(pulsesPerDetent + 1) / 2) {
    int8_t dir = (accum[i] > 0) ? 1 : -1;
    int v = constrain((int)volume[i] + dir * step, 0, 127);
    if (v != volume[i]) {
      volume[i] = (uint8_t)v;
      sendVolume(i);
      markDirty(i);
      markLed(i);
    }
  }
  accum[i] = 0;
}

void handleSwitches(uint16_t gpio) {
  unsigned long now = millis();
  for (uint8_t i = 0; i < numEncoders; i++) {
    bool level;
    if (swBit[i] == 255) level = digitalRead(SW5_PIN);
    else if (mcpOk)      level = (gpio >> swBit[i]) & 1;
    else                 continue;
    bool raw = SW_ACTIVE_HIGH ? level : !level;   // true = apertado

    if (raw != swLastRaw[i]) {
      swLastRaw[i] = raw;
      swChanged[i] = now;
    } else if (raw != swState[i] && now - swChanged[i] >= DEBOUNCE_MS) {
      swState[i] = raw;
      MIDIAddress addr {uint8_t(firstSwNote + i), Channel_1};
      if (raw) midi.sendNoteOn(addr, 127);
      else     midi.sendNoteOff(addr, 0);
      if (FLASH_ON_PRESS) markLed(i);
    }
  }
}

// ===============================
// Envio inicial (após USB enumerar)
// ===============================
bool initialSent = false;
constexpr unsigned long INITIAL_DELAY = 1500;

// ===============================
// SETUP & LOOP
// ===============================
void setup() {
  Control_Surface.begin();

  // OLED
  u8x8.setBusClock(400000);
  u8x8.begin();
  u8x8.setFont(u8x8_font_chroma48medium8_r);
  u8x8.clear();
  u8x8.drawString(0, 0, "MIDI CONTROLLER");

  Wire.begin();
  Wire.setClock(400000);

  // MCP23017: tudo entrada (padrão). Pull-up nos encoders; nos botões só
  // se eles fecharem contra o GND.
  mcpOk = i2cPresent(MCP_ADDR);
  if (mcpOk) {
    uint8_t pu = 0x1F | (SW_ACTIVE_HIGH ? 0x00 : 0x60);
    i2cWrite8(MCP_ADDR, MCP_GPPUA, pu);
    i2cWrite8(MCP_ADDR, MCP_GPPUB, pu);
  }

  // PCA9685
  pcaOk = i2cPresent(PCA_ADDR);
  if (pcaOk) pcaBegin();

  // Botão do encoder 5, direto no Pro Micro
  pinMode(SW5_PIN, SW_ACTIVE_HIGH ? INPUT : INPUT_PULLUP);

  if (!mcpOk)      u8x8.drawString(0, 7, "MCP23017 ERRO");
  else if (!pcaOk) u8x8.drawString(0, 7, "PCA9685 ERRO");

  uint16_t gpio = mcpOk ? mcpReadAB() : 0xFFFF;
  for (uint8_t i = 0; i < numEncoders; i++) {
    volume[i] = initialVolume;
    prevState[i] = readEncoderState(i, gpio);
  }
  for (uint8_t p = 0; p < numPots; p++)
    potShown[p] = 0;

  dirty = (1u << numItems) - 1;              // desenha tudo no início
  ledDirty = (1 << numEncoders) - 1;         // acende todos os LEDs
}

void loop() {
  Control_Surface.loop();   // matriz + faders

  // 1 leitura I2C: giro dos 5 encoders e botões 1 a 4
  uint16_t gpio = mcpOk ? mcpReadAB() : 0xFFFF;
  if (mcpOk)
    for (uint8_t i = 0; i < numEncoders; i++)
      handleEncoder(i, gpio);
  handleSwitches(gpio);

  for (uint8_t p = 0; p < numPots; p++) {
    uint8_t v = pots[p].getValue();
    if (v != potShown[p]) {
      potShown[p] = v;
      markDirty(numEncoders + p);
    }
  }

  updateOutputs();

  if (!initialSent && millis() > INITIAL_DELAY) {
    for (uint8_t i = 0; i < numEncoders; i++)
      sendVolume(i);
    initialSent = true;
  }
}
