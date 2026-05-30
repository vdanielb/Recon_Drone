# DARKMAP Handover Plan

## Project Title
**DARKMAP: Offline Reconnaissance Mapping Module for GPS-Denied Dark Environments**

## One-Line Pitch
A low-cost autonomous ground rover that can operate without internet, GPS, or visible light by using ultrasonic scanning to detect obstacles and generate a rough 2D map of a dark indoor area.

## Track Fit
This project is designed for the **Autonomous Navigation & Edge AI (Hardware+) Track**. The RC car is used as the prototype platform, but the main deliverable is a modular sensing and navigation payload that could scale to ground robots, drones, or other autonomous defense-oriented systems.

Core alignment:
- Offline operation with little to no internet
- GPS-denied navigation concept
- Autonomous navigation on an RC-car platform
- Dark-environment reconnaissance
- Modular sensing attachment concept
- Edge decision-making using onboard sensor data

## Project Goal
Build a working hackathon prototype in under 48 hours that can:
1. Move autonomously or semi-autonomously.
2. Detect obstacles in pitch-black conditions.
3. Scan left, center, and right using a servo-mounted ultrasonic sensor.
4. Avoid obstacles using onboard decision logic.
5. Send distance and movement data to a laptop over USB serial.
6. Display a rough 2D map of detected walls/obstacles.
7. Demonstrate that the system does not require internet, GPS, or visible light.

## Important Scope Boundary
This prototype is a **non-weaponized reconnaissance and navigation demo**. It is intended for safe, controlled indoor testing only. It should not include weapon payloads, target engagement, harmful automation, or unsafe deployment behavior.

---

# 1. System Overview

## Hardware Platform
Use the provided RC car / Elegoo robot car kit as the base.

Main components:
- Arduino Uno / Elegoo Uno R3
- RC robot car chassis
- DC motors
- Motor driver board
- Ultrasonic sensor, likely HC-SR04
- SG90 servo motor
- Battery pack
- USB cable
- Laptop for code upload and map visualization
- Optional: MPU6050 gyro/accelerometer if available
- Optional: IR remote/manual override
- Optional: LEDs for status indication

## Recommended Architecture

```text
[Ultrasonic Sensor]
        |
      [Servo]
        |
[Arduino / Elegoo Board]
        |
[Motor Driver] ---> [Left Motor + Right Motor]
        |
[USB Serial]
        |
[Laptop Python Map Viewer]
```

## Concept
The ultrasonic sensor detects distance without needing light. Mounting it on a servo allows the rover to scan multiple directions. The Arduino uses this data to avoid obstacles. The laptop receives sensor readings and approximates a 2D map.

---

# 2. Winning Strategy

Do not present the project as only an RC car. Present it as:

> A modular offline reconnaissance mapping payload for GPS-denied and dark environments, tested on an RC rover platform.

Judges should understand that the RC car is only the prototype body. The real innovation is the navigation and sensing module.

## Key Demo Message
In defense, rescue, or disaster environments, a robot may need to enter a building or tunnel where:
- GPS is unavailable.
- Internet connection is unreliable or unavailable.
- Lighting is poor or absent.
- Humans should not enter first.

DARKMAP provides a low-cost way to scan, navigate, and build a rough map offline.

---

# 3. MVP Features

## Must-Have Features
These are required for a successful demo.

### A. Manual Movement Test
The rover must be able to:
- Move forward
- Move backward
- Turn left
- Turn right
- Stop

### B. Ultrasonic Reading
The sensor must measure front distance and print it to Serial Monitor.

### C. Servo Scan
The servo must rotate the ultrasonic sensor to scan:
- Left
- Center
- Right

Recommended scan angles:
```text
30 degrees   = left
90 degrees   = center
150 degrees  = right
```

### D. Obstacle Avoidance
Basic rule:
```text
If front distance < 25 cm:
    Stop
    Scan left and right
    Turn toward the side with more free space
Else:
    Move forward slowly
```

### E. Offline Map Visualization
Arduino sends scan data to the laptop through USB serial. Python plots detected obstacle points in a 2D view.

Example serial output:
```text
SCAN,angle=-60,distance=80
SCAN,angle=-30,distance=95
SCAN,angle=0,distance=120
MOVE,forward,500
TURN,left,400
```

### F. No-Internet Demo
Show that the system works without Wi-Fi or cloud access.

---

# 4. Nice-to-Have Features

Add these only after the MVP works.

## A. Manual Override
Use IR remote, keyboard serial commands, or joystick to control the rover if autonomy fails.

## B. Status LEDs
Use LEDs to show mode:
- Green: moving safely
- Yellow: scanning
- Red: obstacle detected

