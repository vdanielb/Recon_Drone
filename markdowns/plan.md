# DARKMAP-Q Handover Plan

## Project Title

**DARKMAP-Q: Offline GPS-Denied Reconnaissance Mapping Module**

## One-Line Pitch

DARKMAP-Q is an offline autonomous reconnaissance rover module that uses an Arduino UNO Q, ultrasonic scanning, real-time motor control, and onboard Linux/Python mapping to explore and generate a rough 2D map of pitch-black GPS-denied environments.

## Track Fit

This project is designed for the **Autonomous Navigation & Edge AI (Hardware+) Track**.

The project aligns with the track because it demonstrates:

- Autonomous navigation using an RC-car platform
- Operation with little to no internet connection
- GPS-denied movement and environment awareness
- A scalable sensing/navigation module that could be adapted to drones or UGVs
- Onboard processing using the Arduino UNO Q Linux + MCU architecture
- Defense-inspired reconnaissance in dark, unknown, or connectivity-limited environments

## Final Demo Goal

By the end of the hackathon, the team should demonstrate a rover that can:

1. Move autonomously inside a small dark test area.
2. Stop before obstacles.
3. Scan left, center, and right using a servo-mounted ultrasonic sensor.
4. Choose a safer direction when blocked.
5. Send scan/movement data to the UNO Q Linux side.
6. Display or save a rough 2D map locally.
7. Run without internet during the demo.

The best judging demo is a small cardboard maze or room with the lights off, where the rover moves slowly and the map appears live or is saved locally.

---

# 1. Hardware Platform

## Main Board

Use the **Arduino UNO Q** as the core controller.

The UNO Q has two useful sides:

### MCU Side

The MCU is responsible for real-time tasks:

- Motor control
- Servo control
- Ultrasonic timing
- Emergency stop logic
- Basic obstacle avoidance

### Linux MPU Side

The Linux processor is responsible for high-level tasks:

- Mapping
- Local dashboard or visualization
- Data logging
- Optional edge AI / camera processing
- Mission state management

## Main Components

Required:

- Arduino UNO Q
- RC car chassis
- Motor driver board
- DC motors
- Battery pack for motors
- Servo motor, such as SG90
- Ultrasonic sensor, such as HC-SR04
- Jumper wires
- Breadboard or prototype board
- USB-C data/power cable
- Laptop for setup and optional monitoring

Optional but helpful:

- MPU6050 IMU for heading correction
- Camera module or USB camera
- IR LEDs or small flashlight if using camera in darkness
- 3D-printed or laser-cut sensor bracket
- Level shifter module
- Additional battery bank for UNO Q

---

# 2. Critical Electrical Notes

## 3.3V Logic Warning

The Arduino UNO Q uses **3.3V logic** on its Arduino-compatible digital and analog headers.

This is different from a classic Arduino Uno, which commonly uses 5V logic.

Important rules:

- Do not feed 5V signals directly into UNO Q analog pins.
- Be careful with sensors that output 5V signals.
- Most beginner ultrasonic sensors, especially HC-SR04, output 5V on the ECHO pin.
- Use a voltage divider or level shifter before connecting HC-SR04 ECHO to the UNO Q.

## Ultrasonic Sensor Echo Protection

Recommended voltage divider:

```text
HC-SR04 ECHO ---- 2kΩ ---- UNO Q input pin
                       |
                      1kΩ
                       |
                      GND
```

This reduces approximately 5V to about 3.3V.

## Motor Power Warning

Do not power the DC motors from the UNO Q directly.

Use this structure:

```text
Motor battery pack ---> motor driver ---> motors
UNO Q GPIO pins -----> motor driver control pins
UNO Q GND -----------> motor driver GND
Motor battery GND ---> motor driver GND
```

All grounds must be common.

If the motor current causes brownouts or resets, separate the motor battery from the UNO Q power source.

## Servo Power Warning

The servo can pull more current than expected.

