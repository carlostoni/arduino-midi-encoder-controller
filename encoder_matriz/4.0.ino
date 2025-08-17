#include <Control_Surface.h>

// ===============================
// Interface MIDI USB
// ===============================
USBMIDI_Interface midi;

// ===============================
// ENCODERS (state machine quadratura)
// ===============================

// Pinos dos encoders
constexpr uint8_t pinA[] = {1, 20, 4, 18};
constexpr uint8_t pinB[] = {2, 21, 3, 19};
constexpr uint8_t ccNumber[] = {21, 22, 23, 24};

// Estado anterior e valores
uint8_t prevState[4];
int8_t volume[4] = {90, 90, 90, 90};

// Step de mudança (pode ser 1, 2, 5...)
constexpr int8_t step = 3;

// Controle de debounce por tempo
unsigned long lastMove[4] = {0, 0, 0, 0};

// Tabela de transições do encoder
// Cada linha = estado anterior, cada coluna = estado atual
// Valores: -1 (anti-horário), +1 (horário), 0 (inválido/sem movimento)
const int8_t transitionTable[4][4] = {
  { 0, -1,  1,  0},  // prev 00
  { 1,  0,  0, -1},  // prev 01
  {-1,  0,  0,  1},  // prev 10
  { 0,  1, -1,  0}   // prev 11
};

void handleEncoder(uint8_t index) {
  // Lê estado atual (2 bits)
  uint8_t state = (digitalRead(pinA[index]) << 1) | digitalRead(pinB[index]);

  int8_t delta = transitionTable[prevState[index]][state];
  if (delta != 0) {
    unsigned long now = millis();
    if (now - lastMove[index] > 1) { // debounce mínimo

      volume[index] = constrain(volume[index] + delta * step, 0, 127);

      // Envia CC no canal correto
      midi.sendCC({ccNumber[index], CHANNEL_1}, volume[index]);

      lastMove[index] = now;
    }
  }

  prevState[index] = state;
}

// ===============================
// MATRIZ DE BOTÕES
// ===============================
const AddressMatrix<5, 4> addresses = {{
  {1,  2,  3,  4},
  {5,  6,  7,  8},
  {9,  10, 11, 12},
  {13, 14, 15, 16},
  {17, 18, 19, 20},
}};

NoteButtonMatrix<5, 4> buttonmatrix = {
  {5, 6, 7, 8, 9},   // row pins
  {15, 14, 16, 10},  // column pins
  addresses,
  CHANNEL_1,
};

// ===============================
// SETUP & LOOP
// ===============================
void setup() {
  Control_Surface.begin();

  // Configura pinos dos encoders
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(pinA[i], INPUT_PULLUP);
    pinMode(pinB[i], INPUT_PULLUP);
    prevState[i] = (digitalRead(pinA[i]) << 1) | digitalRead(pinB[i]);

    // Envia valor inicial
    midi.sendCC({ccNumber[i], CHANNEL_1}, volume[i]);
  }
}

void loop() {
  Control_Surface.loop();

  // Leitura dos encoders
  for (uint8_t i = 0; i < 4; i++) {
    handleEncoder(i);
  }
}
