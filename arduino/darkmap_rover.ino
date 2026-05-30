/*
 * DARKMAP-Q  -  MCU side (Arduino UNO Q / STM32U585, Arduino Core on Zephyr)
 * ---------------------------------------------------------------------------
 * Offline GPS-denied reconnaissance rover. This sketch runs on the real-time
 * microcontroller and is responsible for:
 *   - DC motor control (via a dual H-bridge motor driver)
 *   - SG90 servo sweep that aims the ultrasonic sensor
 *   - HC-SR04 ultrasonic distance measurement
 *   - Pulse-based autonomous obstacle avoidance
 *   - Right-hand wall-following perimeter scan (Roomba-style room mapping)
 *   - Five operating modes: AUTO / MANUAL / SCAN_ONLY / WALLFOLLOW / STOP
 *   - CSV telemetry over Serial for the Linux/Python mapping side
 *
 * Telemetry line formats (one record per line, '\n' terminated):
 *   SCAN,timestamp_ms,angle_deg,distance_cm,mode
 *   MOVE,timestamp_ms,action,duration_ms,speed     (action: FORWARD/BACKWARD/TURN_LEFT/TURN_RIGHT/STOP)
 *   STATE,timestamp_ms,mode,message
 *
 * Single-character commands accepted on Serial (from laptop or Linux side):
 *   a = AUTO,  m = MANUAL,  o = SCAN_ONLY,  w = WALLFOLLOW,  x = STOP
 *   In MANUAL: w/s = forward/back, a/d... (see MANUAL handling below; uses i/k/j/l)
 *
 * =====================  CRITICAL ELECTRICAL WARNING  =======================
 * The Arduino UNO Q uses 3.3V logic on its JDIGITAL / JANALOG headers. It is
 * NOT a 5V Arduino Uno. The HC-SR04 ECHO pin typically outputs 5V, which can
 * damage a 3.3V input. You MUST level-shift the ECHO line before it reaches
 * the UNO Q:
 *
 *     HC-SR04 ECHO ---- 2kOhm ----+---- UNO Q ECHO pin
 *                                 |
 *                               1kOhm
 *                                 |
 *                                GND
 *
 * Do NOT connect ECHO directly. Do NOT use D3 for the ECHO input (D3 is not
 * 5V tolerant). Do NOT power the DC motors or servo directly from the UNO Q;
 * use a separate battery through the motor driver and a common ground.
 * ===========================================================================
 */

#include <Servo.h>

// ---------------------------------------------------------------------------
// Pin configuration  (VERIFY against your motor driver + UNO Q carrier wiring)
// Motor driver control pins are PWM-capable outputs. Adjust as needed.
// ---------------------------------------------------------------------------
#define LEFT_MOTOR_FWD    5   // PWM
#define LEFT_MOTOR_REV    6   // PWM
#define RIGHT_MOTOR_FWD   9   // PWM
#define RIGHT_MOTOR_REV   10  // PWM

#define SERVO_PIN         11  // PWM output to servo signal (avoid D3 for inputs)
#define ULTRASONIC_TRIG   7   // output, 3.3V trigger is accepted by HC-SR04
#define ULTRASONIC_ECHO   8   // input, MUST go through a voltage divider/level shifter

// ---------------------------------------------------------------------------
// Tunable behavior constants  (start slow for clean mapping + safety)
// ---------------------------------------------------------------------------
const int  BASE_SPEED          = 120;  // forward PWM (0-255)
const int  TURN_SPEED          = 120;  // turning PWM (0-255)
const int  OBSTACLE_THRESHOLD  = 30;   // cm; below this the front is "blocked"
const unsigned long FORWARD_PULSE_MS = 300;  // step-based forward burst
const unsigned long TURN_PULSE_MS    = 250;  // step-based turn burst

// Wall-following tuning
// TARGET_WALL_CM: desired gap between rover and the right wall.
// WALL_TOLERANCE_CM: dead-band around the target; inside it we go straight.
// WF_CORNER_THRESHOLD_CM: front distance that triggers a left turn (corner ahead).
// WF_OPEN_THRESHOLD_CM: right-side distance that indicates the rover has drifted
//   past a gap or corner and should turn right to re-acquire the wall.
// WF_TURN90_MS: duration of a 90-degree in-place turn (calibrate on real hardware).
const int  TARGET_WALL_CM        = 20;
const int  WALL_TOLERANCE_CM     = 5;
const int  WF_CORNER_THRESHOLD_CM = 25;
const int  WF_OPEN_THRESHOLD_CM  = 50;
const unsigned long WF_TURN90_MS = 700;  // tune so rover turns ~90 deg in place