Preferred:

```text
External 5V supply ---> servo VCC
UNO Q GND -----------> servo GND
UNO Q PWM pin -------> servo signal
```

Do not overload the UNO Q 5V pin if the servo stalls or jitters.

---

# 3. Recommended System Architecture

```text
+---------------------------------------------------+
| Arduino UNO Q                                      |
|                                                   |
|  +-------------------+     Bridge/RPC/Serial      |
|  | STM32 MCU Side    | <------------------------> |
|  | Arduino Sketch    |                            |
|  |                   |                            |
|  | - Motor control   |                            |
|  | - Servo scan      |                            |
|  | - Ultrasonic read |                            |
|  | - Safety stop     |                            |
|  +-------------------+                            |
|                                                   |
|  +-------------------+                            |
|  | Linux MPU Side    |                            |
|  | Python App        |                            |
|  |                   |                            |
|  | - Mapping         |                            |
|  | - Dashboard       |                            |
|  | - Data logging    |                            |
|  | - Optional AI     |                            |
|  +-------------------+                            |
+---------------------------------------------------+
```

## MVP Communication Method

For the fastest hackathon build, use serial-style messages from the MCU side to the Linux/Python side.

Example sensor message:

```text
SCAN,angle=-60,distance=120
SCAN,angle=-30,distance=95
SCAN,angle=0,distance=45
SCAN,angle=30,distance=80
SCAN,angle=60,distance=150
POSE,move=forward,duration_ms=400
TURN,dir=left,duration_ms=300
```

The Python side parses these messages and updates the map.

---

# 4. Software Files to Build

Create this project structure:

```text
darkmap-q/
│
├── README.md
├── handover.md
│
├── arduino/
│   └── darkmap_q_mcu.ino
│
├── linux/
│   ├── main.py
│   ├── mapper.py
│   ├── dashboard.py
│   └── requirements.txt
│
├── docs/
│   ├── wiring.md
│   ├── demo_script.md
│   └── judging_pitch.md
│
└── data/
    └── logs/
```

## File Responsibilities

### `arduino/darkmap_q_mcu.ino`

Runs on the MCU side.

Responsibilities:

- Motor control
- Servo control
- Ultrasonic distance readings
- Obstacle avoidance
- Safety stop
- Send scan and motion data to Linux/Python side

### `linux/main.py`

Runs on the Linux side.

Responsibilities:

- Receive MCU data
- Start mapping loop
- Log incoming data
- Start dashboard or live plot

### `linux/mapper.py`

Responsibilities:

- Convert angle + distance into XY points
- Maintain robot estimated pose
- Maintain occupancy grid or point cloud
- Save map as CSV/PNG

### `linux/dashboard.py`

Responsibilities:

- Display live 2D map
- Show rover status
- Show current mode: idle / scan / move / blocked / manual

### `docs/demo_script.md`

Responsibilities:

- Step-by-step hackathon demo instructions
- What to say to judges
- Backup plan if autonomy fails

---

# 5. MCU Code Plan

## Required MCU Functions

Implement these first:

```cpp
void moveForward(int speed);
void moveBackward(int speed);
void turnLeft(int speed);
void turnRight(int speed);
void stopCar();
long readDistanceCM();
int scanAtAngle(int angle);
void scanSweep();
void autonomousStep();
void sendTelemetry(String message);
```

## Motor Control Logic

Movement is controlled by the left and right wheels.

```text
Forward:  left forward, right forward
Backward: left backward, right backward
Left:     left slow/backward, right forward
Right:    left forward, right slow/backward
Stop:     all motor outputs off
```

Use slow speeds for the demo.

Recommended starting PWM values:

```text
Forward speed: 110-150
Turn speed:    100-140
```

Avoid full speed. Mapping will be worse if the robot moves too quickly.

## Ultrasonic Scan Angles

Use a servo-mounted ultrasonic sensor.

Recommended angles:

