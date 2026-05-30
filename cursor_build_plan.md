# Cursor Build Prompt: DARKMAP Offline Reconnaissance Rover

You are helping build a 48-hour hackathon prototype called **DARKMAP**.

DARKMAP is an **offline GPS-denied reconnaissance rover** using an RC car kit, Arduino, ultrasonic sensor, servo scanner, and optional laptop visualization. The goal is to map a pitch-black 2D indoor area without internet, GPS, or visible light.

The project is for an **Autonomous Navigation & Edge AI Hardware+ defense-oriented hackathon track**. The RC car is only the test platform. The real concept is a **modular sensing/navigation payload** that could scale to drones, UGVs, or defense robotics.

---

## Core Objective

Build a working prototype that can:

1. Move forward, backward, left, right, and stop.
2. Detect obstacles in pitch-black conditions using an ultrasonic sensor.
3. Scan left, center, and right using a servo-mounted ultrasonic sensor.
4. Autonomously avoid obstacles.
5. Send sensor readings to a laptop through serial USB.
6. Display a simple live 2D map/radar visualization on the laptop.
7. Run offline with no internet connection required after setup.

---

## Project Name

**DARKMAP: Offline Reconnaissance Mapping Module for GPS-Denied Environments**

---

## Hardware Assumptions

The kit likely includes:

- Arduino Uno or Elegoo-compatible board
- RC car chassis
- DC motors
- Motor driver module or motor shield
- Ultrasonic sensor, likely HC-SR04
- Servo motor, likely SG90
- MPU6050 gyro/accelerometer, optional
- IR remote/receiver, optional
- USB cable
- Battery pack
- Laptop for visualization

Do not assume internet connectivity during demo.

---

## Repository Structure

Create this structure:

```text
DARKMAP/
├── arduino/
│   └── darkmap_rover/
│       └── darkmap_rover.ino
├── laptop/
│   ├── live_map.py
│   └── requirements.txt
├── docs/
│   ├── demo_script.md
│   ├── wiring_notes.md
│   └── pitch_notes.md
└── README.md
```

---

# Part 1: Arduino Code Requirements

Create the Arduino file:

```text
arduino/darkmap_rover/darkmap_rover.ino
```

The Arduino code must handle:

- Motor movement
- Ultrasonic distance readings
- Servo scanning
- Simple autonomous navigation
- Serial data output for laptop mapping

---

## Arduino Pin Configuration

Use clearly editable constants at the top of the file.

Example placeholder pins:

```cpp
// Motor pins - update based on actual motor driver wiring
const int LEFT_MOTOR_FORWARD = 5;
const int LEFT_MOTOR_BACKWARD = 6;
const int RIGHT_MOTOR_FORWARD = 9;
const int RIGHT_MOTOR_BACKWARD = 10;

// Ultrasonic sensor pins
const int TRIG_PIN = 12;
const int ECHO_PIN = 13;

// Servo pin
const int SERVO_PIN = 3;

// Speed settings
const int DRIVE_SPEED = 130;
const int TURN_SPEED = 120;

// Distance threshold in cm
const int OBSTACLE_THRESHOLD_CM = 30;
```

Add comments that these pins may need to be changed based on the Elegoo board or motor shield.

---

## Arduino Functions to Implement

Implement these functions:

```cpp
void moveForward();
void moveBackward();
void turnLeft();
void turnRight();
void stopCar();
long readDistanceCM();
long scanAtAngle(int angle);
void performFullScan();
void autonomousStep();
void sendScanData(int angle, long distance);
```

---

## Motor Control Logic

Use PWM with `analogWrite()` if using simple motor pins.

Movement behavior:

```text
Forward:
- left motor forward
- right motor forward

Backward:
- left motor backward
- right motor backward

Turn left:
- left motor backward or stop
- right motor forward

Turn right:
- left motor forward
- right motor backward or stop

Stop:
- all motor pins 0
```

Use conservative speeds between 100 and 150.

---

## Ultrasonic Distance Reading

Implement HC-SR04 logic:

```cpp
long readDistanceCM() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) {
    return 999;
  }

  long distance = duration * 0.034 / 2;
  return distance;
}
```

Use timeout to prevent blocking.

Clamp unreasonable distances:

```cpp
if (distance < 2 || distance > 400) distance = 999;
```

---

## Servo Scanning

Mount ultrasonic sensor on servo.

Use angles:

```text
30° = left
60° = slight left
90° = center
120° = slight right
150° = right
```

Implement:

```cpp
long scanAtAngle(int angle) {
  scannerServo.write(angle);
  delay(250);
  long d = readDistanceCM();
  sendScanData(angle, d);
  return d;
}
```

Full scan:

```cpp
void performFullScan() {
  scanAtAngle(30);
  scanAtAngle(60);
  scanAtAngle(90);
  scanAtAngle(120);
  scanAtAngle(150);
}
```

