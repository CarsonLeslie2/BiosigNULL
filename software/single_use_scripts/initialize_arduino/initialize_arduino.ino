#include <Arduino.h>

const int SET_PIN = A1;      // ULN2803 IN1
const int RESET_PIN = A0;    // ULN2803 IN2
const int PULSE_MS = 50;     // pulse length

void sendPulse(int pin) {
  digitalWrite(pin, HIGH);
  delay(PULSE_MS);
  digitalWrite(pin, LOW);
}

void setup() {
  pinMode(SET_PIN, OUTPUT);
  pinMode(RESET_PIN, OUTPUT);

  digitalWrite(SET_PIN, LOW);
  digitalWrite(RESET_PIN, LOW);

  Serial.begin(9600);
  Serial.println("Ready. Send S for SET, R for RESET.");
}

void loop() {
  if (Serial.available() > 0) {
    char cmd = Serial.read();

    if (cmd == 'S' || cmd == 's') {
      sendPulse(SET_PIN);
      Serial.println("SET pulse sent");
    } 
    else if (cmd == 'R' || cmd == 'r') {
      sendPulse(RESET_PIN);
      Serial.println("RESET pulse sent");
    }
  }
}