```text
30°   = left
60°   = slight left
90°   = center
120°  = slight right
150°  = right
```

Alternative mapping-friendly angle set:

```text
-60°, -30°, 0°, 30°, 60°
```

Internally, convert servo angle to relative robot angle.

Example:

```text
servo 90° = robot 0°
servo 30° = robot -60°
servo 150° = robot +60°
```

## Basic Autonomous Logic

```text
Loop:
1. Scan center.
2. If front distance is clear, move forward slowly for a short time.
3. Stop.
4. Perform scan sweep.
5. If blocked, compare left and right distance.
6. Turn toward the clearer side.
7. Repeat.
```

Recommended threshold:

```text
Obstacle threshold: 25-35 cm
Forward step time: 300-600 ms
Turn step time:    250-500 ms
```

Keep movement step-based, not continuous. Step-based motion makes mapping easier.

## MCU Pseudocode

```cpp
void loop() {
  int front = scanAtAngle(90);

  if (front > OBSTACLE_THRESHOLD_CM) {
    sendTelemetry("STATE,moving_forward");
    moveForward(BASE_SPEED);
    delay(FORWARD_STEP_MS);
    stopCar();
    sendTelemetry("POSE,move=forward,duration_ms=" + String(FORWARD_STEP_MS));
  } else {
    stopCar();
    sendTelemetry("STATE,blocked");

    int left = scanAtAngle(30);
    int right = scanAtAngle(150);

    if (left > right) {
      sendTelemetry("STATE,turn_left");
      turnLeft(TURN_SPEED);
      delay(TURN_STEP_MS);
      stopCar();
      sendTelemetry("TURN,dir=left,duration_ms=" + String(TURN_STEP_MS));
    } else {
      sendTelemetry("STATE,turn_right");
      turnRight(TURN_SPEED);
      delay(TURN_STEP_MS);
      stopCar();
      sendTelemetry("TURN,dir=right,duration_ms=" + String(TURN_STEP_MS));
    }
  }

  scanSweep();
}
```

---

# 6. Linux/Python Mapping Plan

## Mapping Assumption

For the MVP, the rover does not need perfect SLAM.

Use approximate dead reckoning:

```text
Robot pose = x, y, heading
```

When the robot moves forward, update position estimate.

When the robot turns, update heading estimate.

## Basic Pose Variables

```python
x = 0.0
y = 0.0
heading_deg = 0.0
```

## Convert Scan to XY

Each scan message provides:

```text
relative_angle_deg
distance_cm
```

Convert it into map point:

```python
global_angle = heading_deg + relative_angle_deg
point_x = x + distance_cm * cos(global_angle)
point_y = y + distance_cm * sin(global_angle)
```

## Map Types

### MVP Map

Use a simple point cloud:

```text
List of obstacle points: [(x1, y1), (x2, y2), ...]
```

This is easiest and good enough for visual demo.

### Stronger Map

Use an occupancy grid:

```text
0 = unknown
1 = free
2 = obstacle
```

For 48 hours, point cloud is safer.

## Python MVP Features

Required:

- Read telemetry from MCU
- Parse `SCAN`, `POSE`, `TURN`, `STATE` messages
- Update robot pose estimate
- Convert scan readings into XY obstacle points
- Display map using matplotlib or local web dashboard
- Save logs to CSV

Optional:

- Save map image as PNG
- Serve dashboard locally at `localhost`
- Add mission replay from saved log

---

# 7. Edge AI Add-On Options

Only attempt these after the core rover and mapping work.

## Option A: Rule-Based Scene Classification

Classify local environment from ultrasonic scan data:

```text
OPEN_AREA
CORRIDOR
DEAD_END
LEFT_BLOCKED
RIGHT_BLOCKED
NARROW_PASSAGE
```

This is not true ML, but it demonstrates onboard decision intelligence.

## Option B: Camera Detection

If the camera works and lighting/IR support is available:

