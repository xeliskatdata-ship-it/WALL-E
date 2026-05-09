// walle_firmware.ino - WALL-E Mega 2560 firmware v2.4
//
// Hardware :
//   - Mega 2560 REV3
//   - Shield TB6612 4 moteurs Mecanum (a valider visuellement par Brice)
//   - 4 servos : head pan/tilt + bras G/D
//   - 1 HC-SR04 ultrason avant
//   - 1 MPU6050 GY-521 (I2C natif Mega : SDA=D20, SCL=D21)
//
// Protocole serie 115200 baud, line-based '\n' :
//   RECEPTION (commandes Pi -> Mega) :
//     PING                            -> R:PONG
//     SERVO <id> <angle>              -> R:OK | R:ERR:..   (id 0=hpan,1=htilt,2=armL,3=armR)
//     MOTORS <fl> <fr> <bl> <br>      -> R:OK              (chaque -100..100, signed)
//     STOP                            -> R:OK
//     DUTY <0..100>                   -> R:OK              (modifie le duty cap runtime)
//   PUSH (Mega -> Pi) toutes les 50ms (20 Hz) :
//     S:{"u":<cm>,"ax":..,"ay":..,"az":..,"gx":..,"gy":..,"gz":..,"t":<ms>}
//
// Securites :
//   - Watchdog 1s : sans MOTORS ou STOP -> stop auto les 4 moteurs.
//   - Obstacle stop : si ultrason < 15cm ET un moteur en avant -> override stop, push R:OBSTACLE.
//   - Duty cap au boot 60 (debridable via DUTY runtime).
//
// Libs requises (Library Manager IDE Arduino) :
//   - MPU6050 (jrowberg / electroniccats)
//   - I2Cdevlib (auto-installe avec MPU6050)
//   - NewPing (Tim Eckel)

#include <Servo.h>
#include <Wire.h>
#include <I2Cdev.h>
#include <MPU6050.h>
#include <NewPing.h>

// ===== PINOUT (a valider serigraphie shield Brice - Q1 ouvert) =====
// TB6612 4 moteurs : PWM sur timers compatibles Servo.h
// Convention : FL=front-left, FR=front-right, BL=back-left, BR=back-right
const uint8_t M_PWM[4] = { 2,  7,  8, 12};   // FL, FR, BL, BR
const uint8_t M_IN1[4] = {22, 24, 26, 28};
const uint8_t M_IN2[4] = {23, 25, 27, 29};
const uint8_t M_STBY   = 30;

// Servos (Mega supporte jusqu'a 12 servos avec lib Servo standard)
const uint8_t SERVO_PIN[4] = {5, 6, 11, 13};   // hpan, htilt, armL, armR
const uint8_t SERVO_INIT[4] = {90, 90, 90, 90};

// HC-SR04 (digital pur, hors timers Servo)
const uint8_t US_TRIG = 48;
const uint8_t US_ECHO = 49;
const unsigned int US_MAX_CM = 200;

// MPU6050 sur I2C natif Mega : SDA=D20, SCL=D21 (PAS A4/A5)

// ===== ETAT GLOBAL =====
Servo servos[4];
MPU6050 mpu;
NewPing sonar(US_TRIG, US_ECHO, US_MAX_CM);

uint8_t  duty_cap = 60;          // plafond duty 0..100 (boot a 60, modifiable via DUTY)
unsigned long last_motor_cmd_ms = 0;
unsigned long last_push_ms = 0;
const unsigned long WATCHDOG_MS = 1000;
const unsigned long PUSH_PERIOD_MS = 50;     // 20 Hz
const int OBSTACLE_STOP_CM = 15;

int8_t motor_cmd[4] = {0, 0, 0, 0};   // -100..100 dernier ordre

// ===== HELPERS MOTEURS =====
void motorsStandby(bool stby) {
  digitalWrite(M_STBY, stby ? LOW : HIGH);
}

void setMotor(uint8_t idx, int speed) {
  // speed -100..100, applique duty_cap
  speed = constrain(speed, -100, 100);
  bool fwd = (speed >= 0);
  int mag = abs(speed);
  if (mag > duty_cap) mag = duty_cap;
  int pwm = map(mag, 0, 100, 0, 255);
  digitalWrite(M_IN1[idx], fwd ? HIGH : LOW);
  digitalWrite(M_IN2[idx], fwd ? LOW  : HIGH);
  analogWrite(M_PWM[idx], pwm);
}

void allMotorsStop() {
  for (uint8_t i = 0; i < 4; i++) {
    digitalWrite(M_IN1[i], LOW);
    digitalWrite(M_IN2[i], LOW);
    analogWrite(M_PWM[i], 0);
    motor_cmd[i] = 0;
  }
}

