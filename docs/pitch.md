# DARKMAP-Q Pitch

## Positioning

Do not pitch this as "just an RC car." Pitch it as a payload:

> A modular, offline reconnaissance sensing payload for GPS-denied and low-light
> environments, demonstrated on an RC rover but scalable to drones and UGVs.

## 30-second spoken pitch

DARKMAP-Q is an offline reconnaissance mapping module for GPS-denied and
low-visibility environments. The Arduino UNO Q gives us a dual architecture: the
microcontroller handles real-time movement, ultrasonic scanning, and safety,
while the Linux processor handles mapping and local intelligence. Our RC car is
the test platform, but the sensing and navigation module is designed to scale to
drones or ground robots. It operates without internet, builds a rough 2D map in
darkness, and supports edge features like scene classification and risk-zone
tagging.

## Key phrases

- Offline-first (no cloud dependency during operation)
- GPS-denied navigation
- Pitch-black reconnaissance (ultrasonic needs no light)
- Edge processing / onboard decision logic
- Real-time MCU control + onboard Linux mapping
- Dual-compute architecture
- Modular payload, scalable to drone or ground robot

## Judging strengths

1. Offline-first: no cloud needed during the demo.
2. GPS-denied: designed for indoor / signal-blocked environments.
3. Pitch-black operation: ultrasonic sensing does not need visible light.
4. Dual-compute: MCU for real-time control, Linux for mapping/intelligence.
5. Scalable module: the RC car is only the test platform.
6. Defense relevance: scout dark, unknown spaces before humans enter.
7. Practical: low-cost, modular, fast to deploy.

## What NOT to overclaim

Avoid claiming military-grade SLAM, LiDAR-quality mapping, perfect localization,
battlefield readiness, real target detection (unless implemented), or swarm
coordination. Instead say:

> This is a proof-of-concept for a low-cost offline reconnaissance mapping
> payload.

## Honest limitations + upgrade path

Limitations:

- Ultrasonic mapping is rough, not LiDAR-quality.
- Without wheel encoders, the position estimate drifts.
- Thin / soft / angled surfaces may be missed by ultrasonic.
- A normal camera is useless in total darkness without IR illumination.

Upgrades that address them:

- Wheel encoders + IMU fusion for better odometry.
- 2D LiDAR for higher-resolution mapping.
- IR / thermal camera for dark-environment vision.
- Mesh communication between multiple rovers.
- Drone-compatible mounting bracket for the payload.