- Use OpenCV locally on UNO Q Linux
- Detect bright markers, silhouettes, or QR-style mission tags
- Save detections into the map

Do not depend on cloud APIs.

## Option C: Local Risk Tagging

When close obstacles are detected, mark them as risk zones.

```text
Distance < 15 cm = high risk
15-35 cm = medium risk
>35 cm = clear
```

This is easy and useful for the defense-oriented pitch.

---

# 8. 48-Hour Build Schedule

## Hour 0-2: Team Setup

- Confirm hardware parts
- Assign roles
- Create GitHub repository
- Create project folder structure
- Install Arduino App Lab / Arduino tools
- Confirm UNO Q boots
- Run blink example

Roles:

```text
Hardware Lead: wiring, chassis, power, mounting
MCU Lead: Arduino sketch, motors, servo, ultrasonic
Linux Lead: Python mapping and dashboard
Pitch Lead: demo script, slides, judging story
```

## Hour 2-6: Motor Bring-Up

Goal:

- Car can move forward, backward, left, right, and stop.

Tasks:

- Wire motor driver
- Confirm separate motor power
- Confirm common ground
- Test one motor at a time
- Tune PWM speed

Success test:

```text
Robot drives forward for 1 second, stops, turns left, stops, turns right, stops.
```

## Hour 6-10: Ultrasonic + Servo Bring-Up

Goal:

- Sensor scans left/center/right and prints distances.

Tasks:

- Mount ultrasonic sensor on servo
- Add voltage divider or level shifter on ECHO
- Test distance readings
- Test servo scan angles
- Print telemetry messages

Success test:

```text
Move hand/wall in front of sensor.
Serial output changes correctly.
Servo scans 30°, 90°, 150° reliably.
```

## Hour 10-16: Basic Autonomy

Goal:

- Rover avoids walls in a lit room.

Tasks:

- Implement obstacle threshold
- Implement scan-and-turn logic
- Slow down rover
- Add stop before every scan
- Add telemetry messages

Success test:

```text
Rover moves forward, stops before a wall, scans left/right, turns toward open space.
```

## Hour 16-24: Linux Mapping MVP

Goal:

- Python receives scan data and plots obstacle points.

Tasks:

- Create `main.py`
- Parse telemetry messages
- Create `mapper.py`
- Plot points using matplotlib or simple local dashboard
- Save CSV logs

Success test:

```text
When the rover scans a wall, the laptop/UNO Q display shows obstacle points.
```

## Hour 24-32: Integrate Mapping + Movement

Goal:

- Map updates as rover moves.

Tasks:

- Parse movement events
- Update estimated robot pose
- Update heading after turns
- Draw robot path
- Draw obstacle points

Success test:

```text
Map shows robot path and rough wall/obstacle locations.
```

## Hour 32-38: Dark-Room Demo Build

Goal:

- Controlled demo environment works reliably.

Tasks:

- Build cardboard maze or small test arena
- Test in low light / dark room
- Tune obstacle threshold
- Reduce speed
- Add manual override if possible
- Prepare reset procedure

Success test:

```text
Robot can complete a 1-2 minute demo without crashing badly.
```

## Hour 38-44: Polish

Goal:

- Make the system look intentional and professional.

Tasks:

- Clean wiring
- Tape or mount loose parts
- Label module sections
- Add project name label: DARKMAP-Q
- Save demo logs
- Create backup video
- Prepare short pitch

## Hour 44-48: Final Rehearsal

Goal:

- Repeatable judging demo.

Tasks:

- Run complete demo 5 times
- Prepare fallback mode
- Prepare answers to expected judge questions
- Save one successful map screenshot
- Charge all batteries

---

# 9. Demo Script

## Demo Setup

Use a small cardboard or foam-board maze:

```text
Size: 1.5m x 1.5m to 2m x 2m
Walls: cardboard boxes or foam boards
Lighting: dim or fully dark
Speed: slow
Duration: 60-120 seconds
```

