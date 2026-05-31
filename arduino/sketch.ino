// last working sketch

#include <Servo.h>
#include <Wire.h>
#include <math.h>
#include <Modulino.h>
#include <Arduino_RouterBridge.h>

// Elegoo V4 motor pins (TB6612 shield)
#define PWMA 5
#define PWMB 6
#define AIN1 7
#define BIN1 8
#define STBY 3
#define BUTTON_PIN 2   // active-LOW: idles HIGH, reads LOW when pressed

// Servo-mounted Modulino Distance (VL53L4CD ToF, I2C 0x29 on Qwiic / Wire1)
#define SERVO_PIN 10
#define SERVO_CENTER 90   // degrees — sensor points forward

// Wall-following tuning — calibrate on real hardware
const int WF_TURN90_MS           = 500;
const int TURN_PULSE_MS          = 100;
const int FORWARD_PULSE_MS       = 300;
const int TARGET_WALL_CM         = 30; // Desired gap to the left wall +- WALL_TOLERANCE_CM
const int WALL_TOLERANCE_CM      = 15;
const int WF_CORNER_THRESHOLD_CM = 15; // How close something in front can get before a left pivot (inner corner / acquisition)
const int WF_OPEN_THRESHOLD_CM   = 45; // left distance that counts as "wall lost" → triggers an outer-corner turn right.
// WF_OPEN_THRESHOLD_CM must stay above TARGET_WALL_CM + WALL_TOLERANCE_CM.
const int BASE_SPEED             = 120;
const int TURN_SPEED             = 120;

// MPU6050 gyro (I2C: SDA=A4, SCL=A5) — exact turns + heading telemetry
#define MPU_ADDR                 0x68
const float GYRO_SENS              = 131.0f;  // LSB/(deg/s) at +/-250 deg/s
const int GYRO_SIGN                = 1;       // flip to -1 if left turn reads negative
const int WF_TURN_ANGLE_DEG        = 90;
const int NUDGE_ANGLE_DEG          = 12;
// Cut motors this many degrees early so coast/momentum lands near target.
const float TURN_LEAD_DEG          = 10.0f;
const unsigned long TURN_TIMEOUT_MS = 3000UL;
const int GYRO_BIAS_SAMPLES        = 1000;

// ToF limits (VL53L4CD: 0–1200 mm usable, clamp to 130 cm for mapping)
const long DIST_MIN_CM = 2;
const long DIST_MAX_CM = 130;
const int SERVO_SETTLE_MS = 60;
const unsigned long TOF_READ_TIMEOUT_MS = 40;  // ~2 ranging cycles

// Button debounce
const unsigned long DEBOUNCE_MS = 40;

// Wall-follow debug telemetry (wf_decide STATE lines forwarded to laptop)
#define DEBUG_WF 1

// Staleness cap for last valid left-wall reading when side scan fails
const unsigned long LEFT_CACHE_MS = 500;

// Sweep angles (telemetry degrees: 0 = forward, negative = left, positive = right)
const int SCAN_ANGLES[] = {-75, -45, -20, 0, 20, 45, 75};
const int SCAN_COUNT = 7;

Servo scanServo;
ModulinoDistance tofSensor;
bool tofOk = false;

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

// MPU6050 state (continuous unwrapped yaw for closed-loop turns)
bool imuOk = false;
float yawDeg = 0.0f;
float gyroBiasZ = 0.0f;
unsigned long lastYawUs = 0;

// ---------------------------------------------------------------------------
// Telemetry helpers
// ---------------------------------------------------------------------------

int telemetryToServo(int telemetryDeg) {
  return SERVO_CENTER - telemetryDeg;
}

int servoToTelemetry(int servoDeg) {
  return SERVO_CENTER - servoDeg;
}

// Push one CSV telemetry line to the UNO Q Linux side via Bridge RPC.
void emitTelemetry(const String &line) {
  Bridge.notify("telemetry", line.c_str());
}

void emitScan(int angleDeg, long distanceCm) {
  emitTelemetry("SCAN," + String(millis()) + "," + String(angleDeg) + ","
                + String(distanceCm) + "," + currentMode);
}

void emitMove(const char *action, int durationMs, int speed) {
  emitTelemetry("MOVE," + String(millis()) + "," + String(action) + ","
                + String(durationMs) + "," + String(speed));
}

