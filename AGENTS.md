# DARKMAP-Q — Agent Guidance

Offline GPS-denied reconnaissance mapping rover using the **Arduino UNO Q**.
Read this file before making any changes to the codebase.

---

## Project Overview

DARKMAP-Q maps pitch-black, GPS-denied environments with no internet connection.
Two compute subsystems run on the same board:

| Side | Chip | Language | Responsibility |
|---|---|---|---|
| MCU | STM32U585 | Arduino (C++) | Motors, servo, ultrasonic, wall-following, obstacle avoidance, telemetry |
| Linux MPU | Qualcomm QRB2210 | Python 3 | Pose estimation, 2D mapping, logging, dashboard |

The MCU sends one-line CSV packets over serial. The Python side parses them.

---

## Repository Layout

```text
arduino/darkmap_rover.ino    MCU sketch - motors, servo, HC-SR04, wall-following, telemetry
linux/serial_bridge.py       Telemetry sources: serial / file / stdin / sim / wallsim
linux/mapper.py              Pose dead-reckoning, scan→XY, matplotlib map, PNG/CSV export
linux/main.py                Orchestrator: parse packets, log, map, scene labels
linux/scene.py               Rule-based scene classification (no ML)
linux/dashboard.py           Optional Flask dashboard (localhost only, no cloud)
linux/requirements.txt       Python deps: matplotlib, pyserial, Flask
data/logs/                   Session CSVs, points CSV, map.png (all gitignored)
```

---

## Telemetry Packet Contract

These are the only line formats the MCU emits and Python parses. Do not change
the field order without updating both sides.

```text
SCAN,timestamp_ms,angle_deg,distance_cm,mode
MOVE,timestamp_ms,action,duration_ms,speed
STATE,timestamp_ms,mode,message
```

Valid `action` values: `FORWARD`, `BACKWARD`, `TURN_LEFT`, `TURN_RIGHT`, `STOP`.
Valid `mode` values: `AUTO`, `MANUAL`, `SCAN_ONLY`, `WALLFOLLOW`, `STOP`.

---

## Operating Modes (5 total)

| Command | Mode | Behaviour |
|---|---|---|
| `a` | `AUTO` | Reactive obstacle avoidance — moves forward, dodges walls |
| `m` | `MANUAL` | Human-driven via `i/k/j/l` keys; scanning continues |
| `o` | `SCAN_ONLY` | Stationary; full servo sweep every 150 ms |
| `w` | `WALLFOLLOW` | Autonomous perimeter scan (right-hand rule, Roomba-style) |
| `x` | `STOP` | Motors off |

---

## Wall-Following Mode (`WALLFOLLOW`)

The primary room-mapping mode. The rover:

1. **Acquisition phase** — drives straight forward until a wall is within
   `WF_CORNER_THRESHOLD_CM`, then turns left 90° so the wall becomes the
   right-side reference.
2. **Following phase** — keeps the right wall at `TARGET_WALL_CM` using a
   five-case decision loop every step:
   - Front blocked → turn left 90° (inner corner)
   - Right wall lost → overshoot + turn right 90° (outer corner)
   - Drifting away from wall → nudge right + forward
   - Too close to wall → nudge left + forward
   - On track → drive straight

Right-wall distance uses `scanRightWall()` which takes the **minimum of the
45° and 75° right-side readings**. This prevents false "wall lost" triggers
at wall segment ends where the outer beam sees past the edge.

### Wall-following constants (all in `darkmap_rover.ino`)

| Constant | Default | Notes |
|---|---|---|
| `WF_TURN90_MS` | 700 ms | Duration of a ~90° in-place turn. **Calibrate on real hardware.** |
| `TURN_PULSE_MS` | 250 ms | Half used for nudge corrections; ~`WF_TURN90_MS / 4` |
| `FORWARD_PULSE_MS` | 300 ms | Step distance per action |
| `TARGET_WALL_CM` | 20 cm | Desired gap to the right wall |
| `WALL_TOLERANCE_CM` | 5 cm | Dead band; widen to reduce oscillation |
| `WF_CORNER_THRESHOLD_CM` | 25 cm | Front distance that triggers a corner turn |
| `WF_OPEN_THRESHOLD_CM` | 50 cm | Right-side distance that counts as "wall lost" |
| `BASE_SPEED` / `TURN_SPEED` | 120 PWM | Motor power 0–255; start low |

---

## Arduino (MCU) Conventions

- All configurable values live as named `const` or `#define` at the top of the
  sketch. Never hardcode magic numbers inline.
- The MCU is **3.3V logic**. HC-SR04 ECHO is typically 5V — it **must** go
  through a voltage divider or level shifter before the UNO Q. Never connect
  ECHO directly. Never use D3 for a 5V input.
- Do not power DC motors or servo from the UNO Q. They use a separate battery
  pack through the motor driver with a common ground.
- Movement is step-based (short pulses), not continuous. Each pulse emits a
  `MOVE` packet before the next action.
- Scanning stops motors first (`stopCar()`) to reduce vibration.
- Distance readings use median-of-3 with clamping (3–250 cm); return `-1` for
  invalid.
