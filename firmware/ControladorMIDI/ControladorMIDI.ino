#include <Control_Surface.h>

// ===============================
// Interface MIDI USB
// ===============================
USBMIDI_Interface midi;

// ===============================
// ENCODERS (state machine de quadratura)
// ===============================

// Pinos dos encoders (Arduino Pro Micro)
constexpr uint8_t pinA[]     = {1, 20, 4, 18};
constexpr uint8_t pinB[]     = {2, 21, 3, 19};
constexpr uint8_t ccNumber[] = {21, 22, 23, 24};

// Número de encoders, derivado do array (evita o "4" mágico espalhado)
constexpr uint8_t numEncoders = sizeof(pinA) / sizeof(pinA[0]);

// Passo de mudança por detent (clique)
constexpr int8_t step = 3;

// Quantas transições de quadratura formam 1 detent.
// EC11 e a maioria dos encoders mecânicos = 4. Se andar "pela metade", troque p/ 2.
constexpr int8_t pulsesPerDetent = 4;

// Estado em que o encoder fica parado no clique (com INPUT_PULLUP costuma ser 11).
// Se o seu repousar em 00, troque para 0b00.
constexpr uint8_t restState = 0b11;

// Estado e valores
uint8_t prevState[numEncoders];
int8_t  accum[numEncoders]  = {0};                 // transições acumuladas desde o último detent
uint8_t volume[numEncoders] = {90, 90, 90, 90};    // valor de cada CC (0..127)

// Tabela de transições do encoder
// linha = estado anterior, coluna = estado atual
// +1 horário, -1 anti-horário, 0 inválido/sem movimento
const int8_t transitionTable[4][4] = {
  { 0, -1,  1,  0},  // prev 00
  { 1,  0,  0, -1},  // prev 01
  {-1,  0,  0,  1},  // prev 10
  { 0,  1, -1,  0}   // prev 11
};

inline uint8_t readState(uint8_t i) {
  return (digitalRead(pinA[i]) << 1) | digitalRead(pinB[i]);
}

// Encoders de 4 transições param só em restState;
// os de 2 transições param também no estado oposto.
inline bool isRestState(uint8_t state) {
  return state == restState ||
         (pulsesPerDetent == 2 && state == (restState ^ 0b11));
}

void sendVolume(uint8_t i) {
  midi.sendCC({ccNumber[i], CHANNEL_1}, volume[i]);
}

void handleEncoder(uint8_t i) {
  uint8_t state = readState(i);
  if (state == prevState[i]) return;

  accum[i] += transitionTable[prevState[i]][state];
  prevState[i] = state;

  // Só decide quando o encoder chega na posição de repouso (o "clique").
  // Basta ter andado mais da metade do detent: tolera 1 transição perdida
  // por bounce, e zerar aqui impede que o contador saia de fase com o clique.
  if (!isRestState(state)) return;

  if (accum[i] >= (pulsesPerDetent + 1) / 2 || accum[i] <= -(pulsesPerDetent + 1) / 2) {
    int8_t dir = (accum[i] > 0) ? 1 : -1;
    int v = constrain((int)volume[i] + dir * step, 0, 127);
    if (v != volume[i]) {
      volume[i] = (uint8_t)v;
      sendVolume(i);
    }
  }
  accum[i] = 0;
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
  {5, 6, 7, 8, 9},   // pinos das linhas
  {15, 14, 16, 10},  // pinos das colunas
  addresses,
  CHANNEL_1,
};

// ===============================
// Envio inicial (após USB enumerar)
// ===============================
bool initialSent = false;
constexpr unsigned long INITIAL_DELAY = 1500; // ms p/ o host reconhecer o dispositivo

// ===============================
// SETUP & LOOP
// ===============================
void setup() {
  Control_Surface.begin();

  for (uint8_t i = 0; i < numEncoders; i++) {
    pinMode(pinA[i], INPUT_PULLUP);
    pinMode(pinB[i], INPUT_PULLUP);
    prevState[i] = readState(i);
  }
}

void loop() {
  Control_Surface.loop();

  for (uint8_t i = 0; i < numEncoders; i++)
    handleEncoder(i);

  // Manda os valores iniciais uma vez, já com o USB-MIDI ativo
  // (em setup() o host normalmente ainda não está conectado e a msg se perde).
  if (!initialSent && millis() > INITIAL_DELAY) {
    for (uint8_t i = 0; i < numEncoders; i++)
      sendVolume(i);
    initialSent = true;
  }
}
