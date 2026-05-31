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
const int WF_TURN90_MS           = 500;
const int TURN_PULSE_MS          = 100;
const int FORWARD_PULSE_MS       = 500;
const int TARGET_WALL_CM         = 50; // Desired gap to the left wall +- WALL_TOLERANCE_CM
const int WALL_TOLERANCE_CM      = 25;
const int WF_CORNER_THRESHOLD_CM = 50; // How close something in front can get before a left pivot (inner corner / acquisition)
const int WF_OPEN_THRESHOLD_CM   = 75; // left distance that counts as "wall lost" → triggers an outer-corner turn right.
// WF_OPEN_THRESHOLD_CM must stay above TARGET_WALL_CM + WALL_TOLERANCE_CM.
const int BASE_SPEED             = 120;
const int TURN_SPEED             = 120;

// Ultrasonic limits
const unsigned long ECHO_TIMEOUT_US = 25000UL;  // ~4.3 m round-trip cap
const long DIST_MIN_CM = 3;
const long DIST_MAX_CM = 250;
const int SERVO_SETTLE_MS = 80;

// Button debounce
const unsigned long DEBOUNCE_MS = 40;

// Wall-follow debug telemetry (wf_decide STATE lines on Monitor)
#define DEBUG_WF 1

// Staleness cap for last valid left-wall reading when side scan fails
const unsigned long LEFT_CACHE_MS = 500;

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

// Cached distances from the latest fullSweep (same index as SCAN_ANGLES)
long lastSweepDistCm[SCAN_COUNT];

// Last front distance from a full sweep (telemetry 0 deg)
long lastFrontDistCm = -1;

// Last valid min(-45°, -75°) left-wall reading
long lastValidLeftCm = -1;
unsigned long lastValidLeftMs = 0;

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
    lastValidLeftCm = -1;
    lastValidLeftMs = 0;
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
    // Out of range: report invalid rather than a fake wall at DIST_MAX_CM.
    return -1;
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
    lastSweepDistCm[i] = dist;
    emitScan(angle, dist);
    if (angle == 0) {
      lastFrontDistCm = dist;
    }
  }

  scanServo.write(SERVO_CENTER);
}

// Combine the two left-side beams. Using min(-45°, -75°) prevents false
// "wall lost" reads at wall segment ends where the outer beam sees past
// the edge.
long combineSideWall(long dInner, long dOuter) {
  if (dInner >= 0 && dOuter >= 0) {
    return min(dInner, dOuter);
  }
  if (dInner >= 0) {
    return dInner;
  }
  if (dOuter >= 0) {
    return dOuter;
  }
  return -1;
}

long leftWallFromSweep() {
  long d45 = -1;
  long d75 = -1;

  for (int i = 0; i < SCAN_COUNT; i++) {
    if (SCAN_ANGLES[i] == -45) {
      d45 = lastSweepDistCm[i];
    } else if (SCAN_ANGLES[i] == -75) {
      d75 = lastSweepDistCm[i];
    }
  }

  return combineSideWall(d45, d75);
}

long effectiveFront(long rawCm) {
  return (rawCm >= 0) ? rawCm : DIST_MAX_CM;
}

// Raw left from sweep; updates last-valid cache when fresh.
long resolveLeftDistance(long rawLeftCm, bool *rawValidOut) {
  if (rawValidOut != NULL) {
    *rawValidOut = (rawLeftCm >= 0);
  }

  if (rawLeftCm >= 0) {
    lastValidLeftCm = rawLeftCm;
    lastValidLeftMs = millis();
    return rawLeftCm;
  }

  if (lastValidLeftCm >= 0 &&
      millis() - lastValidLeftMs <= LEFT_CACHE_MS) {
    return lastValidLeftCm;
  }

  return -1;
}

#if DEBUG_WF
void emitWfDecide(long frontCm, long leftCm, bool leftRawValid,
                  const char *branch) {
  Monitor.print("STATE,");
  Monitor.print(millis());
  Monitor.print(",WALLFOLLOW,wf_decide,f=");
  Monitor.print(frontCm);
  Monitor.print(",l=");
  Monitor.print(leftCm);
  Monitor.print(",lv=");
  Monitor.print(leftRawValid ? 1 : 0);
  Monitor.print(",b=");
  Monitor.println(branch);
}
#endif

// ---------------------------------------------------------------------------
// Wall-following state machine
// ---------------------------------------------------------------------------

void wallFollowStep() {
  fullSweep();

  long frontRaw = lastFrontDistCm;
  long front = effectiveFront(frontRaw);
  long leftRaw = leftWallFromSweep();
  bool leftRawValid = false;
  long left = resolveLeftDistance(leftRaw, &leftRawValid);

  // Phase 1 — acquisition: drive forward until a wall is ahead, then reorient
  // so the wall sits on the left, then nudge forward to clear the corner.
  if (!wf_acquired) {
    if (frontRaw >= 0 && frontRaw <= WF_CORNER_THRESHOLD_CM) {
      turnLeft(WF_TURN90_MS);
      driveForward(FORWARD_PULSE_MS);
      wf_acquired = true;
      emitState("wf_acquired");
#if DEBUG_WF
      emitWfDecide(frontRaw, leftRaw, leftRawValid, "acquired");
#endif
    } else {
      driveForward(FORWARD_PULSE_MS);
#if DEBUG_WF
      emitWfDecide(front, left, leftRawValid, "seek_wall");
#endif
    }
    return;
  }

  // Phase 2 — left-hand wall follow (one motion per scan). The left wall is
  // sensed from the sweep (-45°/-75°); no scanning turns are needed.
  if (frontRaw >= 0 && frontRaw <= WF_CORNER_THRESHOLD_CM) {
    // Inner corner: something ahead. Turn away from the left wall.
    emitState("wf_corner");
    turnLeft(WF_TURN90_MS);
#if DEBUG_WF
    emitWfDecide(frontRaw, left, leftRawValid, "inner");
#endif
  } else if (leftRawValid && leftRaw > WF_OPEN_THRESHOLD_CM) {
    // Outer corner: left wall ended. Overshoot, then wrap toward the wall.
    driveForward(FORWARD_PULSE_MS);
    turnRight(WF_TURN90_MS);
#if DEBUG_WF
    emitWfDecide(front, leftRaw, true, "outer");
#endif
  } else if (left >= 0 && left > TARGET_WALL_CM + WALL_TOLERANCE_CM) {
    // Drifting away from the left wall: nudge back toward it.
    turnRight(TURN_PULSE_MS / 2);
    driveForward(FORWARD_PULSE_MS);
#if DEBUG_WF
    emitWfDecide(front, left, leftRawValid, "nudge_to_wall");
#endif
  } else if (left >= 0 && left < TARGET_WALL_CM - WALL_TOLERANCE_CM) {
    // Too close to the left wall: nudge away from it.
    turnLeft(TURN_PULSE_MS / 2);
    driveForward(FORWARD_PULSE_MS);
#if DEBUG_WF
    emitWfDecide(front, left, leftRawValid, "nudge_off_wall");
#endif
  } else {
    driveForward(FORWARD_PULSE_MS);
#if DEBUG_WF
    emitWfDecide(front, left, leftRawValid, "straight");
#endif
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
