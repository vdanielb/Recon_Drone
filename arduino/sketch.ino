#include <Servo.h>

// Elegoo V4 motor pins (TB6612 shield)
#define PWMA 5
#define PWMB 6
#define AIN1 7
#define BIN1 8
#define STBY 3
#define BUTTON_PIN 2   // active-LOW: idles HIGH, reads LOW when pressed

// Servo-mounted HC-SR04
#define SERVO_PIN 10
#define SERVO_CENTER 90   // degrees — sensor points forward
#define TRIG 13           // direct connection OK (3.3V output)
#define ECHO 12           // MUST come through a 5V->3.3V voltage divider

// Wall-following tuning — calibrate on real hardware
const int WF_TURN90_MS           = 700;
const int TURN_PULSE_MS          = 250;
const int FORWARD_PULSE_MS       = 300;
const int TARGET_WALL_CM         = 20;
const int WALL_TOLERANCE_CM      = 5;
const int WF_CORNER_THRESHOLD_CM = 25;
const int WF_OPEN_THRESHOLD_CM   = 50;
const int BASE_SPEED             = 120;
const int TURN_SPEED             = 120;

// Ultrasonic limits
const unsigned long ECHO_TIMEOUT_US = 25000UL;  // ~4.3 m round-trip cap
const long DIST_MIN_CM = 3;
const long DIST_MAX_CM = 250;
const int SERVO_SETTLE_MS = 80;

// Button debounce
const unsigned long DEBOUNCE_MS = 40;

// Sweep angles (telemetry degrees: 0 = forward, negative = left, positive = right)
const int SCAN_ANGLES[] = {-75, -45, -20, 0, 20, 45, 75};
const int SCAN_COUNT = 7;

Servo scanServo;

String currentMode = "STOP";
bool wf_acquired = false;

// Button debounce state
int lastReading = HIGH;
int stableState = HIGH;
unsigned long lastChange = 0;

// Last front distance from a full sweep (telemetry 0 deg)
long lastFrontDistCm = -1;

// ---------------------------------------------------------------------------
// Telemetry helpers
// ---------------------------------------------------------------------------

int telemetryToServo(int telemetryDeg) {
  return SERVO_CENTER - telemetryDeg;
}

int servoToTelemetry(int servoDeg) {
  return SERVO_CENTER - servoDeg;
}

void emitScan(int angleDeg, long distanceCm) {
  Monitor.print("SCAN,");
  Monitor.print(millis());
  Monitor.print(",");
  Monitor.print(angleDeg);
  Monitor.print(",");
  Monitor.print(distanceCm);
  Monitor.print(",");
  Monitor.println(currentMode);
}

void emitMove(const char *action, int durationMs, int speed) {
  Monitor.print("MOVE,");
  Monitor.print(millis());
  Monitor.print(",");
  Monitor.print(action);
  Monitor.print(",");
  Monitor.print(durationMs);
  Monitor.print(",");
  Monitor.println(speed);
}

void emitState(const char *message) {
  Monitor.print("STATE,");
  Monitor.print(millis());
  Monitor.print(",");
  Monitor.print(currentMode);
  Monitor.print(",");
  Monitor.println(message);
}

void setMode(const String &mode) {
  if (currentMode == mode) {
    return;
  }

  currentMode = mode;
  stopMotors();

  if (currentMode == "WALLFOLLOW") {
    wf_acquired = false;
    emitState("wf_start");
  } else if (currentMode == "STOP") {
    emitState("stopped");
  }
}

// ---------------------------------------------------------------------------
// Motor control
// ---------------------------------------------------------------------------

void stopMotors() {
  analogWrite(PWMA, 0);
  analogWrite(PWMB, 0);
}

void driveForward(int durationMs) {
  digitalWrite(AIN1, HIGH);
  digitalWrite(BIN1, HIGH);
  analogWrite(PWMA, BASE_SPEED);
  analogWrite(PWMB, BASE_SPEED);
  delay(durationMs);
  stopMotors();
  emitMove("FORWARD", durationMs, BASE_SPEED);
}

void turnLeft(int durationMs) {
  digitalWrite(AIN1, LOW);
  digitalWrite(BIN1, HIGH);
  analogWrite(PWMA, TURN_SPEED);
  analogWrite(PWMB, TURN_SPEED);
  delay(durationMs);
  stopMotors();
  emitMove("TURN_LEFT", durationMs, TURN_SPEED);
}

void turnRight(int durationMs) {
  digitalWrite(AIN1, HIGH);
  digitalWrite(BIN1, LOW);
  analogWrite(PWMA, TURN_SPEED);
  analogWrite(PWMB, TURN_SPEED);
  delay(durationMs);
  stopMotors();
  emitMove("TURN_RIGHT", durationMs, TURN_SPEED);
}

// ---------------------------------------------------------------------------
// Ultrasonic sensing
// ---------------------------------------------------------------------------