---

## Autonomous Navigation Logic

Implement simple obstacle avoidance:

```text
1. Scan center.
2. If center distance > threshold:
   - move forward briefly
   - stop
3. If center distance <= threshold:
   - stop
   - scan left and right
   - turn toward the side with more free space
4. Repeat
```

Use short movement pulses to reduce crash risk:

```cpp
moveForward();
delay(250);
stopCar();
delay(100);
```

Turning:

```cpp
turnLeft();
delay(350);
stopCar();
```

or:

```cpp
turnRight();
delay(350);
stopCar();
```

---

## Serial Output Format

Arduino must output machine-readable lines to Serial at 115200 baud.

Use this CSV-like format:

```text
SCAN,angle,distance
MOVE,action,duration_ms
STATUS,message
```

Examples:

```text
SCAN,90,45
SCAN,30,120
MOVE,FORWARD,250
MOVE,LEFT,350
STATUS,OBSTACLE_DETECTED
```

This makes Python parsing simple.

---

## Arduino Setup

In `setup()`:

```cpp
Serial.begin(115200);
pinMode(...);
scannerServo.attach(SERVO_PIN);
scannerServo.write(90);
stopCar();
Serial.println("STATUS,DARKMAP_READY");
```

---

## Arduino Loop

In `loop()`:

```cpp
autonomousStep();
delay(100);
```

Optional later: add serial command mode for manual control.

---

# Part 2: Python Laptop Mapping Code

Create:

```text
laptop/live_map.py
```

The Python code must:

1. Connect to Arduino through serial.
2. Read lines such as `SCAN,90,45`.
3. Convert angle + distance into x/y points.
4. Plot live radar/2D occupancy view using matplotlib.
5. Work offline.

---

## Python Dependencies

Create:

```text
laptop/requirements.txt
```

Include:

```text
pyserial
matplotlib
numpy
```

---

## Python Serial Setup

Use configurable serial port at top:

```python
SERIAL_PORT = "/dev/cu.usbmodem1101"  # Mac example; update as needed
BAUD_RATE = 115200
```

Also include common alternatives in comments:

```python
# Windows example: COM3
# Linux example: /dev/ttyUSB0 or /dev/ttyACM0
```

---

## Python Mapping Logic

Assume the robot is initially at `(0, 0)` facing upward.

For MVP radar mode:

```python
x = distance_cm * math.cos(math.radians(angle - 90))
y = distance_cm * math.sin(math.radians(angle - 90))
```

Important:

- Servo angle 90° is forward.
- 30° is left.
- 150° is right.
- Ignore distance values like 999.

Store points in a list:

```python
obstacle_points = []
```

When receiving a `SCAN` line, append a point.

---

## Live Plot Requirements

Use matplotlib animation or repeated plotting.

Display:

- Robot position at origin
- Obstacle points
- Current scan direction if possible
- Axis limits around -200 to 200 cm
- Title: `DARKMAP Live Offline 2D Scan`

Add labels:

```text
X distance cm
Y distance cm
```

The plot should update live as data arrives.

---

## Recommended Python Behavior

When script starts:

```text
DARKMAP live mapping started.
Waiting for Arduino data...
```

When Arduino sends status:

```text
Arduino: DARKMAP_READY
```

If serial connection fails, print helpful error:

```text
Could not open serial port. Check cable, port name, and Arduino Serial Monitor.
```

---

# Part 3: Optional Manual Control Mode

Only implement if the main autonomous mode works.

Allow laptop keyboard input to send commands to Arduino:

```text
w = forward
s = backward
a = left
d = right
x = stop
m = full scan
q = quit
```

Arduino would read Serial commands and execute movement.

This is optional. Do not prioritize over autonomous movement and mapping.

---

# Part 4: Optional MPU6050 Heading Support

Only implement if there is time.

Purpose:

- Improve turn estimation.
- Track approximate heading.
- Show judges that this can support GPS-denied movement tracking.

Do not make this required for MVP.

Create a placeholder section in code comments:

```cpp
// TODO: Add MPU6050 yaw correction for improved GPS-denied heading estimation.
```

---

# Part 5: README Requirements

Create:

```text
README.md
```

Include:

## Project Summary

DARKMAP is an offline GPS-denied reconnaissance mapping module. It uses ultrasonic scanning and autonomous movement logic to explore dark environments without internet, GPS, or visible light.

## Why It Matters

In defense, rescue, and disaster-response environments, robots may need to operate where:

- GPS is unavailable
- Internet is unreliable
- Lighting is poor or absent
- Human entry is risky

## MVP Features

- Offline operation
- Pitch-black obstacle detection
- Servo-based ultrasonic scan
- Simple autonomous navigation
- USB serial telemetry
- Laptop live 2D map

## How to Upload Arduino Code