// Ultrasonic sensing limits
const long MIN_VALID_CM = 3;     // ignore anything closer than this (noise)
const long MAX_VALID_CM = 250;   // ignore anything farther than this
const unsigned long ECHO_TIMEOUT_US = 25000UL;  // ~4.3m round trip cap

// Servo geometry: 90 deg = straight ahead (robot 0 deg)
const int SERVO_CENTER = 90;
const int SERVO_SETTLE_MS = 120;  // let the servo + sensor settle before reading

// Scan angles relative to the robot heading (negative = left, positive = right)
const int SCAN_ANGLES[] = { -75, -45, -20, 0, 20, 45, 75 };
const int NUM_SCAN_ANGLES = sizeof(SCAN_ANGLES) / sizeof(SCAN_ANGLES[0]);

// ---------------------------------------------------------------------------
// Operating modes
// ---------------------------------------------------------------------------
enum Mode { MODE_AUTO, MODE_MANUAL, MODE_SCAN_ONLY, MODE_WALLFOLLOW, MODE_STOP };
Mode currentMode = MODE_STOP;  // start safe: motors off until told to run

// Wall-follow acquisition flag: true once the rover has found and aligned to
// its first wall.  Reset to false every time WALLFOLLOW mode is entered so the
// rover always starts with a fresh "drive to wall" acquisition pass.
bool wf_acquired = false;

Servo scanServo;

// Forward declarations
void moveForward(int speed);
void moveBackward(int speed);
void turnLeft(int speed);
void turnRight(int speed);
void stopCar();
long readDistanceCM();
int  scanAtAngle(int angle);
void scanAndReport();
void autonomousStep();
void wallFollowStep();
void manualStep(char cmd);
void handleCommand(char cmd);
const char* modeName(Mode m);
void sendScan(int angle, long distance);
void sendMove(const char* action, unsigned long duration_ms, int speed);
void sendState(const char* message);

// Return the closest valid right-side reading (min of front-right and right).
// Using two angles avoids false "open" reads at wall ends where only the
// outer sensor sees past the end of a wall segment.
long scanRightWall() {
  long rSide  = scanAtAngle(75);
  long rFront = scanAtAngle(45);
  long best = MAX_VALID_CM;
  if (rSide  >= 0 && rSide  < best) best = rSide;
  if (rFront >= 0 && rFront < best) best = rFront;
  return (best == MAX_VALID_CM) ? -1 : best;
}

// ===========================================================================
// Setup
// ===========================================================================
void setup() {
  Serial.begin(115200);

  pinMode(LEFT_MOTOR_FWD, OUTPUT);
  pinMode(LEFT_MOTOR_REV, OUTPUT);
  pinMode(RIGHT_MOTOR_FWD, OUTPUT);
  pinMode(RIGHT_MOTOR_REV, OUTPUT);

  pinMode(ULTRASONIC_TRIG, OUTPUT);
  pinMode(ULTRASONIC_ECHO, INPUT);
  digitalWrite(ULTRASONIC_TRIG, LOW);

  scanServo.attach(SERVO_PIN);
  scanServo.write(SERVO_CENTER);

  stopCar();
  delay(500);
  sendState("boot_ok");
}

// ===========================================================================
// Main loop
// ===========================================================================
void loop() {
  // Always service incoming single-character commands first (mode + manual).
  if (Serial.available() > 0) {
    char cmd = (char) Serial.read();
    handleCommand(cmd);
  }

  switch (currentMode) {
    case MODE_AUTO:
      autonomousStep();
      break;

    case MODE_WALLFOLLOW:
      wallFollowStep();
      break;

    case MODE_SCAN_ONLY:
      stopCar();
      scanAndReport();
      delay(150);
      break;

    case MODE_MANUAL:
      // Movement is driven by handleCommand(); we just keep scanning so the
      // map keeps filling in while a human drives.
      scanAndReport();
      break;

    case MODE_STOP:
    default:
      stopCar();
      delay(50);
      break;
  }
}