## C. Risk Zone Marking
When an object is very close, mark it as a risk point on the map.

Example:
```text
Distance < 15 cm = high-risk obstacle
```

## D. IMU Heading Correction
If MPU6050 is available, use the gyro to improve turn-angle estimation.

## E. Modular Mount
Use 3D printing, acrylic, cardboard, or zip ties to make the ultrasonic + servo unit look like a removable payload.

---

# 5. What Not to Build First

Avoid these until the main demo works:
- Full SLAM
- Complex AI model training
- Multi-robot swarm behavior
- Camera-based mapping in pitch black
- Fully accurate room reconstruction
- Mobile app interface
- Internet/cloud dashboard
- Drone flight hardware

These are high-risk and can consume too much time.

---

# 6. 48-Hour Build Schedule

## Hour 0-2: Team Setup
Assign roles:

| Role | Responsibility |
|---|---|
| Hardware Lead | Build chassis, mount servo/sensor, wiring |
| Arduino Lead | Motor control, ultrasonic, servo scanning |
| Mapping Lead | Python serial reader and map visualization |
| Demo/Pitch Lead | Story, slides, judging script, final demo setup |

Deliverable:
- Everyone understands the system architecture.
- Parts are checked.
- Pins and wiring plan are agreed.

---

## Hour 2-6: Chassis + Motor Control
Build the robot car and verify motor movement.

Tasks:
1. Assemble chassis.
2. Connect motors to motor driver.
3. Connect motor driver to Arduino.
4. Upload basic motor test code.
5. Tune motor speed.

Target result:
```text
Car can move forward, backward, left, right, and stop.
```

Recommended speed:
```text
PWM 100-150
```

Keep it slow for mapping.

---

## Hour 6-10: Ultrasonic Sensor Test
Connect ultrasonic sensor and test distance readings.

Tasks:
1. Wire VCC, GND, TRIG, ECHO.
2. Print distance to Serial Monitor.
3. Test against wall at 10 cm, 30 cm, 50 cm, 100 cm.
4. Filter bad readings.

Target result:
```text
Reliable distance reading between roughly 5 cm and 200 cm.
```

Basic filtering:
- Ignore 0 cm.
- Ignore readings above 300 cm.
- Average 3 readings.

---

## Hour 10-14: Servo Scanner
Mount the ultrasonic sensor on the servo.

Tasks:
1. Attach ultrasonic sensor to servo.
2. Mount servo at the front of the rover.
3. Program scan angles.
4. Print angle + distance.

Target result:
```text
The sensor scans left, center, and right and prints readings.
```

Example scan pattern:
```text
30 -> 60 -> 90 -> 120 -> 150 -> 120 -> 90 -> 60 -> 30
```

---

## Hour 14-20: Obstacle Avoidance
Implement basic autonomous movement.

Rules:
```text
If front is clear:
    Move forward slowly
If front is blocked:
    Stop
    Scan left and right
    Turn toward the larger distance
If both sides blocked:
    Reverse briefly and turn
```

Target result:
```text
The rover can avoid walls in a small test area.
```

Demo environment:
- Cardboard walls
- Boxes
- 1.5 m x 1.5 m to 2 m x 2 m test area

---

## Hour 20-28: Serial Protocol + Laptop Mapping
Create a simple serial output from Arduino and Python visualization on laptop.

Arduino should output structured lines:
```text
SCAN,angle=90,distance=78
POSE,move=forward,duration=300
TURN,direction=left,duration=250
```

Python should:
1. Read serial lines.
2. Estimate robot x, y, heading.
3. Convert scan angle + distance into obstacle points.
4. Plot points live.

Approximate mapping formula:
```text
obstacle_x = robot_x + distance * cos(robot_heading + sensor_angle)
obstacle_y = robot_y + distance * sin(robot_heading + sensor_angle)
```

This map does not need to be perfect. It just needs to show the concept.

---

## Hour 28-34: Dark-Room Demo Setup
Create a controlled dark environment.

Recommended setup:
- Small cardboard maze
- Black cloth or dark room
- Obstacles/walls with hard surfaces
- Laptop outside showing map

Avoid soft fabric walls because ultrasonic sensors may give poor reflections.

Target result:
```text
Rover can scan and avoid obstacles while lights are off.
```

---

## Hour 34-40: Stabilization and Polish
Focus on reliability.

Tasks:
1. Secure loose wires.
2. Tape or screw down sensor mount.
3. Label the module.
4. Add LEDs for status if time allows.
5. Tune movement durations.
6. Reduce speed.
7. Make demo repeatable.