1. Open Arduino IDE.
2. Open `arduino/darkmap_rover/darkmap_rover.ino`.
3. Select board: Arduino Uno.
4. Select correct port.
5. Upload.
6. Open Serial Monitor at 115200 baud to test.

## How to Run Mapping Code

```bash
cd laptop
pip install -r requirements.txt
python live_map.py
```

## Demo Steps

1. Build cardboard/dark room test area.
2. Connect Arduino to laptop.
3. Run `live_map.py`.
4. Start rover.
5. Turn off lights.
6. Show rover scanning and avoiding obstacles.
7. Show live 2D map.
8. Explain that the system runs offline.

## Known Limitations

- Ultrasonic mapping is rough, not LiDAR-grade.
- Without wheel encoders, robot position estimation drifts.
- Thin or soft obstacles may be missed.
- Current MVP is a proof-of-concept sensing module.

## Future Improvements

- Add 2D LiDAR
- Add wheel encoders
- Add IR camera and onboard object detection
- Add multi-rover offline coordination
- Add return-to-start behavior
- Add compact 3D-printed modular mount for drones/UGVs

---

# Part 6: Demo Script

Create:

```text
docs/demo_script.md
```

Include this script:

```markdown
# DARKMAP Demo Script

## 30-Second Pitch

DARKMAP is an offline reconnaissance mapping module for GPS-denied and pitch-black environments. Our prototype uses an RC rover as a test platform, but the system is designed as a modular payload that can scale to drones, ground robots, or defense robotics platforms.

It does not require internet, GPS, or visible light. It scans with ultrasonic sensing, avoids obstacles, and sends telemetry to a local laptop that builds a simple live 2D map.

## Live Demo Flow

1. Show the rover and sensor module.
2. Explain the ultrasonic sensor on servo scanner.
3. Disconnect internet or mention offline operation.
4. Run the Python mapping screen.
5. Start autonomous mode.
6. Let rover scan and move inside dark/covered test area.
7. Show detected obstacle points appearing on map.
8. Explain current limitations and future upgrades.

## Key Judge Message

This is not just an RC car. The RC car is the test platform. The real innovation is the offline sensing and navigation payload for GPS-denied reconnaissance.
```

---

# Part 7: Wiring Notes

Create:

```text
docs/wiring_notes.md
```

Include a clear wiring checklist:

```markdown
# Wiring Notes

## Ultrasonic HC-SR04

- VCC -> 5V
- GND -> GND
- TRIG -> Arduino pin 12
- ECHO -> Arduino pin 13

## Servo SG90

- Brown/Black -> GND
- Red -> 5V
- Orange/Yellow -> Arduino pin 3

## Motors

Motor wiring depends on the motor driver or shield. Update pin constants in the Arduino sketch:

- LEFT_MOTOR_FORWARD
- LEFT_MOTOR_BACKWARD
- RIGHT_MOTOR_FORWARD
- RIGHT_MOTOR_BACKWARD

## Important

Use a separate battery pack for motors if possible. Make sure Arduino GND and motor driver GND are connected together.
```

---

# Part 8: Pitch Notes

Create:

```text
docs/pitch_notes.md
```

Include:

```markdown
# Pitch Notes

## Main Positioning

DARKMAP is a modular offline reconnaissance payload, not merely an RC car.

## Problem

Defense and rescue environments may be dark, GPS-denied, and disconnected from the internet. Sending humans into unknown areas is risky.

## Solution

A low-cost autonomous sensing module that can detect obstacles, navigate, and produce a rough 2D map using only onboard sensors and local computation.

## Why It Fits the Track

- Autonomous navigation
- Edge/offline operation
- RC car hardware modification
- GPS-denied movement concept
- Defense-oriented reconnaissance use case
- Scalable to drones and ground robots

## Honest Limitations

The prototype uses ultrasonic scanning, so the map is approximate. Future versions would integrate LiDAR, wheel encoders, onboard AI cameras, and multi-robot coordination.
```

---

# Important Implementation Priorities

Build in this order:

1. Arduino motor movement.
2. Ultrasonic distance reading.
3. Servo scanning.
4. Basic obstacle avoidance.
5. Serial output.
6. Python live map.
7. Demo docs.
8. Optional manual mode.
9. Optional MPU6050 heading.

Do not over-engineer. Prioritize a reliable live demo.

---

# Acceptance Criteria

The project is successful if:

- The rover moves without crashing constantly.
- It stops before obstacles.
- It scans left and right.
- It chooses a direction with more space.
- It prints `SCAN,angle,distance` to Serial.
- The Python script reads the Serial data.
- The laptop shows a live 2D visualization.
- The demo can be explained as an offline reconnaissance payload.

---

# Final Reminder

This is a hackathon MVP. Reliability beats complexity.

The winning story is:

> DARKMAP enables low-cost offline reconnaissance in dark, GPS-denied, disconnected environments using a modular sensing and navigation payload that can scale beyond the RC rover platform.