// ===========================================================================
// Command handling
// ===========================================================================
void handleCommand(char cmd) {
  switch (cmd) {
    case 'a': currentMode = MODE_AUTO;       stopCar(); sendState("mode_auto");       break;
    case 'm': currentMode = MODE_MANUAL;     stopCar(); sendState("mode_manual");     break;
    case 'o': currentMode = MODE_SCAN_ONLY;  stopCar(); sendState("mode_scan_only");  break;
    case 'w': currentMode = MODE_WALLFOLLOW; wf_acquired = false; stopCar(); sendState("mode_wallfollow"); break;
    case 'x': currentMode = MODE_STOP;       stopCar(); sendState("mode_stop");       break;
    default:
      if (currentMode == MODE_MANUAL) {
        manualStep(cmd);
      }
      break;
  }
}

// Manual driving: short pulses so the Linux side can dead-reckon each command.
void manualStep(char cmd) {
  switch (cmd) {
    case 'i':  // forward
      moveForward(BASE_SPEED);
      delay(FORWARD_PULSE_MS);
      stopCar();
      sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);
      break;
    case 'k':  // backward
      moveBackward(BASE_SPEED);
      delay(FORWARD_PULSE_MS);
      stopCar();
      sendMove("BACKWARD", FORWARD_PULSE_MS, BASE_SPEED);
      break;
    case 'j':  // turn left
      turnLeft(TURN_SPEED);
      delay(TURN_PULSE_MS);
      stopCar();
      sendMove("TURN_LEFT", TURN_PULSE_MS, TURN_SPEED);
      break;
    case 'l':  // turn right
      turnRight(TURN_SPEED);
      delay(TURN_PULSE_MS);
      stopCar();
      sendMove("TURN_RIGHT", TURN_PULSE_MS, TURN_SPEED);
      break;
    case ' ':  // explicit stop
      stopCar();
      sendMove("STOP", 0, 0);
      break;
    default:
      break;
  }
}

// ===========================================================================
// Autonomous obstacle avoidance (pulse-based)
//   scan front -> if clear, nudge forward -> else stop, scan L/R, turn to open
// ===========================================================================
void autonomousStep() {
  long front = scanAtAngle(0);

  if (front < 0 || front > OBSTACLE_THRESHOLD) {
    // Path ahead looks clear (or unknown/far): take one short step forward.
    moveForward(BASE_SPEED);
    delay(FORWARD_PULSE_MS);
    stopCar();
    sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);
  } else {
    // Blocked: stop, look left and right, turn toward the more open side.
    stopCar();
    sendState("blocked");

    long leftDist  = scanAtAngle(-75);
    long rightDist = scanAtAngle(75);

    // Treat invalid (-1) as "very far / open" so we still pick a direction.
    long leftScore  = (leftDist  < 0) ? MAX_VALID_CM : leftDist;
    long rightScore = (rightDist < 0) ? MAX_VALID_CM : rightDist;

    if (leftScore >= rightScore) {
      turnLeft(TURN_SPEED);
      delay(TURN_PULSE_MS);
      stopCar();
      sendMove("TURN_LEFT", TURN_PULSE_MS, TURN_SPEED);
    } else {
      turnRight(TURN_SPEED);
      delay(TURN_PULSE_MS);
      stopCar();
      sendMove("TURN_RIGHT", TURN_PULSE_MS, TURN_SPEED);
    }
  }

  // After acting, do a full sweep so the map gets a fresh frame.
  scanAndReport();
}