## Judge Demo Flow

1. Show the rover and sensing module.
2. Explain that the system runs offline.
3. Explain that the RC car is a test platform for a scalable navigation payload.
4. Turn off internet or mention no cloud is used.
5. Start the rover.
6. Rover scans, moves, avoids obstacle.
7. Show 2D map/log generated locally.
8. Explain how this could scale to UGV/drone use.

## 30-Second Spoken Pitch

DARKMAP-Q is an offline reconnaissance mapping module for GPS-denied and low-visibility environments. The Arduino UNO Q gives us a dual architecture: the microcontroller handles real-time movement, ultrasonic scanning, and safety, while the Linux processor handles mapping and local intelligence. Our RC car is the test platform, but the sensing and navigation module is designed to scale to drones or ground robots. It can operate without internet, build a rough 2D map in darkness, and support future edge AI features like object detection and risk-zone classification.

---

# 10. Fallback Plans

## If Full Autonomy Fails

Use semi-autonomous mode:

- Human controls movement manually.
- Rover still scans automatically.
- Map still updates locally.

Pitch it as:

```text
Operator-supervised reconnaissance mode with autonomous sensing and mapping.
```

## If Mapping Fails

Show:

- Serial scan data
- Saved sample map from previous run
- Obstacle avoidance live demo

Pitch it as:

```text
Mapping pipeline is logging data locally; visualization is in prototype stage.
```

## If Ultrasonic Is Noisy

Reduce complexity:

- Scan only left, center, right
- Increase delay after servo movement
- Ignore distances above 250 cm
- Ignore distances below 3 cm
- Use median of 3 readings

## If Servo Jitters

- Use external 5V power for servo
- Confirm common ground
- Reduce scan frequency
- Stop motors while scanning

## If UNO Q Resets

- Separate motor power from board power
- Use battery bank/USB-C power for UNO Q
- Confirm common ground
- Avoid powering motors from UNO Q

---

# 11. Judging Strengths

Emphasize these points:

1. **Offline-first:** No cloud dependency during operation.
2. **GPS-denied:** Designed for indoor or blocked-signal environments.
3. **Pitch-black operation:** Ultrasonic sensing does not need visible light.
4. **Dual-compute architecture:** MCU for real-time control, Linux for mapping and intelligence.
5. **Scalable module:** The RC car is only the test platform; the module can be adapted to UGVs or drones.
6. **Defense relevance:** Useful for reconnaissance before humans enter unknown dark spaces.
7. **Practical constraints:** Low-cost, modular, fast to deploy.

---

# 12. What Not to Overclaim

Do not claim:

- Military-grade SLAM
- Accurate LiDAR-quality mapping
- Perfect localization
- Fully reliable battlefield readiness
- Real target detection unless implemented
- True swarm coordination unless demonstrated

Say instead:

```text
This is a proof-of-concept for a low-cost offline reconnaissance mapping payload.
```

---

# 13. Known Limitations

## Localization Drift

Without wheel encoders, visual odometry, or LiDAR, robot position will drift.

Mitigation:

- Use short demo runs
- Move slowly
- Step-based movement
- Use IMU heading correction if available

## Ultrasonic Resolution

Ultrasonic sensing is lower resolution than LiDAR.

Mitigation:

- Use it for rough obstacle/wall mapping
- Keep environment simple
- Use large cardboard walls

## Pitch-Black Camera Limitation

A normal camera does not help in total darkness unless IR lighting or low-light support is added.

Mitigation:

- Make ultrasonic the main dark-environment sensor
- Treat camera/AI as optional enhancement

---

# 14. Recommended Pin Planning

Exact pins may need adjustment depending on the motor driver and UNO Q carrier layout.

Suggested starting plan:

