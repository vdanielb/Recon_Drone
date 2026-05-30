# Arduino UNO Q Specifications

## Overview

The **Arduino UNO Q** is a hybrid single-board computer and microcontroller development board. It combines a Linux-capable application processor with a real-time microcontroller, allowing one board to run high-level software, Python applications, AI/ML workloads, and low-level motor/sensor control.

For the DARKMAP / autonomous reconnaissance rover project, this board is stronger than a normal Arduino Uno because it can handle both:

- **Real-time robotics control** through the STM32 microcontroller
- **On-board mapping, logging, dashboard, and AI/vision tasks** through the Linux processor

---

## Board Variants

| Variant | RAM | On-board Storage |
|---|---:|---:|
| ABX00162 | 2 GB LPDDR4X | 16 GB eMMC |
| ABX00173 | 4 GB LPDDR4X | 32 GB eMMC |

---

## Processing Architecture

The UNO Q has two main processing subsystems.

### 1. Main Linux Application Processor (MPU)

| Item | Specification |
|---|---|
| Processor | Qualcomm Dragonwing QRB2210 SoC |
| CPU | 4 × Arm Cortex-A53 |
| Clock Speed | Up to 2.0 GHz |
| Architecture | 64-bit |
| Operating System | Debian Linux |
| GPU | Adreno 702 |
| GPU Clock | 845 MHz |
| Camera/Display Support | MIPI-CSI-2 camera, MIPI-DSI display |
| USB | USB 3.1 with role-switching over USB-C |

### 2. Real-Time Microcontroller (MCU)

| Item | Specification |
|---|---|
| Microcontroller | STMicroelectronics STM32U585 |
| Core | Arm Cortex-M33 |
| Clock Speed | Up to 160 MHz |
| Runtime | Arduino Core on Zephyr OS |
| Flash | 2 MB |
| SRAM | 786 kB |
| Main Role | Real-time I/O, PWM, ADC, motor control, sensor timing |

---

## Memory and Storage

| Component | Specification |
|---|---|
| RAM | 2 GB or 4 GB LPDDR4X, depending on variant |
| Storage | 16 GB or 32 GB eMMC, depending on variant |
| MCU Flash | 2 MB |
| MCU SRAM | 786 kB |

---

## Connectivity

| Feature | Specification |
|---|---|
| Wi-Fi | Wi-Fi 5, 802.11a/b/g/n/ac, dual-band |
| Bluetooth | Bluetooth 5.1 |
| USB-C | USB 3.1 with role-switching |
| Display Output | USB-C DisplayPort Alt-Mode |
| Recommended Display Resolution | 1280 × 720 |
| Maximum Supported Display | Full HD 1920 × 1080p |

---

## Power Specifications

| Input Method | Voltage | Maximum Current / Notes |
|---|---:|---|
| USB-C VBUS | 5 V | Up to 3 A |
| VIN / DC IN | 7–24 V | Via JMEDIA or JANALOG VIN |
| 5V Pin | 5 V | Up to 3 A via JANALOG |

### Recommended Operating Conditions

| Parameter | Minimum | Typical | Maximum |
|---|---:|---:|---:|
| USB-C input | 4.5 V | 5.0 V | 5.5 V |
| DC input | 7.0 V | — | 24.0 V |
| 3.3 V system rail | 3.1 V | 3.3 V | 3.5 V |
| Operating temperature | -10°C | — | 60°C |

### Important Power Notes for Robotics

- Use a **5 V / 3 A USB-C power source** for stable board operation.
- Do **not** power drive motors directly from the UNO Q.
- Use a separate motor battery or battery pack through the motor driver.
- Connect **common ground** between the UNO Q and motor driver.
- Motor current spikes can cause board resets if the board and motors share an undersized power source.

---

## I/O Voltage and Header Notes

The UNO Q is primarily a **3.3 V logic board**, not a traditional 5 V Arduino Uno board.

| Header | Voltage / Function |
|---|---|
| JDIGITAL | 3.3 V digital I/O; supports SPI, I²C, UART, PWM, CAN |
| JANALOG | 3.3 V analog I/O; ADC inputs |
| Qwiic | 3.3 V I²C |
| JSPI | 3.3 V SPI with 5 V power pin |
| JMEDIA | 1.8 V MIPI camera/display signals, not general-purpose I/O |
| JMISC | Mixed 1.8 V MPU and 3.3 V MCU signals |
| JCTL | 1.8 V control / console signals |

### Critical Voltage Warning

- Digital and analog headers use **3.3 V logic**.
- Analog inputs are **not 5 V tolerant**.
- A0 and A1 must stay within approximately **0–3.3 V**.
- D3 is specifically **not 5 V tolerant**.
- Some digital pins may tolerate 5 V as inputs, but it is safer to treat the board as **3.3 V only** unless confirmed.

### For HC-SR04 Ultrasonic Sensor

Many HC-SR04 ultrasonic sensors output a **5 V Echo signal**, which can damage 3.3 V inputs.