void emitState(const char *message) {
  emitTelemetry("STATE," + String(millis()) + "," + currentMode + ","
                + String(message));
}

void emitHeading();

void emitTofStatus() {
  emitState(tofOk ? "tof_ready" : "tof_absent");
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
// MPU6050 gyro (raw Wire — no external library)
// ---------------------------------------------------------------------------

void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg);
  Wire.write(val);
  Wire.endTransmission();
}

int16_t mpuReadGyroZ() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x47);  // GYRO_ZOUT_H
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)2, (uint8_t)true);
  if (Wire.available() < 2) {
    return 0;
  }
  int16_t hi = Wire.read();
  int16_t lo = Wire.read();
  return (int16_t)((hi << 8) | lo);
}

bool mpuInit() {
  Wire.begin();
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x75);  // WHO_AM_I
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, (uint8_t)1, (uint8_t)true);
  if (Wire.available() < 1 || Wire.read() != 0x68) {
    return false;
  }
  mpuWrite(0x6B, 0x00);  // wake
  mpuWrite(0x1A, 0x03);  // DLPF ~44 Hz
  mpuWrite(0x1B, 0x00);  // gyro +/-250 deg/s
  delay(50);
  lastYawUs = micros();
  return true;
}

void calibrateGyroBias() {
  if (!imuOk) {
    emitState("imu_absent");
    return;
  }
  emitState("imu_calibrating");
  delay(500);
  float sum = 0.0f;
  for (int i = 0; i < GYRO_BIAS_SAMPLES; i++) {
    sum += (float)mpuReadGyroZ();
    delay(2);
  }
  gyroBiasZ = sum / (float)GYRO_BIAS_SAMPLES;
  yawDeg = 0.0f;
  lastYawUs = micros();
  emitState("imu_ready");
}

void updateYaw() {
  if (!imuOk) {
    return;
  }
  unsigned long nowUs = micros();
  float dt = (nowUs - lastYawUs) / 1000000.0f;
  lastYawUs = nowUs;
  if (dt <= 0.0f || dt > 0.5f) {
    return;
  }
  float gz = (float)mpuReadGyroZ() - gyroBiasZ;
  yawDeg += (float)GYRO_SIGN * (gz / GYRO_SENS) * dt;
}

float wrapYawDeg(float deg) {
  while (deg > 180.0f) {
    deg -= 360.0f;
  }
  while (deg < -180.0f) {
    deg += 360.0f;
  }
  return deg;
}

void emitHeading() {
  if (!imuOk) {
    return;
  }
  emitTelemetry("HEADING," + String(millis()) + ","
                + String(wrapYawDeg(yawDeg), 2));
}

// ---------------------------------------------------------------------------
// Motor control
// ---------------------------------------------------------------------------

void stopMotors() {
  analogWrite(PWMA, 0);
  analogWrite(PWMB, 0);
}

void setLeftSpin() {
  digitalWrite(AIN1, LOW);
  digitalWrite(BIN1, HIGH);
  analogWrite(PWMA, TURN_SPEED);
  analogWrite(PWMB, TURN_SPEED);
}

void setRightSpin() {
  digitalWrite(AIN1, HIGH);
  digitalWrite(BIN1, LOW);
  analogWrite(PWMA, TURN_SPEED);
  analogWrite(PWMB, TURN_SPEED);
}

int fallbackTurnMs(float deltaDeg) {
  return (int)((fabs(deltaDeg) / 90.0f) * (float)WF_TURN90_MS + 0.5f);
}

void driveForward(int durationMs) {
  digitalWrite(AIN1, HIGH);
  digitalWrite(BIN1, HIGH);
  analogWrite(PWMA, BASE_SPEED);
  analogWrite(PWMB, BASE_SPEED);
  unsigned long t0 = millis();
  while (millis() - t0 < (unsigned long)durationMs) {
    if (imuOk) {
      updateYaw();
    } else {
      delay(1);
    }
  }
  stopMotors();
  emitMove("FORWARD", durationMs, BASE_SPEED);
  if (imuOk) {
    emitHeading();
  }
}

