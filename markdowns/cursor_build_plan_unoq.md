# Cursor Build Plan — DARKMAP-Q

## Project
**DARKMAP-Q: Offline GPS-Denied Reconnaissance Mapping Rover using Arduino UNO Q**

This project builds an autonomous RC-car reconnaissance rover that can operate in pitch-black environments with little or no internet connection. The rover uses an ultrasonic sensor mounted on a servo to scan the environment, avoid obstacles, and generate a rough 2D map. The Arduino UNO Q is used as a dual-processor platform: the MCU handles real-time motor/sensor control, while the Linux side handles mapping, logging, visualization, and optional edge-AI features.

---

## Goal
Build a working hackathon prototype in under 48 hours that demonstrates:

- Offline operation
- Pitch-black obstacle detection
- Basic autonomous navigation
- Servo-based ultrasonic scanning
- Real-time or near-real-time 2D mapping
- GPS-denied movement estimation
- Modular sensing payload concept scalable to UGVs or drones

---

## Hardware Assumptions

### Main Board
- Arduino UNO Q
- MCU side: STM32U585 running Arduino Core on Zephyr
- Linux side: Qualcomm Dragonwing QRB2210 running Debian Linux

### RC Car Kit Parts
- 4WD / 2WD robot car chassis
- DC motors
- Motor driver board
- Ultrasonic sensor, likely HC-SR04
- SG90 servo motor
- Battery holder / battery pack
- Jumper wires
- USB-C cable
- Optional camera module
- Optional IMU / MPU6050 if included

---

## Critical Electrical Warning

The Arduino UNO Q uses **3.3V logic** on JDIGITAL and JANALOG headers.

Many Arduino starter-kit sensors are designed for classic 5V Arduino Uno boards. Be careful.

### HC-SR04 Ultrasonic Sensor Warning

If using a common HC-SR04:

- VCC may be 5V
- TRIG input can usually accept 3.3V
- ECHO output is often 5V

Do **not** connect ECHO directly to the UNO Q input pin.

Use a voltage divider or level shifter.

Recommended voltage divider:

```text
HC-SR04 ECHO ---- 2kΩ ---- UNO Q ECHO_INPUT_PIN
                       |
                      1kΩ
                       |
                      GND
```

This reduces approximately 5V to approximately 3.3V.

### Power Warning

Do not power motors directly from UNO Q.

Use:

```text
Battery pack -> motor driver -> motors
UNO Q GPIO/PWM -> motor driver control pins
UNO Q GND -> motor driver GND
```

The UNO Q and motor driver must share a common ground.

---

## Recommended Software Architecture

```text
DARKMAP-Q
│
├── arduino/
│   └── darkmap_rover.ino
│
├── linux/
│   ├── main.py
│   ├── mapper.py
│   ├── dashboard.py
│   ├── serial_bridge.py
│   └── requirements.txt
│
├── docs/
│   ├── demo_script.md
│   ├── wiring.md
│   └── pitch.md
│
└── README.md
```

---

## Division of Responsibilities

### MCU / Arduino Sketch
The MCU should handle time-critical hardware control:

- Motor control
- Servo sweep
- Ultrasonic pulse timing
- Basic obstacle avoidance
- Emergency stop
- Sending scan data to Linux side

### Linux / Python App
The Linux side should handle higher-level tasks:

- Read scan packets from MCU
- Convert distance/angle into 2D points
- Estimate rover pose
- Build simple occupancy map
- Display dashboard
- Save logs locally
- Optional camera / edge AI

---

## MVP Behavior

The rover should:

1. Start in idle mode.
2. Sweep ultrasonic sensor left, center, right.
3. If front is clear, move forward slowly.
4. If front is blocked, stop.
5. Scan left and right.
6. Turn toward the direction with more open space.
7. Send sensor data to the Linux app.
8. Linux app plots obstacle points on a 2D map.
9. System works with internet disabled.

---

## Modes

Implement these modes if possible:

### AUTO Mode
Robot autonomously explores while avoiding obstacles.

### MANUAL Mode
Operator controls robot from keyboard or simple commands.

### SCAN_ONLY Mode
Robot stays still and performs a radar-like sweep for demo/debugging.

### STOP Mode
All motors stop immediately.

---

## Arduino Sketch Requirements

Create `arduino/darkmap_rover.ino`.

### Pin Definitions
Use configurable pin constants at the top.

Example placeholder pins:

```cpp
#define LEFT_MOTOR_FWD 5
#define LEFT_MOTOR_REV 6
#define RIGHT_MOTOR_FWD 9
#define RIGHT_MOTOR_REV 10

#define SERVO_PIN 3
#define ULTRASONIC_TRIG 7
#define ULTRASONIC_ECHO 8
```

Important: verify actual UNO Q-compatible pins before final wiring. Avoid D3 if the connected signal may ever output 5V. Servo PWM output is okay, but do not feed 5V into D3.

### Motor Functions
Implement:

```cpp
void moveForward(int speed);
void moveBackward(int speed);
void turnLeft(int speed);
void turnRight(int speed);
void stopCar();
```

### Ultrasonic Function
Implement:

```cpp
long readDistanceCM();
```

Requirements:

- Return distance in centimeters.
- Timeout if no echo is received.
- Clamp unrealistic values.
- Mark invalid readings as `-1`.

### Servo Scan Function
Implement:

```cpp
void scanAndReport();
```

Scan angles:

```text
-75, -45, -20, 0, 20, 45, 75
```

Servo positions assuming 90 degrees is center:

```text
servo_angle = 90 + scan_angle
```

For each scan point, send a serial packet.

### Serial Packet Format
Use simple CSV or JSON-lines.

Recommended CSV:

```text
SCAN,timestamp_ms,angle_deg,distance_cm,mode
```

Example:

```text
SCAN,123456,-45,88,AUTO
```

Also send movement events:

```text
MOVE,timestamp_ms,action,duration_ms,speed
```

Example:

```text
MOVE,123900,FORWARD,300,120
```

### Autonomous Logic
Implement this simple state machine:

```text
LOOP:
  scan front
  if front_distance > 35 cm:
      move forward briefly
  else:
      stop
      scan left and right
      if left_distance > right_distance:
          turn left briefly
      else:
          turn right briefly
```

Use short movement pulses, not continuous movement. This improves mapping and safety.

Suggested values:

```text
forward pulse: 250–400 ms
turn pulse: 200–350 ms
speed: 100–150 PWM
obstacle threshold: 25–35 cm
```

---

## Linux Python App Requirements

Create `linux/main.py`.

### Core Responsibilities

- Read data from MCU serial/Bridge.
- Parse `SCAN` and `MOVE` packets.
- Maintain estimated pose: `x`, `y`, `theta`.
- Convert scan readings into obstacle points.
- Plot/update 2D map.
- Save session logs.

### Data Structures

```python
pose = {
    "x": 0.0,
    "y": 0.0,
    "theta": 0.0,  # radians
}

obstacle_points = []  # list of (x, y)
path_points = []      # list of (x, y)
```

### Coordinate Conversion

For each scan:

```python
world_angle = pose["theta"] + math.radians(scan_angle_deg)
x = pose["x"] + distance_cm * math.cos(world_angle)
y = pose["y"] + distance_cm * math.sin(world_angle)
```

Append `(x, y)` to `obstacle_points`.

### Simple Pose Estimate

Without wheel encoders, use approximate dead reckoning.

When receiving:

```text
MOVE,timestamp,FORWARD,duration_ms,speed
```

Estimate distance:

```python
cm_per_second = SPEED_CALIBRATION_VALUE
distance = cm_per_second * duration_ms / 1000
pose["x"] += distance * cos(theta)
pose["y"] += distance * sin(theta)
```

When receiving:

```text
MOVE,timestamp,TURN_LEFT,duration_ms,speed
```

Estimate heading change:

```python
degrees_per_second = TURN_CALIBRATION_VALUE
pose["theta"] += radians(degrees_per_second * duration_ms / 1000)
```

For right turn, subtract angle.

### Calibration Values

Start with:

```python
SPEED_CM_PER_SEC = 12.0
TURN_DEG_PER_SEC = 90.0
```

Then tune during testing.

---

## Mapping Visualization

Create `linux/mapper.py`.

Use matplotlib for quick implementation.

Requirements:

- Live scatter plot of obstacle points
- Line plot of rover path
- Current rover location marker
- Equal aspect ratio
- Grid enabled
- Save final map to `logs/map.png`

If live plotting is slow, update every 10 scan points instead of every point.

---

## Optional Offline Dashboard

If time allows, create `linux/dashboard.py` using Flask.

Features:

- Local web dashboard served from UNO Q
- Shows map image
- Shows latest scan distance
- Shows mode: AUTO / MANUAL / STOP
- Shows internet-independent status

Run locally:

```bash
python3 dashboard.py
```

Access from laptop over local connection if available, or run directly in SBC mode with display.

Do not depend on cloud APIs.

---

## Optional Edge AI Features

Only add these after MVP works.

### Option 1: Rule-Based Scene Classification
Classify each scan frame as:

- open area
- corridor
- dead end
- wall ahead
- obstacle nearby

This can be done without ML and still presented as onboard edge decision logic.

### Option 2: Camera Object Detection
If camera works and lighting/IR source is available:

- Use OpenCV locally
- Detect simple shapes or ArUco markers
- Tag detected objects on the map

Do not prioritize this before mapping works.

---

## Testing Plan

### Test 1 — Motor Test
Upload a sketch that performs:

```text
forward 1 sec
stop 1 sec
left 0.5 sec
stop 1 sec
right 0.5 sec
stop
```

Pass criteria:

- Motors spin correctly.
- Direction is correct.
- No board reset.

### Test 2 — Ultrasonic Test
Print distance every 200 ms.

Pass criteria:

- Distance changes when object moves.
- Readings are plausible.
- UNO Q input is protected with level shifting/divider.

### Test 3 — Servo Test
Sweep servo from 30 to 150 degrees.

Pass criteria:

- Servo moves smoothly.
- Sensor mount does not shake too much.

### Test 4 — Scan Packet Test
Print scan packets.