- Serial is opened at 115200 baud. The Linux side must match.
- `wf_acquired` is a global bool reset every time `WALLFOLLOW` mode is entered.
  It tracks whether the rover has found its first wall.

---

## Python Conventions

- All Python files are in `linux/`. Run them from that directory or from the
  repo root.
- No cloud APIs. No internet required at runtime. Everything is offline-first.
- `mapper.py` owns all state: `Pose`, `obstacle_points`, `path_points`. Do not
  maintain duplicate pose state in other files.
- Calibration constants (`SPEED_CM_PER_SEC`, `TURN_DEG_PER_SEC`) are in
  `mapper.py`. Tune these against the real rover; do not change defaults without
  testing.
- `serial_bridge.py` telemetry sources are independent of the rest of the
  pipeline. Adding a new source means subclassing `TelemetrySource` and
  registering it in `make_source()`.
- `scene.py` must stay dependency-free (no numpy, no sklearn). Rule-based logic
  only. `classify()` accepts an optional `mode` string; pass `"WALLFOLLOW"` to
  get `WF_CORNER` / `WF_WALL_NEAR` labels.
- `dashboard.py` is optional and must degrade gracefully if Flask is not
  installed.
- matplotlib uses the `Agg` backend for headless saves; interactive plotting
  uses `ion()`. Never call `plt.show(blocking=True)` inside the main loop.

---

## Testing (No Hardware Required)

### Original obstacle-avoidance simulator

```bash
cd linux
python3 main.py --source sim --no-plot           # headless
python3 main.py --source sim                     # live map window
python3 main.py --source sim --sim-steps 300     # longer run
```

### Wall-follow simulator (`wallsim`)

Simulates `WALLFOLLOW` mode against a polygon room using ray-casting.
The virtual rover runs the exact same five-case logic as the MCU.

```bash
# Default 300×300 cm square
python3 main.py --source wallsim --sim-steps 300 --hold

# Rectangle
python3 main.py --source wallsim --room rect:500x300 --sim-steps 300 --hold

# Circle (diameter in cm, optional segment count)
python3 main.py --source wallsim --room circle:300 --sim-steps 450 --hold
python3 main.py --source wallsim --room circle:300:64 --sim-steps 500 --hold

# Equilateral triangle (side length in cm)
python3 main.py --source wallsim --room triangle:300 --sim-steps 350 --hold

# L-shaped room (tests open outer corner)
python3 main.py --source wallsim --room l-shape --sim-steps 400 --hold

# Custom polygon (comma-separated x,y vertex pairs in cm)
python3 main.py --source wallsim --room "poly:0,0,400,0,400,300,0,300" --sim-steps 400 --hold

# Headless (no display)
python3 main.py --source wallsim --room square:300 --sim-steps 300 --no-plot
```

### Replay a saved log

```bash
python3 main.py --source file --file ../data/logs/session_XXXX.csv
```

### A passing test produces

- A `data/logs/session_*.csv` with SCAN/MOVE/STATE lines
- A `data/logs/points_*.csv` with obstacle + path points
- A `data/logs/map.png` showing walls and a rover path that traces the perimeter
- No Python exceptions

---

## Hardware Calibration Checklist

When moving from simulation to real hardware, calibrate in this order:

1. **Pin assignments** — verify `#define` blocks in the sketch match your wiring
2. **`SERVO_CENTER`** (default 90) — sensor should point straight ahead
3. **`BASE_SPEED` / `TURN_SPEED`** (default 120) — start slow (~80–100 PWM)
4. **`WF_TURN90_MS`** (default 700 ms) — mark 90° on floor, turn in place, adjust
5. **`TURN_PULSE_MS`** / **`FORWARD_PULSE_MS`** — step size and nudge intensity
6. **Wall-follow thresholds** — test in a square room; adjust `TARGET_WALL_CM`,
   `WF_CORNER_THRESHOLD_CM`, `WF_OPEN_THRESHOLD_CM` for your room size
7. **`SPEED_CM_PER_SEC`** in `mapper.py` — measure real forward speed
8. **`TURN_DEG_PER_SEC`** in `mapper.py` — measure real turn rate

If `SPEED_CM_PER_SEC` or `TURN_DEG_PER_SEC` are wrong the obstacle map will
look rotated or sheared even when navigation is correct.

---

## What NOT to Change

- **Telemetry format** — changing field positions breaks both the MCU and the
  parser simultaneously.
- **`SPEED_CM_PER_SEC` / `TURN_DEG_PER_SEC`** without a calibration note.
- **Motor driver pins D5/D6/D9/D10** without checking the physical wiring first.
- **`scanRightWall()`** logic — it uses min(45°, 75°) specifically to prevent
  false open-corner reads at wall segment ends. Do not reduce this to a single
  angle.

---

## Key Safety Rules (never skip these)

1. HC-SR04 ECHO **must** be level-shifted (2kΩ + 1kΩ divider or equivalent).
   No direct connection to any 3.3V pin.
2. D3 is not 5V tolerant on the UNO Q. Do not use it for ECHO input.
3. Motor/servo power comes from external battery through the motor driver.
   Common ground with the UNO Q.
4. The UNO Q needs a stable 5V / 3A USB-C supply. Under-powered boards reset
   when motors spin.