void turnByAngle(float deltaDeg) {
  if (!imuOk) {
    int ms = fallbackTurnMs(deltaDeg);
    if (deltaDeg >= 0.0f) {
      turnLeft(ms);
    } else {
      turnRight(ms);
    }
    return;
  }

  float startYaw = yawDeg;
  // Stop early by the lead angle to pre-empt coast; never below zero.
  float target = fabs(deltaDeg) - TURN_LEAD_DEG;
  if (target < 0.0f) {
    target = 0.0f;
  }
  if (deltaDeg >= 0.0f) {
    setLeftSpin();
  } else {
    setRightSpin();
  }

  unsigned long t0 = millis();
  while (fabs(yawDeg - startYaw) < target && millis() - t0 < TURN_TIMEOUT_MS) {
    updateYaw();
  }
  stopMotors();

  unsigned long elapsed = millis() - t0;
  if (deltaDeg >= 0.0f) {
    emitMove("TURN_LEFT", (int)elapsed, TURN_SPEED);
  } else {
    emitMove("TURN_RIGHT", (int)elapsed, TURN_SPEED);
  }
  emitHeading();
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
// ToF distance sensing (Modulino Distance / VL53L4CD)
// ---------------------------------------------------------------------------

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

long readDistanceCM() {
  if (!tofOk) {
    return -1;
  }
  unsigned long t0 = millis();
  while (millis() - t0 < TOF_READ_TIMEOUT_MS) {
    if (tofSensor.available()) {
      float mm = tofSensor.get();
      if (isnan(mm)) {
        return -1;
      }
      return clampDistance((long)(mm / 10.0f + 0.5f));
    }
  }
  return -1;
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
  emitTelemetry("STATE," + String(millis()) + ",WALLFOLLOW,wf_decide,f="
                + String(frontCm) + ",l=" + String(leftCm) + ",lv="
                + String(leftRawValid ? 1 : 0) + ",b=" + String(branch));
}
#endif

// ---------------------------------------------------------------------------
// Wall-following state machine
// ---------------------------------------------------------------------------

void wallFollowStep() {
  if (imuOk) {
    updateYaw();
    emitHeading();
  }
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
      turnByAngle((float)WF_TURN_ANGLE_DEG);
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
    turnByAngle((float)WF_TURN_ANGLE_DEG);
#if DEBUG_WF
    emitWfDecide(frontRaw, left, leftRawValid, "inner");
#endif
  } else if (leftRawValid && leftRaw > WF_OPEN_THRESHOLD_CM) {
    // Outer corner: left wall ended. Overshoot, then wrap toward the wall.
    driveForward(FORWARD_PULSE_MS);
    turnByAngle((float)(-WF_TURN_ANGLE_DEG));
#if DEBUG_WF
    emitWfDecide(front, leftRaw, true, "outer");
#endif
  } else if (left >= 0 && left > TARGET_WALL_CM + WALL_TOLERANCE_CM) {
    // Drifting away from the left wall: nudge back toward it.
    turnByAngle((float)(-NUDGE_ANGLE_DEG));
    driveForward(FORWARD_PULSE_MS);
#if DEBUG_WF
    emitWfDecide(front, left, leftRawValid, "nudge_to_wall");
#endif
  } else if (left >= 0 && left < TARGET_WALL_CM - WALL_TOLERANCE_CM) {
    // Too close to the left wall: nudge away from it.
    turnByAngle((float)NUDGE_ANGLE_DEG);
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
  Bridge.begin();

  pinMode(PWMA, OUTPUT);
  pinMode(PWMB, OUTPUT);
  pinMode(AIN1, OUTPUT);
  pinMode(BIN1, OUTPUT);
  pinMode(STBY, OUTPUT);
  digitalWrite(STBY, HIGH);

  pinMode(BUTTON_PIN, INPUT);

  scanServo.attach(SERVO_PIN);
  scanServo.write(SERVO_CENTER);

  // Modulino Distance is on the Qwiic connector, which is a separate I2C bus
  // (Wire1) from the A4/A5 pins (Wire) used by the MPU6050. Use the library
  // default bus for Qwiic.
  Modulino.begin();
  tofOk = tofSensor.begin();
  emitTofStatus();

  imuOk = mpuInit();
  calibrateGyroBias();

  stopMotors();
  emitState("ready");
}

void loop() {
  if (imuOk) {
    updateYaw();
  }
  handleButton();

  if (currentMode == "WALLFOLLOW") {
    wallFollowStep();
  } else {
    stopMotors();
  }
}