Use one of these:

1. A voltage divider on the Echo pin
2. A logic level shifter
3. A 3.3 V-compatible ultrasonic sensor

Suggested quick divider:

```text
HC-SR04 Echo → 2kΩ resistor → UNO Q input pin
                         |
                       1kΩ resistor
                         |
                        GND
```

This reduces a 5 V Echo signal to about 3.3 V.

---

## Hardware Acceleration

| Feature | Specification |
|---|---|
| GPU | Adreno 702 |
| GPU Clock | 845 MHz |
| OpenGL / OpenGL ES | Supported through Mesa drivers |
| Vulkan | Supported through Turnip driver implementation |
| OpenCL | OpenCL 2.0 through Mesa |
| Video Encoding | H.264, H.265 |
| Video Decoding | H.264, H.265, VP9 |
| Video API | V4L2 devices `/dev/video0` and `/dev/video1` |
| GStreamer Support | Yes |

This is useful for:

- Edge AI experiments
- Computer vision
- On-board video processing
- Local dashboard rendering
- Offline map visualization

---

## Camera and Display Support

| Feature | Specification |
|---|---|
| Camera Interface | 4-lane MIPI-CSI-2 |
| Display Interface | 4-lane MIPI-DSI converted to DisplayPort Alt-Mode on USB-C |
| Camera Control | 1.8 V CCI I²C, dedicated camera-control bus |
| Display Output | USB-C DisplayPort Alt-Mode |

Important: MIPI CSI/DSI pins are **not general-purpose I/O**.

---

## Arduino App Lab and Software Model

The UNO Q is designed to use **Arduino App Lab**, where one project can include:

- A **Python program** running on the Linux processor
- An **Arduino sketch** running on the STM32 microcontroller
- Optional **Bricks**, such as AI models, web servers, APIs, or prebuilt services

The Linux side and MCU side communicate using **Arduino Bridge**, an RPC-based communication layer.

### Suggested Software Split for DARKMAP-Q

| Component | Runs On | Responsibility |
|---|---|---|
| Motor control | MCU | PWM, direction, stop, turn |
| Servo scanning | MCU | Sweep ultrasonic sensor |
| Ultrasonic timing | MCU | Accurate pulse timing |
| Obstacle avoidance | MCU | Immediate safety behavior |
| Mapping | Linux MPU | Convert scan data to 2D map |
| Dashboard | Linux MPU | Local UI or web interface |
| Data logging | Linux MPU | Save scans and paths locally |
| Edge AI / vision | Linux MPU | Optional object detection or scene classification |

---

## Why UNO Q Is Good for the Reconnaissance Rover Project

The UNO Q fits the project well because the hackathon track emphasizes:

- Offline operation
- Edge AI
- Autonomous navigation
- GPS-denied movement
- Drone or robotics attachments
- Defense-oriented sensing modules

The UNO Q supports this because it combines real-time control and Linux computing on one board.

### Strong Project Positioning

> DARKMAP-Q is an offline GPS-denied reconnaissance mapping module. The MCU handles real-time vehicle control and ultrasonic scanning, while the Linux MPU performs local mapping, logging, visualization, and optional edge AI.

---

## Practical Feasibility for 48-Hour Hackathon

### Highly Feasible

- Motor control
- Ultrasonic scanning
- Servo sweep
- Obstacle avoidance
- Offline local mapping
- Local data logging
- Basic dashboard

### Feasible if Time Allows

- On-board web UI
- Camera streaming
- Simple object detection
- IMU heading correction
- Manual override mode
- Map export as image or CSV

### Risky in 48 Hours

- Full SLAM
- Accurate odometry without wheel encoders
- Swarm coordination
- Reliable vision in pitch-black conditions without IR lighting
- Drone-grade localization

---

## Recommended Minimum Build

### Hardware

- Arduino UNO Q
- RC car chassis
- Motor driver
- DC motors
- Servo motor
- Ultrasonic sensor with voltage protection on Echo
- Battery pack for motors
- 5 V / 3 A USB-C supply or stable board power source
- Common ground between board and motor driver

### Software

- Arduino sketch for motor, servo, and ultrasonic control
- Python app on Linux side for mapping and dashboard
- Bridge or serial-style communication between MCU and Linux
- Offline mode with no cloud dependency

---

## Final Assessment

The Arduino UNO Q makes the project **more feasible and more competitive** than a normal Arduino Uno.

Recommended project framing:

> **DARKMAP-Q: Offline Autonomous Reconnaissance Mapping Module for GPS-Denied Environments**

Feasibility score:

| Version | Score |
|---|---:|
| Basic Arduino Uno version | 6.5 / 10 |
| Arduino UNO Q version | 8 / 10 |
| UNO Q + clean demo + onboard map | 8.5 / 10 |

The biggest technical caution is **3.3 V logic compatibility**, especially with 5 V sensors like the HC-SR04 ultrasonic module.
