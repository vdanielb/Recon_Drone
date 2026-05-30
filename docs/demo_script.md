# DARKMAP-Q Demo Script

A repeatable 60-120 second judging demo. Practice it end-to-end at least 5 times
before judging.

## Demo environment

```text
Arena:    1.5 m x 1.5 m to 2 m x 2 m
Walls:    cardboard boxes or foam boards
Lighting: dim or fully dark (this is the point - ultrasonic needs no light)
Speed:    slow (step-based motion)
Duration: 60-120 seconds
```

## Pre-demo checklist

- [ ] Batteries charged (motor pack + UNO Q power)
- [ ] Backup USB-C cable ready
- [ ] Laptop ready with `linux/` and a terminal open
- [ ] One known-good saved map screenshot ready (`data/logs/map.png`)
- [ ] Backup demo video ready
- [ ] Internet OFF (or be ready to point out nothing uses the network)
- [ ] Fallback manual mode tested (`m` then `i/j/k/l`)

## Run order (live rover)

1. Power the UNO Q and the motor battery. Confirm `STATE,...,boot_ok` appears.
2. On the laptop / UNO Q Linux side:
   ```bash
   cd linux
   python3 main.py --source serial --port /dev/ttyACM0
   ```
3. Put the rover at the arena entrance.
4. Send `a` (AUTO) over the serial monitor / console to start autonomy.
5. The rover scans, steps forward when clear, stops and turns toward open space
   when blocked. Obstacle points and the path appear live on the 2D map.
6. After ~60-120 s, send `x` (STOP).
7. Show the generated map (`data/logs/map.png`) and the session log CSV.
8. Explain how the same sensing/mapping payload scales to UGVs or drones.

## What to say while it runs

- "Everything is running offline on the board - no cloud, no GPS."
- "The microcontroller handles real-time motor, servo, and ultrasonic timing;
   the Linux side does the mapping, logging, and scene classification."
- "It maps in total darkness because ultrasonic sensing doesn't need light."
- "Motion is step-based and slow on purpose - it keeps the rough map clean."

## No-hardware backup (always works)

If the rover misbehaves, run the built-in simulator. It produces the same
telemetry and a real map so the mapping story still lands:

```bash
cd linux
python3 main.py --source sim          # live map window
# or headless, then show the PNG:
python3 main.py --source sim --no-plot
```

Optionally show the local dashboard:

```bash
python3 dashboard.py        # then open http://127.0.0.1:8000
```

## Fallback modes

- **Autonomy flaky?** Switch to MANUAL (`m`) and drive with `i/j/k/l` (space to
  stop). The rover still scans and maps automatically. Pitch it as
  "operator-supervised reconnaissance with autonomous sensing and mapping."
- **Mapping window fails?** Show the saved `map.png`, the live serial scan data,
  and the obstacle-avoidance behavior on its own.
- **Ultrasonic noisy?** Use SCAN_ONLY mode (`o`) as a stationary radar sweep,
  keep the arena walls large and flat, and rely on the median-filtered readings.

## Reset procedure between runs

1. Send `x` to stop.
2. Pick up the rover, place it back at the start.
3. Restart `main.py` (a fresh session log + map are created each run).
4. Send `a` to begin again.