// ===========================================================================
// Wall-following perimeter scan (right-hand rule)
// ---------------------------------------------------------------------------
// Phase 1 – Acquisition (wf_acquired == false):
//   Drive straight forward until a wall is within WF_CORNER_THRESHOLD_CM,
//   then turn left 90 deg so that wall ends up on the right side.
//
// Phase 2 – Following (wf_acquired == true):
//   1. CORNER  - front too close  -> turn left 90 deg in place.
//   2. OPEN    - right wall lost  -> forward burst + turn right 90 deg.
//      (right distance uses min of 45 deg and 75 deg scans so wall ends
//       do not falsely read as open space)
//   3. TOO FAR - drifting right   -> nudge right + forward.
//   4. TOO CLOSE - too near wall  -> nudge left  + forward.
//   5. ON TRACK               -> drive straight.
//   After every action: full sweep to keep the map dense.
//
// Tune WF_TURN90_MS until the rover turns ~90 degrees in place.
// ===========================================================================
void wallFollowStep() {
  long front = scanAtAngle(0);
  long right  = scanRightWall();

  // Treat sensor misses as "far away / open".
  long frontDist = (front < 0) ? (long)MAX_VALID_CM : front;
  long rightDist = (right < 0) ? (long)MAX_VALID_CM : right;

  // ------------------------------------------------------------------
  // Phase 1: acquisition – drive straight until we see a wall ahead.
  // ------------------------------------------------------------------
  if (!wf_acquired) {
    if (frontDist <= WF_CORNER_THRESHOLD_CM) {
      // Found a wall straight ahead. Turn left 90 deg so it becomes the
      // right-side wall, then switch to following.
      stopCar();
      sendState("wf_acquired");
      turnLeft(TURN_SPEED);
      delay(WF_TURN90_MS);
      stopCar();
      sendMove("TURN_LEFT", WF_TURN90_MS, TURN_SPEED);
      wf_acquired = true;
    } else {
      moveForward(BASE_SPEED);
      delay(FORWARD_PULSE_MS);
      stopCar();
      sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);
    }
    scanAndReport();
    return;
  }

  // ------------------------------------------------------------------
  // Phase 2: wall-following.
  // ------------------------------------------------------------------
  if (frontDist <= WF_CORNER_THRESHOLD_CM) {
    // Wall or inner corner straight ahead -> turn left 90 deg.
    stopCar();
    sendState("wf_corner");
    turnLeft(TURN_SPEED);
    delay(WF_TURN90_MS);
    stopCar();
    sendMove("TURN_LEFT", WF_TURN90_MS, TURN_SPEED);

  } else if (rightDist > WF_OPEN_THRESHOLD_CM) {
    // Right side opened up (outer corner / gap).
    // Overshoot slightly, then turn right to wrap around the corner.
    moveForward(BASE_SPEED);
    delay(FORWARD_PULSE_MS);
    stopCar();
    sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);

    turnRight(TURN_SPEED);
    delay(WF_TURN90_MS);
    stopCar();
    sendMove("TURN_RIGHT", WF_TURN90_MS, TURN_SPEED);

  } else if (rightDist > TARGET_WALL_CM + WALL_TOLERANCE_CM) {
    // Drifting away from right wall -> gentle right correction.
    turnRight(TURN_SPEED);
    delay(TURN_PULSE_MS / 2);
    stopCar();
    sendMove("TURN_RIGHT", TURN_PULSE_MS / 2, TURN_SPEED);

    moveForward(BASE_SPEED);
    delay(FORWARD_PULSE_MS);
    stopCar();
    sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);

  } else if (rightDist < TARGET_WALL_CM - WALL_TOLERANCE_CM) {
    // Too close to right wall -> gentle left correction.
    turnLeft(TURN_SPEED);
    delay(TURN_PULSE_MS / 2);
    stopCar();
    sendMove("TURN_LEFT", TURN_PULSE_MS / 2, TURN_SPEED);

    moveForward(BASE_SPEED);
    delay(FORWARD_PULSE_MS);
    stopCar();
    sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);

  } else {
    // Right wall in target band -> drive straight.
    moveForward(BASE_SPEED);
    delay(FORWARD_PULSE_MS);
    stopCar();
    sendMove("FORWARD", FORWARD_PULSE_MS, BASE_SPEED);
  }

  // Full sweep after every action to densely populate the map.
  scanAndReport();
}

// ===========================================================================
// Servo + ultrasonic scanning
// ===========================================================================

// Move servo to a robot-relative angle, settle, take one reading, report it.
int scanAtAngle(int angle) {
  int servoAngle = SERVO_CENTER + angle;
  if (servoAngle < 0)   servoAngle = 0;
  if (servoAngle > 180) servoAngle = 180;

  scanServo.write(servoAngle);
  delay(SERVO_SETTLE_MS);

  long distance = readDistanceCM();
  sendScan(angle, distance);
  return (int) distance;
}

// Full sweep across all configured angles. Motors are stopped while scanning
// to reduce vibration/jitter and improve readings.
void scanAndReport() {
  stopCar();
  for (int i = 0; i < NUM_SCAN_ANGLES; i++) {
    scanAtAngle(SCAN_ANGLES[i]);
  }
  // Return to center so the next "front" read is quick.
  scanServo.write(SERVO_CENTER);
}