Do at least 5 full demo runs.

---

## Hour 40-46: Pitch + Final Demo Script
Prepare the judging story.

Demo script:
1. “This is DARKMAP, an offline reconnaissance mapping module.”
2. “It is designed for GPS-denied, dark, low-connectivity environments.”
3. “The RC car is our test platform; the module can scale to drones or UGVs.”
4. “It uses ultrasonic scanning, so it does not need visible light.”
5. “All navigation decisions run locally on the Arduino.”
6. “Mapping runs locally on the laptop over USB serial.”
7. “No cloud API, no internet, no GPS.”
8. Run the dark-room demo.
9. Show the map forming live.
10. Explain limitations and next steps.

---

## Hour 46-48: Final Check
Checklist:
- Batteries charged
- USB cable ready
- Arduino code uploaded
- Python script tested
- Spare wires available
- Tape/zip ties ready
- Demo area ready
- Team roles clear
- Backup manual-control mode ready
- Short pitch practiced

---

# 7. Wiring Plan Template

Fill this in during the build.

## Motor Driver
| Function | Arduino Pin | Notes |
|---|---:|---|
| Left motor forward | TBD | PWM preferred |
| Left motor backward | TBD | PWM preferred |
| Right motor forward | TBD | PWM preferred |
| Right motor backward | TBD | PWM preferred |

## Ultrasonic Sensor
| HC-SR04 Pin | Arduino Pin | Notes |
|---|---:|---|
| VCC | 5V |  |
| GND | GND |  |
| TRIG | TBD | Digital output |
| ECHO | TBD | Digital input |

## Servo
| Servo Wire | Arduino Pin | Notes |
|---|---:|---|
| Signal | TBD | PWM pin |
| VCC | 5V or external 5V | Use stable power |
| GND | GND | Common ground required |

## Optional LEDs
| LED | Arduino Pin | Meaning |
|---|---:|---|
| Green | TBD | Moving / safe |
| Yellow | TBD | Scanning |
| Red | TBD | Obstacle / risk |

---

# 8. Arduino Logic Plan

## Main Loop Pseudocode

```cpp
loop() {
    frontDistance = scanCenter();

    sendScanToLaptop(90, frontDistance);

    if (frontDistance > SAFE_DISTANCE) {
        moveForwardSlowly();
        sendMovementToLaptop("forward", duration);
    } else {
        stopCar();

        leftDistance = scanLeft();
        sendScanToLaptop(30, leftDistance);

        rightDistance = scanRight();
        sendScanToLaptop(150, rightDistance);

        if (leftDistance > rightDistance && leftDistance > SAFE_DISTANCE) {
            turnLeft();
            sendTurnToLaptop("left", duration);
        } else if (rightDistance > SAFE_DISTANCE) {
            turnRight();
            sendTurnToLaptop("right", duration);
        } else {
            reverseShort();
            turnRight();
            sendMovementToLaptop("reverse", duration);
            sendTurnToLaptop("right", duration);
        }
    }
}
```

## Recommended Constants

```cpp
SAFE_DISTANCE = 25 cm
DANGER_DISTANCE = 15 cm
FORWARD_SPEED = 110 to 150 PWM
TURN_SPEED = 100 to 130 PWM
FORWARD_STEP_TIME = 250 to 500 ms
TURN_TIME = 250 to 500 ms
```

---

# 9. Python Mapping Plan

## Input
Read from Arduino serial:
```text
SCAN,angle=90,distance=78
MOVE,forward,300
TURN,left,250
```

## Pose Estimate
Maintain approximate robot state:
```text
x position
y position
heading angle
```

## Movement Update
When receiving `MOVE,forward,300`:
```text
x += step_distance * cos(heading)
y += step_distance * sin(heading)
```

When receiving `TURN,left,250`:
```text
heading += estimated_turn_angle
```

## Obstacle Point Update
When receiving scan data:
```text
world_angle = heading + sensor_angle
obstacle_x = x + distance * cos(world_angle)
obstacle_y = y + distance * sin(world_angle)
```

Plot obstacle points on a 2D graph.

## Map Quality Note
This is a rough occupancy map, not precision SLAM. It is acceptable for a hackathon prototype if explained clearly.

---

# 10. Demo Setup

## Physical Demo Area
Recommended:
```text
2 m x 2 m cardboard maze
Hard walls/boxes
Dark room or covered area
Laptop beside the maze
```

## Demo Flow
1. Show the rover and modular sensor payload.
2. Explain no internet/GPS/visible light requirement.
3. Turn off lights or cover test area.
4. Start autonomous mode.
5. Rover scans and moves.
6. Laptop shows points appearing on 2D map.
7. Show manual override if needed.
8. Explain scaling to drones/UGVs.

