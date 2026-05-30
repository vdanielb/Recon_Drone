# DARKMAP-Q — Agent Guidance

Offline GPS-denied reconnaissance mapping rover using the **Arduino UNO Q**.
Read this file before making any changes to the codebase.

---

## Project Overview

DARKMAP-Q maps pitch-black, GPS-denied environments with no internet connection.
Two compute subsystems run on the same board:

| Side | Chip | Language | Responsibility |
|---|---|---|---|
| MCU | STM32U585 | Arduino (C++) | Motors, servo, ultrasonic, obstacle avoidance, telemetry |
| Linux MPU | Qualcomm QRB2210 | Python 3 | Pose estimation, 2D mapping, logging, dashboard |

The MCU sends one-line CSV packets over serial. The Python side parses them.

---

## Repository Layout

```text
arduino/darkmap_rover.ino    MCU sketch - motors, servo, HC-SR04, autonomy, telemetry
linux/serial_bridge.py       Telemetry sources: serial / file / stdin / simulator
linux/mapper.py              Pose dead-reckoning, scan→XY, matplotlib map, PNG/CSV export
linux/main.py                Orchestrator: parse packets, log, map, scene labels
linux/scene.py               Rule-based scene classification (no ML)
linux/dashboard.py           Optional Flask dashboard (localhost only, no cloud)
linux/requirements.txt       Python deps: matplotlib, pyserial, Flask
docs/wiring.md               Pin map, voltage-divider diagram, power/ground rules
docs/demo_script.md          Judge demo flow and fallback procedures
docs/pitch.md                30-second pitch and key phrases
data/logs/                   Session CSVs, points CSV, map.png (all gitignored)
markdowns/                   Planning docs - do NOT edit these
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
Valid `mode` values: `AUTO`, `MANUAL`, `SCAN_ONLY`, `STOP`.

---

## Arduino (MCU) Conventions

- All configurable values live as named `const` or `#define` at the top of the sketch. Never hardcode magic numbers inline.
- The MCU is **3.3V logic**. HC-SR04 ECHO is typically 5V — it must go through a voltage divider or level shifter before the UNO Q. Never connect ECHO directly. Never use D3 for a 5V input.
- Do not power DC motors or servo from the UNO Q. They use a separate battery pack through the motor driver with a common ground.
- Movement is step-based (short pulses), not continuous. Each pulse emits a `MOVE` packet before the next action.
- Scanning stops motors first (`stopCar()`) to reduce vibration.
- Distance readings use median-of-3 with clamping (3–250 cm); return `-1` for invalid.
- Serial is opened at 115200 baud. The Linux side must match.

---

## Python Conventions

- All Python files are in `linux/`. Run them from that directory or from the repo root.
- No cloud APIs. No internet required at runtime. Everything is offline-first.
- `mapper.py` owns all state: `Pose`, `obstacle_points`, `path_points`. Do not maintain duplicate pose state in other files.
- Calibration constants (`SPEED_CM_PER_SEC`, `TURN_DEG_PER_SEC`) are in `mapper.py`. Tune these against the real rover; do not change defaults without testing.
- `serial_bridge.py` telemetry sources are independent of the rest of the pipeline. Adding a new source means subclassing `TelemetrySource` and registering it in `make_source()`.
- `scene.py` must stay dependency-free (no numpy, no sklearn). Rule-based logic only.
- `dashboard.py` is optional and must degrade gracefully if Flask is not installed.
- matplotlib uses the `Agg` backend for headless saves; interactive plotting uses `ion()`. Never call `plt.show(blocking=True)` inside the main loop.

---

## Testing (No Hardware Required)

Run the built-in simulator for all pipeline testing:

```bash
cd linux
python3 main.py --source sim --no-plot      # headless, fast
python3 main.py --source sim                # live map window
python3 main.py --source sim --sim-steps 300 --delay 0.05  # longer run
```

Replay a saved log:

```bash
python3 main.py --source file --file ../data/logs/session_XXXX.csv
```

A passing test produces:
- A `data/logs/session_*.csv` with SCAN/MOVE/STATE lines
- A `data/logs/points_*.csv` with obstacle + path points
- A `data/logs/map.png` showing walls and a rover path
- No Python exceptions

---

## What NOT to Change

- **`markdowns/`** — planning docs for the hackathon. Read-only reference.
- **Telemetry format** — changing field positions breaks both the MCU and the parser simultaneously.
- **`SPEED_CM_PER_SEC` / `TURN_DEG_PER_SEC`** without a calibration note explaining why.
- **Motor driver pins D5/D6/D9/D10** without checking the physical wiring first.

---

## Key Safety Rules (never skip these)

1. HC-SR04 ECHO **must** be level-shifted. No direct connection to any 3.3V pin.
2. D3 is not 5V tolerant on the UNO Q. Do not use it for ECHO input.
3. Motor/servo power comes from external battery through the motor driver. Common ground with the UNO Q.
4. The UNO Q needs a stable 5V / 3A USB-C supply. Under-powered boards reset when motors spin.
