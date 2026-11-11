#include <Control_Surface.h>
#include <Wire.h>
#include <Adafruit_MCP23X17.h>
#include <U8x8lib.h>

// =====================================================================
// Controlador MIDI: Arduino Pro Micro + 1x MCP23017 + OLED I2C
// ---------------------------------------------------------------------
// Pro Micro (18 I/O, todos usados):
//   I2C (MCP23017 + OLED) -> 2 (SDA), 3 (SCL)
//   Potenciômetros        -> A0 (18), A1 (19), A2 (20), A3 (21)
//   Matriz 7x5 - linhas   -> 0, 1, 4, 5, 6, 7, 8
//   Matriz 7x5 - colunas  -> 9, 10, 14, 15, 16
//
// MCP23017 (endereço 0x20) -> 5 encoders
//   Encoder n: A = GPA n, B = GPB n   (n = 0..4)
//   Livres: GPA5, GPA6, GPB5, GPB6 (ex.: botões dos encoders)
//   GPA7/GPB7 não são usados como entrada (somente saída nas revisões atuais)
//
// OLED SSD1306 128x64 I2C (endereço 0x3C)
//   Usa U8x8 (modo texto, sem buffer de tela) para economizar RAM do 32U4.
//
// MIDI (canal 1):
//   Matriz    -> notas 1..35
//   Encoders  -> CC 21..25
//   Pots      -> CC 30..33
// =====================================================================

// ===============================
// Interface MIDI USB
// ===============================
USBMIDI_Interface midi;

// ===============================
// OLED
// ===============================
// Display 0,96" (SSD1306). Se o seu for de 1,3" e aparecer deslocado/com
// lixo na borda, troque pela linha comentada (SH1106).
U8X8_SSD1306_128X64_NONAME_HW_I2C u8x8(U8X8_PIN_NONE);
// U8X8_SH1106_128X64_NONAME_HW_I2C u8x8(U8X8_PIN_NONE);

// ===============================
// MCP23017
// ===============================
Adafruit_MCP23X17 mcp;
bool mcpOk = false;

// ===============================
// ENCODERS (no MCP23017)
// ===============================
constexpr uint8_t numEncoders = 5;
constexpr uint8_t ccNumber[numEncoders] = {21, 22, 23, 24, 25};

constexpr int8_t  step            = 3;     // passo por clique
constexpr int8_t  pulsesPerDetent = 4;     // EC11 = 4; se andar "pela metade", use 2
constexpr uint8_t restState       = 0b11;  // estado parado no clique (pull-up)
constexpr uint8_t initialVolume   = 90;

uint8_t prevState[numEncoders];
int8_t  accum[numEncoders] = {0};
uint8_t volume[numEncoders];

const int8_t transitionTable[4][4] = {
  { 0, -1,  1,  0},  // prev 00
  { 1,  0,  0, -1},  // prev 01
  {-1,  0,  0,  1},  // prev 10
  { 0,  1, -1,  0}   // prev 11
};

// readGPIOAB(): GPA nos bits 0..7, GPB nos bits 8..15
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
// POTENCIÔMETROS (no Pro Micro)
// ===============================
// A Control Surface já filtra o ruído e só envia quando o valor muda.
CCPotentiometer pots[] = {
  {A0, {30, CHANNEL_1}},
  {A1, {31, CHANNEL_1}},
  {A2, {32, CHANNEL_1}},
  {A3, {33, CHANNEL_1}},
};
constexpr uint8_t numPots = sizeof(pots) / sizeof(pots[0]);
uint8_t potShown[numPots];

// ===============================
// MATRIZ 7x5 (no Pro Micro)
// ===============================
const AddressMatrix<7, 5> addresses = {{
  { 1,  2,  3,  4,  5},
  { 6,  7,  8,  9, 10},
  {11, 12, 13, 14, 15},
  {16, 17, 18, 19, 20},
  {21, 22, 23, 24, 25},
  {26, 27, 28, 29, 30},
  {31, 32, 33, 34, 35},
}};