// HC-SR04 read: median of 3 pulses, clamped, returns -1 if invalid.
long readDistanceCM() {
  long readings[3];
  for (int i = 0; i < 3; i++) {
    digitalWrite(ULTRASONIC_TRIG, LOW);
    delayMicroseconds(2);
    digitalWrite(ULTRASONIC_TRIG, HIGH);
    delayMicroseconds(10);
    digitalWrite(ULTRASONIC_TRIG, LOW);

    unsigned long duration = pulseIn(ULTRASONIC_ECHO, HIGH, ECHO_TIMEOUT_US);
    if (duration == 0) {
      readings[i] = -1;  // timeout / no echo
    } else {
      // speed of sound ~ 0.0343 cm/us, divide by 2 for round trip
      long cm = (long)(duration * 0.0343 / 2.0);
      if (cm < MIN_VALID_CM || cm > MAX_VALID_CM) {
        readings[i] = -1;
      } else {
        readings[i] = cm;
      }
    }
    delay(8);  // brief gap so consecutive pings do not interfere
  }

  // Median of 3 (simple sort of 3 elements).
  long a = readings[0], b = readings[1], c = readings[2];
  long med;
  if ((a >= b && a <= c) || (a <= b && a >= c)) med = a;
  else if ((b >= a && b <= c) || (b <= a && b >= c)) med = b;
  else med = c;

  return med;  // may be -1 if readings were invalid
}

// ===========================================================================
// Motor primitives
//   Differential drive: left + right wheel direction sets motion.
// ===========================================================================
void moveForward(int speed) {
  analogWrite(LEFT_MOTOR_FWD, speed);
  analogWrite(LEFT_MOTOR_REV, 0);
  analogWrite(RIGHT_MOTOR_FWD, speed);
  analogWrite(RIGHT_MOTOR_REV, 0);
}

void moveBackward(int speed) {
  analogWrite(LEFT_MOTOR_FWD, 0);
  analogWrite(LEFT_MOTOR_REV, speed);
  analogWrite(RIGHT_MOTOR_FWD, 0);
  analogWrite(RIGHT_MOTOR_REV, speed);
}

void turnLeft(int speed) {
  // Left wheel reverse, right wheel forward -> rotate left in place.
  analogWrite(LEFT_MOTOR_FWD, 0);
  analogWrite(LEFT_MOTOR_REV, speed);
  analogWrite(RIGHT_MOTOR_FWD, speed);
  analogWrite(RIGHT_MOTOR_REV, 0);
}

void turnRight(int speed) {
  // Left wheel forward, right wheel reverse -> rotate right in place.
  analogWrite(LEFT_MOTOR_FWD, speed);
  analogWrite(LEFT_MOTOR_REV, 0);
  analogWrite(RIGHT_MOTOR_FWD, 0);
  analogWrite(RIGHT_MOTOR_REV, speed);
}

void stopCar() {
  analogWrite(LEFT_MOTOR_FWD, 0);
  analogWrite(LEFT_MOTOR_REV, 0);
  analogWrite(RIGHT_MOTOR_FWD, 0);
  analogWrite(RIGHT_MOTOR_REV, 0);
}

// ===========================================================================
// Telemetry helpers (CSV lines on Serial)
// ===========================================================================
const char* modeName(Mode m) {
  switch (m) {
    case MODE_AUTO:       return "AUTO";
    case MODE_MANUAL:     return "MANUAL";
    case MODE_SCAN_ONLY:  return "SCAN_ONLY";
    case MODE_WALLFOLLOW: return "WALLFOLLOW";
    case MODE_STOP:       return "STOP";
    default:              return "UNKNOWN";
  }
}

void sendScan(int angle, long distance) {
  // SCAN,timestamp_ms,angle_deg,distance_cm,mode
  Serial.print("SCAN,");
  Serial.print(millis());
  Serial.print(",");
  Serial.print(angle);
  Serial.print(",");
  Serial.print(distance);
  Serial.print(",");
  Serial.println(modeName(currentMode));
}

void sendMove(const char* action, unsigned long duration_ms, int speed) {
  // MOVE,timestamp_ms,action,duration_ms,speed
  Serial.print("MOVE,");
  Serial.print(millis());
  Serial.print(",");
  Serial.print(action);
  Serial.print(",");
  Serial.print(duration_ms);
  Serial.print(",");
  Serial.println(speed);
}

void sendState(const char* message) {
  // STATE,timestamp_ms,mode,message
  Serial.print("STATE,");
  Serial.print(millis());
  Serial.print(",");
  Serial.print(modeName(currentMode));
  Serial.print(",");
  Serial.println(message);
}