// ===== PARSING COMMANDES =====
void handleLine(String line) {
  line.trim();
  if (line.length() == 0) return;

  if (line == "PING") {
    Serial.println("R:PONG");
    return;
  }

  if (line == "STOP") {
    allMotorsStop();
    last_motor_cmd_ms = millis();
    Serial.println("R:OK");
    return;
  }

  if (line.startsWith("SERVO ")) {
    int id, angle;
    if (sscanf(line.c_str(), "SERVO %d %d", &id, &angle) == 2) {
      if (id >= 0 && id < 4 && angle >= 0 && angle <= 180) {
        servos[id].write(angle);
        Serial.println("R:OK");
      } else {
        Serial.println("R:ERR:bounds");
      }
    } else {
      Serial.println("R:ERR:parse");
    }
    return;
  }

  if (line.startsWith("MOTORS ")) {
    int fl, fr, bl, br;
    if (sscanf(line.c_str(), "MOTORS %d %d %d %d", &fl, &fr, &bl, &br) == 4) {
      // securite obstacle : si ultrason < seuil ET un des moteurs avant > 0 -> override
      unsigned int us_cm = sonar.ping_cm();
      bool moving_fwd = (fl > 0) || (fr > 0);
      if (us_cm > 0 && us_cm < OBSTACLE_STOP_CM && moving_fwd) {
        allMotorsStop();
        Serial.println("R:OBSTACLE");
        last_motor_cmd_ms = millis();
        return;
      }
      motor_cmd[0] = fl; motor_cmd[1] = fr;
      motor_cmd[2] = bl; motor_cmd[3] = br;
      setMotor(0, fl); setMotor(1, fr);
      setMotor(2, bl); setMotor(3, br);
      last_motor_cmd_ms = millis();
      Serial.println("R:OK");
    } else {
      Serial.println("R:ERR:parse");
    }
    return;
  }

  if (line.startsWith("DUTY ")) {
    int d;
    if (sscanf(line.c_str(), "DUTY %d", &d) == 1 && d >= 0 && d <= 100) {
      duty_cap = (uint8_t)d;
      Serial.println("R:OK");
    } else {
      Serial.println("R:ERR:bounds");
    }
    return;
  }

  Serial.println("R:ERR:unknown");
}

// ===== PUSH CAPTEURS 20Hz =====
void pushSensors() {
  unsigned int us_cm = sonar.ping_cm();
  int16_t ax, ay, az, gx, gy, gz;
  mpu.getMotion6(&ax, &ay, &az, &gx, &gy, &gz);

  // JSON compact, pas de floats sur Arduino (couteux)
  Serial.print("S:{\"u\":");   Serial.print(us_cm);
  Serial.print(",\"ax\":");    Serial.print(ax);
  Serial.print(",\"ay\":");    Serial.print(ay);
  Serial.print(",\"az\":");    Serial.print(az);
  Serial.print(",\"gx\":");    Serial.print(gx);
  Serial.print(",\"gy\":");    Serial.print(gy);
  Serial.print(",\"gz\":");    Serial.print(gz);
  Serial.print(",\"t\":");     Serial.print(millis());
  Serial.println("}");
}

// ===== SETUP & LOOP =====
void setup() {
  Serial.begin(115200);
  while (!Serial && millis() < 3000) { /* attente USB */ }

  // TB6612
  for (uint8_t i = 0; i < 4; i++) {
    pinMode(M_PWM[i], OUTPUT);
    pinMode(M_IN1[i], OUTPUT);
    pinMode(M_IN2[i], OUTPUT);
  }
  pinMode(M_STBY, OUTPUT);
  motorsStandby(false);     // wake driver
  allMotorsStop();

  // Servos
  for (uint8_t i = 0; i < 4; i++) {
    servos[i].attach(SERVO_PIN[i]);
    servos[i].write(SERVO_INIT[i]);
  }

  // Capteurs
  Wire.begin();
  mpu.initialize();
  // pas d'erreur fatale si MPU absent : on continuera a pousser les zeros
  pinMode(US_TRIG, OUTPUT);
  pinMode(US_ECHO, INPUT);

  Serial.println("R:READY");
  last_motor_cmd_ms = millis();
}

void loop() {
  // 1. lecture serie
  static String buf;
  while (Serial.available()) {
    char c = Serial.read();
    if (c == '\n') {
      handleLine(buf);
      buf = "";
    } else if (c != '\r') {
      buf += c;
      if (buf.length() > 128) buf = "";   // anti-overflow
    }
  }

  // 2. watchdog moteurs
  if (millis() - last_motor_cmd_ms > WATCHDOG_MS) {
    bool any_running = false;
    for (uint8_t i = 0; i < 4; i++) if (motor_cmd[i] != 0) { any_running = true; break; }
    if (any_running) allMotorsStop();
  }

  // 3. push capteurs 20Hz
  if (millis() - last_push_ms >= PUSH_PERIOD_MS) {
    pushSensors();
    last_push_ms = millis();
  }
}