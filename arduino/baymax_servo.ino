// baymax_servo.ino — Firmware Arduino Nano
// Contrôle 6 servos (2 tête + 4 bras) + capteur ultrason HC-SR04
// Communication série 115200 baud avec le Raspberry Pi
//
// Protocole :
//   HP{0-180}\n   → Head Pan
//   HT{0-180}\n   → Head Tilt
//   ALS{0-180}\n  → Arm Left Shoulder (lever/baisser)
//   ALR{0-180}\n  → Arm Left Rotation (ouvrir/fermer)
//   ARS{0-180}\n  → Arm Right Shoulder
//   ARR{0-180}\n  → Arm Right Rotation
//   HUG\n         → Macro câlin
//   WAVE\n        → Macro salut
//   IDLE\n        → Position neutre
//   PING\n        → Retourne "PONG" (test connexion)
//   DIST\n        → Retourne distance ultrason en cm
//
// Réponse : "OK\n" après chaque commande, ou "ERR:msg\n"

#include <Servo.h>

// ---------------------------------------------------------------
// PINS
// ---------------------------------------------------------------
#define PIN_PAN       9     // Tête horizontal
#define PIN_TILT      10    // Tête vertical
#define PIN_ARM_LS    3     // Bras gauche épaule
#define PIN_ARM_LR    5     // Bras gauche rotation
#define PIN_ARM_RS    6     // Bras droit épaule
#define PIN_ARM_RR    11    // Bras droit rotation
#define PIN_TRIG      7     // HC-SR04 Trigger
#define PIN_ECHO      8     // HC-SR04 Echo

// ---------------------------------------------------------------
// CONSTANTES
// ---------------------------------------------------------------
#define NUM_SERVOS    6
#define RAMP_STEP     2       // Degrés par cycle (lissage mouvement)
#define LOOP_DELAY    20      // ms par cycle (50 Hz)
#define WATCHDOG_MS   2000    // Timeout sans commande → IDLE
#define OBSTACLE_CM   15      // Distance min avant arrêt bras
#define SERIAL_BAUD   115200

// Positions de référence (degrés)
#define IDLE_PAN      90
#define IDLE_TILT     90
#define IDLE_ARM_LS   10
#define IDLE_ARM_LR   90
#define IDLE_ARM_RS   10
#define IDLE_ARM_RR   90

#define HUG_PAN       90
#define HUG_TILT      80
#define HUG_ARM_LS    120
#define HUG_ARM_LR    40
#define HUG_ARM_RS    120
#define HUG_ARM_RR    140

#define WAVE_PAN      90
#define WAVE_TILT     90
#define WAVE_ARM_LS   10
#define WAVE_ARM_LR   90
#define WAVE_ARM_RS   150
#define WAVE_ARM_RR   90

// ---------------------------------------------------------------
// VARIABLES
// ---------------------------------------------------------------
Servo servos[NUM_SERVOS];
int target[NUM_SERVOS];     // Angles cible
int current[NUM_SERVOS];    // Angles courant (rampe progressive)
const int pins[NUM_SERVOS] = {
  PIN_PAN, PIN_TILT, PIN_ARM_LS, PIN_ARM_LR, PIN_ARM_RS, PIN_ARM_RR
};

// Index lisibles
enum ServoIndex {
  PAN = 0, TILT = 1,
  ARM_LS = 2, ARM_LR = 3,
  ARM_RS = 4, ARM_RR = 5
};

unsigned long lastCommandTime = 0;
bool obstacleDetected = false;
String inputBuffer = "";

// ---------------------------------------------------------------
// SETUP
// ---------------------------------------------------------------
void setup() {
  Serial.begin(SERIAL_BAUD);
  Serial.setTimeout(50);

  // Attacher les servos
  for (int i = 0; i < NUM_SERVOS; i++) {
    servos[i].attach(pins[i]);
  }

  // HC-SR04
  pinMode(PIN_TRIG, OUTPUT);
  pinMode(PIN_ECHO, INPUT);

  // Position initiale
  setIdle();
  writeServosImmediate();

  lastCommandTime = millis();
  Serial.println("READY");
}