long readDistanceRawCM() {
  digitalWrite(TRIG, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG, LOW);

  unsigned long t0 = micros();
  while (digitalRead(ECHO) == LOW) {
    if (micros() - t0 > ECHO_TIMEOUT_US) {
      return -1;
    }
  }

  unsigned long echoStart = micros();
  while (digitalRead(ECHO) == HIGH) {
    if (micros() - echoStart > ECHO_TIMEOUT_US) {
      return -1;
    }
  }
  unsigned long dur = micros() - echoStart;

  return (long)(dur * 0.0343 / 2.0);
}

long clampDistance(long distanceCm) {
  if (distanceCm < 0) {
    return -1;
  }
  if (distanceCm < DIST_MIN_CM) {
    return DIST_MIN_CM;
  }
  if (distanceCm > DIST_MAX_CM) {
    return DIST_MAX_CM;
  }
  return distanceCm;
}

long medianOf3(long a, long b, long c) {
  if (a > b) { long t = a; a = b; b = t; }
  if (b > c) { long t = b; b = c; c = t; }
  if (a > b) { long t = a; a = b; b = t; }
  return b;
}

long readDistanceCM() {
  long r1 = readDistanceRawCM();
  delay(5);
  long r2 = readDistanceRawCM();
  delay(5);
  long r3 = readDistanceRawCM();
  return clampDistance(medianOf3(r1, r2, r3));
}

long scanAtAngle(int telemetryDeg) {
  int servoDeg = telemetryToServo(telemetryDeg);
  scanServo.write(servoDeg);
  delay(SERVO_SETTLE_MS);
  return readDistanceCM();
}

void fullSweep() {
  stopMotors();

  for (int i = 0; i < SCAN_COUNT; i++) {
    int angle = SCAN_ANGLES[i];
    long dist = scanAtAngle(angle);
    emitScan(angle, dist);
    if (angle == 0) {
      lastFrontDistCm = dist;
    }
  }

  scanServo.write(SERVO_CENTER);
}

long scanRightWall() {
  long d45 = scanAtAngle(45);
  long d75 = scanAtAngle(75);

  if (d45 >= 0 && d75 >= 0) {
    return min(d45, d75);
  }
  if (d45 >= 0) {
    return d45;
  }
  if (d75 >= 0) {
    return d75;
  }
  return -1;
}

long effectiveDistance(long rawCm, long fallbackCm) {
  return (rawCm >= 0) ? rawCm : fallbackCm;
}

// ---------------------------------------------------------------------------
// Wall-following state machine
// ---------------------------------------------------------------------------

void wallFollowStep() {
  fullSweep();

  long front = effectiveDistance(lastFrontDistCm, DIST_MAX_CM);
  long right = effectiveDistance(scanRightWall(), DIST_MAX_CM);

  scanServo.write(SERVO_CENTER);

  // Phase 1 — acquisition: drive forward until a wall is ahead, then turn left.
  if (!wf_acquired) {
    if (front <= WF_CORNER_THRESHOLD_CM) {
      turnLeft(WF_TURN90_MS);
      wf_acquired = true;
      emitState("wf_acquired");
    } else {
      driveForward(FORWARD_PULSE_MS);
    }
    return;
  }

  // Phase 2 — five-case right-hand wall follow.
  if (front <= WF_CORNER_THRESHOLD_CM) {
    emitState("wf_corner");
    turnLeft(WF_TURN90_MS);
  } else if (right > WF_OPEN_THRESHOLD_CM) {
    driveForward(FORWARD_PULSE_MS);
    turnRight(WF_TURN90_MS);
  } else if (right > TARGET_WALL_CM + WALL_TOLERANCE_CM) {
    turnRight(TURN_PULSE_MS / 2);
    driveForward(FORWARD_PULSE_MS);
  } else if (right < TARGET_WALL_CM - WALL_TOLERANCE_CM) {
    turnLeft(TURN_PULSE_MS / 2);
    driveForward(FORWARD_PULSE_MS);
  } else {
    driveForward(FORWARD_PULSE_MS);
  }
}

// ---------------------------------------------------------------------------
// Input handling
// ---------------------------------------------------------------------------

void handleButton() {
  int reading = digitalRead(BUTTON_PIN);
  if (reading != lastReading) {
    lastChange = millis();
    lastReading = reading;
  }

  if (millis() - lastChange > DEBOUNCE_MS && reading != stableState) {
    stableState = reading;
    if (stableState == LOW) {
      if (currentMode == "STOP") {
        setMode("WALLFOLLOW");
      } else {
        setMode("STOP");
      }
    }
  }
}

// ---------------------------------------------------------------------------
// Arduino entry points
// ---------------------------------------------------------------------------

void setup() {
  Monitor.begin(9600);

  pinMode(PWMA, OUTPUT);
  pinMode(PWMB, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(STBY, OUTPUT);
  digitalWrite(STBY, HIGH);

  pinMode(BUTTON_PIN, INPUT);
  pinMode(TRIG, OUTPUT);
  pinMode(ECHO, INPUT);
  digitalWrite(TRIG, LOW);

  scanServo.attach(SERVO_PIN);
  scanServo.write(SERVO_CENTER);

  stopMotors();
  emitState("ready");
}

void loop() {
  handleButton();

  if (currentMode == "WALLFOLLOW") {
    wallFollowStep();
  } else {
    stopMotors();
  }
}