## Backup Demo
If autonomy fails:
- Use manual driving.
- Keep sensor scanning and mapping active.
- Pitch it as semi-autonomous reconnaissance mode.

This is still acceptable and may be more reliable.

---

# 11. Risk Register

| Risk | Impact | Mitigation |
|---|---|---|
| Motor wiring reversed | Car moves incorrectly | Test each motor separately |
| Servo draws too much current | Arduino resets | Use stable battery/external 5V if needed |
| Ultrasonic noisy readings | Poor navigation | Average 3 readings; ignore invalid values |
| Robot moves too fast | Bad mapping | Lower PWM speed |
| Map drifts over time | Inaccurate map | Keep demo area small; explain limitation |
| Loose wires | Random failure | Tape/zip-tie all wires |
| Dark demo hard to see | Judges miss movement | Use laptop map and status LEDs |
| Python serial port issue | No map | Prepare Serial Monitor fallback |
| Battery low | Motors weak | Charge batteries; bring spares |

---

# 12. Limitations to State Honestly

Be transparent with judges:
- Ultrasonic mapping is lower resolution than LiDAR.
- Without wheel encoders, movement tracking drifts over time.
- The map is approximate and best for small areas.
- Thin, angled, or soft objects may be missed by ultrasonic sensors.
- This is a prototype module, not a production defense system.

Then explain next steps:
- Add wheel encoders.
- Add 2D LiDAR.
- Add thermal or IR camera.
- Add onboard compute such as Raspberry Pi / Jetson Nano.
- Add multi-robot offline coordination.
- Add stronger localization and SLAM.

---

# 13. Suggested Pitch

## 30-Second Pitch
DARKMAP is an offline reconnaissance mapping module designed for dark, GPS-denied, and low-connectivity environments. Instead of relying on cameras, cloud systems, or GPS, it uses local ultrasonic scanning and onboard decision logic to detect obstacles and build a rough 2D map. We tested the module on an RC rover platform, but the same sensing package could scale to drones, UGVs, warehouse robots, or disaster-response robots. The system runs locally, requires no internet, and is designed for safe reconnaissance before humans enter unknown spaces.

## 2-Minute Pitch Structure
1. Problem: Dark/GPS-denied environments are dangerous and hard to scout.
2. Solution: Offline sensor module for local navigation and mapping.
3. Prototype: RC rover with servo-mounted ultrasonic scanner.
4. Demo: Rover scans, avoids obstacles, and builds rough 2D map.
5. Differentiator: No internet, no GPS, no visible light required.
6. Scalability: Can be mounted on drones or UGVs.
7. Future: LiDAR, wheel encoders, thermal camera, onboard AI.

---

# 14. Judging Keywords to Use

Use these words intentionally during the pitch:
- Offline autonomy
- GPS-denied navigation
- Dark-environment reconnaissance
- Modular sensing payload
- Edge decision-making
- Local processing
- No cloud dependency
- Low-cost scalable prototype
- UGV/drone-compatible attachment
- Situational awareness
- Rough occupancy mapping
- Human-risk reduction

---

# 15. Final Deliverables

By the end of the hackathon, aim to submit:
1. Working RC rover prototype.
2. Servo-mounted ultrasonic scanner.
3. Arduino autonomous navigation code.
4. Laptop-based 2D map visualization.
5. Dark-room demo area.
6. Short presentation deck or demo script.
7. Clear explanation of limitations and next-generation improvements.

---

# 16. Minimum Success Definition

The project is considered successful if:
- The rover moves.
- The ultrasonic sensor detects walls in darkness.
- The servo scans multiple directions.
- The rover avoids at least one obstacle autonomously.
- The laptop shows a basic 2D map or obstacle plot.
- The team clearly explains the offline GPS-denied reconnaissance use case.

---

# 17. Best Final Positioning

Do not say:
> We built an RC car.

Say:
> We built a low-cost, offline reconnaissance mapping module and validated it on an RC rover platform.

Do not say:
> It makes a perfect map.

Say:
> It produces a rough real-time occupancy map suitable for first-pass reconnaissance in dark GPS-denied spaces.

Do not say:
> It is a defense drone.

Say:
> It is a non-weaponized sensing and navigation payload that could scale to drones or ground robots.

---

# 18. Immediate Next Action

Start with motor control. Nothing else matters until the rover can reliably move and stop.

Recommended build order:
1. Motor control
2. Ultrasonic distance reading
3. Servo scanning
4. Obstacle avoidance
5. Serial output
6. Python map viewer
7. Demo polish