```text
Motor Driver:
Left motor IN1  -> D5 PWM
Left motor IN2  -> D6 PWM
Right motor IN3 -> D9 PWM
Right motor IN4 -> D10 PWM

Ultrasonic:
TRIG -> D2
ECHO -> D4 through voltage divider / level shifter

Servo:
Signal -> D11 PWM
VCC    -> external 5V preferred
GND    -> common GND
```

Avoid using D3 for 5V input signals because it is not 5V tolerant.

---

# 15. Acceptance Checklist

## Hardware Checklist

- [ ] UNO Q powers reliably
- [ ] Motor driver wired correctly
- [ ] Motors move in correct direction
- [ ] Servo scans smoothly
- [ ] Ultrasonic sensor returns stable distances
- [ ] ECHO pin protected with voltage divider or level shifter
- [ ] Motor power and UNO Q power are stable
- [ ] Grounds are common
- [ ] Wires secured
- [ ] Sensor mounted firmly

## MCU Checklist

- [ ] `moveForward()` works
- [ ] `turnLeft()` works
- [ ] `turnRight()` works
- [ ] `stopCar()` works
- [ ] `readDistanceCM()` works
- [ ] `scanSweep()` works
- [ ] Obstacle threshold works
- [ ] Telemetry messages print correctly

## Linux/Python Checklist

- [ ] Python app starts
- [ ] Receives MCU data
- [ ] Parses scan messages
- [ ] Converts angle/distance to XY
- [ ] Displays obstacle points
- [ ] Saves data log
- [ ] Can run offline

## Demo Checklist

- [ ] Dark maze ready
- [ ] Batteries charged
- [ ] Backup USB-C cable ready
- [ ] Backup demo video ready
- [ ] Saved map screenshot ready
- [ ] 30-second pitch memorized
- [ ] Fallback manual mode ready

---

# 16. Cursor Implementation Prompt

Use this prompt in Cursor to generate the starter code:

```text
We are building DARKMAP-Q, an offline GPS-denied reconnaissance rover using Arduino UNO Q. The UNO Q has an MCU side for real-time Arduino code and a Linux side for Python mapping. Generate a project with:

1. arduino/darkmap_q_mcu.ino
   - Motor control functions: moveForward, moveBackward, turnLeft, turnRight, stopCar
   - Servo-mounted ultrasonic scanning
   - HC-SR04 distance reading
   - Basic autonomous obstacle avoidance
   - Telemetry output in CSV-like lines:
     SCAN,angle=<deg>,distance=<cm>
     POSE,move=forward,duration_ms=<ms>
     TURN,dir=left|right,duration_ms=<ms>
     STATE,<state>
   - Use configurable pin constants at the top.
   - Include comments warning that UNO Q is 3.3V logic and HC-SR04 ECHO needs a voltage divider or level shifter.

2. linux/main.py
   - Read telemetry from serial or stdin for testing.
   - Parse SCAN, POSE, TURN, and STATE lines.
   - Feed data into mapper.py.
   - Show live map using matplotlib.
   - Save log to data/logs/session.csv.

3. linux/mapper.py
   - Maintain robot pose x, y, heading_deg.
   - Convert distance and relative angle into obstacle XY points.
   - Update pose for forward movement and turns.
   - Store path and obstacle points.

4. linux/dashboard.py
   - Provide simple live plotting function.
   - Draw obstacle points and robot path.

5. README.md
   - Explain setup, wiring, safety warnings, and how to run.

Keep the code simple, hackathon-friendly, and offline-first. Do not use cloud APIs.
```

---

# 17. Final Recommended Strategy

Build the project in this priority order:

1. Make the car move reliably.
2. Make the ultrasonic sensor read safely with 3.3V protection.
3. Mount sensor on servo and scan.
4. Add obstacle avoidance.
5. Send telemetry.
6. Plot rough map locally.
7. Polish the demo and pitch.

The winning version is not the most complicated version. The winning version is the one that works reliably, runs offline, clearly maps a dark space, and tells a strong defense-relevant story.