Pass criteria:

```text
SCAN,123456,-45,88,AUTO
SCAN,123700,0,120,AUTO
SCAN,123950,45,72,AUTO
```

### Test 5 — Python Parser Test
Run `main.py` and confirm it parses scan packets.

Pass criteria:

- No parsing crash.
- Points are added to the map.

### Test 6 — Autonomous Test
Run the rover in a small box/cardboard maze.

Pass criteria:

- Stops before walls.
- Turns away from obstacles.
- Map updates.

---

## 48-Hour Build Schedule

### Hour 0–4: Setup
- Assemble car chassis.
- Mount UNO Q securely.
- Identify motor driver wiring.
- Confirm power wiring.
- Install/setup Arduino App Lab.
- Run Blink example.

### Hour 4–8: Motor Control
- Write motor functions.
- Test each movement.
- Tune speed.
- Add emergency stop.

### Hour 8–12: Ultrasonic + Servo
- Wire ultrasonic safely with voltage divider.
- Test distance readings.
- Mount ultrasonic on servo.
- Implement scan sweep.

### Hour 12–18: Basic Autonomy
- Implement front obstacle detection.
- Add left/right scan decision.
- Implement pulse-based movement.
- Test in lit room first.

### Hour 18–26: Serial/Bridge Data
- Send scan packets.
- Send movement packets.
- Build Python parser.
- Save logs.

### Hour 26–34: Mapping
- Implement coordinate conversion.
- Plot obstacle points.
- Plot rover path.
- Tune movement calibration.

### Hour 34–40: Demo Environment
- Build dark maze with cardboard/boxes.
- Test in low light/darkness.
- Record success video.
- Improve reliability.

### Hour 40–46: Polish
- Add README.
- Add pitch script.
- Add labels to hardware module.
- Add fallback manual mode if possible.

### Hour 46–48: Final Prep
- Freeze code.
- Charge batteries.
- Prepare demo script.
- Prepare backup video.
- Prepare explanation of limitations and next steps.

---

## README Requirements

Create `README.md` with:

- Project title
- Problem statement
- Solution overview
- Hardware used
- Software architecture
- How to run Arduino code
- How to run Python mapping
- Demo instructions
- Safety/voltage warning
- Known limitations
- Future improvements

---

## Pitch Positioning

Do not pitch this as only an RC car.

Pitch it as:

> A modular offline reconnaissance sensing payload for GPS-denied and low-light environments, demonstrated on an RC rover but scalable to drones and UGVs.

Key phrases:

- Offline-first
- GPS-denied navigation
- Pitch-black reconnaissance
- Edge processing
- Real-time MCU control
- Onboard Linux mapping
- Modular payload
- Scalable to drone or ground robot applications

---

## Known Limitations

Be honest:

- Ultrasonic mapping is rough, not LiDAR-quality.
- Without wheel encoders, position estimate drifts.
- Thin/soft/angled objects may be missed by ultrasonic.
- Camera is not useful in total darkness without IR illumination.
- This is a proof-of-concept, not military-grade autonomy.

Then explain upgrades:

- Add wheel encoders.
- Add 2D LiDAR.
- Add IMU fusion.
- Add IR camera / thermal camera.
- Add mesh communication between multiple rovers.
- Add drone-compatible mounting bracket.

---

## Cursor Task List

Ask Cursor to implement in this order:

1. Create project structure.
2. Write `arduino/darkmap_rover.ino` with motor, servo, ultrasonic, scan packets, obstacle avoidance.
3. Write `linux/serial_bridge.py` to read MCU serial packets.
4. Write `linux/mapper.py` for live 2D map plotting.
5. Write `linux/main.py` to connect parser + pose estimation + map.
6. Write `linux/requirements.txt`.
7. Write `README.md`.
8. Write `docs/demo_script.md`.
9. Add manual keyboard mode if time allows.
10. Add rule-based scene classification if time allows.

---

## Cursor Prompt

Use this prompt in Cursor:

```text
You are helping build DARKMAP-Q, a 48-hour hackathon prototype for an Arduino UNO Q based offline reconnaissance rover. Generate a clean project with an Arduino MCU sketch and Python Linux-side mapping app.

The Arduino sketch must control DC motors, SG90 servo, and HC-SR04 ultrasonic sensor. It must use pulse-based autonomous obstacle avoidance and send CSV packets over serial:
SCAN,timestamp_ms,angle_deg,distance_cm,mode
MOVE,timestamp_ms,action,duration_ms,speed

The Python app must read those packets, estimate rover pose with rough dead reckoning, convert angle+distance readings into 2D obstacle points, live plot the map, plot rover path, and save logs locally.

The system must run offline. Do not use cloud APIs. Keep code simple and robust for hackathon use. Add comments, constants for calibration, and clear setup instructions.
```

---

## Definition of Done

The project is done when:

- Rover moves safely.
- Rover detects obstacles in darkness.
- Rover turns away from obstacles.
- Servo scans multiple angles.
- Scan packets are produced.
- Python app shows a 2D map.
- Demo works offline.
- Team can explain limitations and next steps.