NoteButtonMatrix<7, 5> buttonmatrix = {
  {0, 1, 4, 5, 6, 7, 8},   // linhas
  {9, 10, 14, 15, 16},     // colunas
  addresses,
  CHANNEL_1,
};

// ===============================
// TELA
// ---------------------------------------------------------------
//  linha 0: título
//  linhas 2..6: encoders (coluna 0)    linhas 2..5: pots (coluna 9)
//
//  Cada item tem um bit "sujo". A cada loop desenha no máximo 1 item
//  (~6 caracteres), para a escrita I2C não travar a leitura dos encoders.
// ===============================
constexpr uint8_t numItems = numEncoders + numPots;   // 0..4 encoders, 5..8 pots
uint16_t dirty = 0;
unsigned long lastDraw = 0;
constexpr unsigned long DRAW_INTERVAL = 15;   // ms entre atualizações de tela

inline void markDirty(uint8_t item) { dirty |= (1u << item); }

void drawItem(uint8_t item) {
  char buf[8];
  if (item < numEncoders) {
    snprintf(buf, sizeof(buf), "E%u:%3u", item + 1, volume[item]);
    u8x8.drawString(0, 2 + item, buf);
  } else {
    uint8_t p = item - numEncoders;
    snprintf(buf, sizeof(buf), "P%u:%3u", p + 1, potShown[p]);
    u8x8.drawString(9, 2 + p, buf);
  }
}

void updateDisplay() {
  if (!dirty || millis() - lastDraw < DRAW_INTERVAL) return;
  for (uint8_t item = 0; item < numItems; item++) {
    if (dirty & (1u << item)) {
      drawItem(item);
      dirty &= ~(1u << item);
      lastDraw = millis();
      return;   // só 1 item por vez
    }
  }
}

// ===============================
// ENVIO MIDI DOS ENCODERS
// ===============================
void sendVolume(uint8_t i) {
  midi.sendCC({ccNumber[i], CHANNEL_1}, volume[i]);
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
    }
  }
  accum[i] = 0;
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
  u8x8.drawString(1, 0, "MIDI CONTROLLER");

  // MCP23017
  mcpOk = mcp.begin_I2C(0x20);
  Wire.setClock(400000);
  if (mcpOk) {
    for (uint8_t i = 0; i < numEncoders; i++) {
      mcp.pinMode(i,     INPUT_PULLUP);   // GPA i -> A
      mcp.pinMode(8 + i, INPUT_PULLUP);   // GPB i -> B
    }
  } else {
    u8x8.drawString(0, 7, "MCP23017 ERRO!");
  }

  uint16_t gpio = mcpOk ? mcp.readGPIOAB() : 0xFFFF;
  for (uint8_t i = 0; i < numEncoders; i++) {
    volume[i] = initialVolume;
    prevState[i] = readEncoderState(i, gpio);
  }
  for (uint8_t p = 0; p < numPots; p++)
    potShown[p] = 0;

  dirty = (1u << numItems) - 1;   // desenha tudo no início
}

void loop() {
  Control_Surface.loop();   // matriz + potenciômetros

  // Encoders: 1 leitura I2C para os 5
  if (mcpOk) {
    uint16_t gpio = mcp.readGPIOAB();
    for (uint8_t i = 0; i < numEncoders; i++)
      handleEncoder(i, gpio);
  }

  // Potenciômetros: atualiza a tela quando o valor muda
  for (uint8_t p = 0; p < numPots; p++) {
    uint8_t v = pots[p].getValue();
    if (v != potShown[p]) {
      potShown[p] = v;
      markDirty(numEncoders + p);
    }
  }

  updateDisplay();

  if (!initialSent && millis() > INITIAL_DELAY) {
    for (uint8_t i = 0; i < numEncoders; i++)
      sendVolume(i);
    initialSent = true;
  }
}