// ---------------------------------------------------------------
// BOUCLE PRINCIPALE
// ---------------------------------------------------------------
void loop() {
  // 1. Lire les commandes série
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n' || c == '\r') {
      if (inputBuffer.length() > 0) {
        processCommand(inputBuffer);
        inputBuffer = "";
      }
    } else {
      inputBuffer += c;
      // Protection buffer overflow
      if (inputBuffer.length() > 20) {
        inputBuffer = "";
        Serial.println("ERR:OVERFLOW");
      }
    }
  }

  // 2. Lire distance ultrason (toutes les 5 boucles = 100 ms)
  static int loopCount = 0;
  loopCount++;
  if (loopCount % 5 == 0) {
    float dist = readDistance();
    obstacleDetected = (dist > 0 && dist < OBSTACLE_CM);
  }

  // 3. Rampe progressive vers les angles cible
  for (int i = 0; i < NUM_SERVOS; i++) {
    // Si obstacle détecté, figer les bras (index 2-5) mais pas la tête (0-1)
    if (obstacleDetected && i >= 2) {
      continue;  // On ne bouge pas les bras
    }

    if (current[i] < target[i]) {
      current[i] = min(current[i] + RAMP_STEP, target[i]);
    } else if (current[i] > target[i]) {
      current[i] = max(current[i] - RAMP_STEP, target[i]);
    }
    servos[i].write(current[i]);
  }

  // 4. Watchdog : sans commande depuis 2s → retour IDLE
  if (millis() - lastCommandTime > WATCHDOG_MS) {
    setIdle();
    lastCommandTime = millis();  // Reset pour ne pas boucler
  }

  delay(LOOP_DELAY);
}

// ---------------------------------------------------------------
// PARSING DES COMMANDES
// ---------------------------------------------------------------
void processCommand(String cmd) {
  cmd.trim();
  cmd.toUpperCase();
  lastCommandTime = millis();

  // --- Macros ---
  if (cmd == "IDLE") {
    setIdle();
    Serial.println("OK");
    return;
  }
  if (cmd == "HUG") {
    setHug();
    Serial.println("OK");
    return;
  }
  if (cmd == "WAVE") {
    setWave();
    Serial.println("OK");
    return;
  }
  if (cmd == "PING") {
    Serial.println("PONG");
    return;
  }
  if (cmd == "DIST") {
    float d = readDistance();
    Serial.print("DIST:");
    Serial.println(d, 1);
    return;
  }

  // --- Commandes individuelles : XX{angle} ---
  int angle = -1;
  int servoIdx = -1;

  if (cmd.startsWith("HP")) {
    servoIdx = PAN;
    angle = cmd.substring(2).toInt();
  } else if (cmd.startsWith("HT")) {
    servoIdx = TILT;
    angle = cmd.substring(2).toInt();
  } else if (cmd.startsWith("ALS")) {
    servoIdx = ARM_LS;
    angle = cmd.substring(3).toInt();
  } else if (cmd.startsWith("ALR")) {
    servoIdx = ARM_LR;
    angle = cmd.substring(3).toInt();
  } else if (cmd.startsWith("ARS")) {
    servoIdx = ARM_RS;
    angle = cmd.substring(3).toInt();
  } else if (cmd.startsWith("ARR")) {
    servoIdx = ARM_RR;
    angle = cmd.substring(3).toInt();
  }

  if (servoIdx >= 0 && angle >= 0 && angle <= 180) {
    target[servoIdx] = angle;
    Serial.println("OK");
  } else {
    Serial.print("ERR:UNKNOWN_CMD:");
    Serial.println(cmd);
  }
}

// ---------------------------------------------------------------
// POSITIONS PRÉDÉFINIES
// ---------------------------------------------------------------
void setIdle() {
  target[PAN]    = IDLE_PAN;
  target[TILT]   = IDLE_TILT;
  target[ARM_LS] = IDLE_ARM_LS;
  target[ARM_LR] = IDLE_ARM_LR;
  target[ARM_RS] = IDLE_ARM_RS;
  target[ARM_RR] = IDLE_ARM_RR;
}

void setHug() {
  target[PAN]    = HUG_PAN;
  target[TILT]   = HUG_TILT;
  target[ARM_LS] = HUG_ARM_LS;
  target[ARM_LR] = HUG_ARM_LR;
  target[ARM_RS] = HUG_ARM_RS;
  target[ARM_RR] = HUG_ARM_RR;
}

void setWave() {
  target[PAN]    = WAVE_PAN;
  target[TILT]   = WAVE_TILT;
  target[ARM_LS] = WAVE_ARM_LS;
  target[ARM_LR] = WAVE_ARM_LR;
  target[ARM_RS] = WAVE_ARM_RS;
  target[ARM_RR] = WAVE_ARM_RR;
}

void writeServosImmediate() {
  for (int i = 0; i < NUM_SERVOS; i++) {
    current[i] = target[i];
    servos[i].write(current[i]);
  }
}

// ---------------------------------------------------------------
// CAPTEUR ULTRASON HC-SR04
// ---------------------------------------------------------------
float readDistance() {
  // Envoyer impulsion 10µs
  digitalWrite(PIN_TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(PIN_TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(PIN_TRIG, LOW);

  // Lire le retour (timeout 30ms = ~500 cm max)
  long duration = pulseIn(PIN_ECHO, HIGH, 30000);

  if (duration == 0) {
    return -1.0;  // Pas de retour (hors portée)
  }

  // Vitesse du son = 343 m/s → distance = durée * 0.0343 / 2
  return duration * 0.0343 / 2.0;
}
