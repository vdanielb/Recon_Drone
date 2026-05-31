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

## Run order (live rover — UNO Q primary)

1. Power the UNO Q and the motor battery. Confirm `STATE,...,boot_ok` appears.
2. On the board, run the Arduino App Lab project — its Python main is
   `linux/main.py` (mapping + edge YOLO + dashboard all start on the board).
3. Join the laptop Wi-Fi hotspot from the board; find the board IP
   (e.g. `192.168.137.x`).
4. On the laptop, open `http://<board-ip>:8000` — live map, radar, camera, detections.
5. Put the rover at the arena entrance.
6. Send `a` (AUTO) over the serial monitor / MCU console to start autonomy.
7. After ~60-120 s, send `x` (STOP).
8. Show the dashboard map and `data/logs/map.png` on the board (or copy logs off).
9. Explain how the same sensing/mapping payload scales to UGVs or drones.

### Legacy: laptop runs `pipeline.py` (TCP relay)

If using `uno_q_forwarder.py` on the board instead of `main.py`:

```bash
# Laptop
cd linux
python3 pipeline.py --source net
python3 dashboard.py   # optional; camera only if laptop has a webcam
```

### Direct serial (non–UNO Q or MCU exposed as `/dev/ttyACM0`)

```bash
cd linux
python3 pipeline.py --source serial --port /dev/ttyACM0
```

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
python3 pipeline.py --source sim          # live map window
# or headless, then show the PNG:
python3 pipeline.py --source sim --no-plot
```

Optionally show the local dashboard (sim writes `status.json` on the same machine):

```bash
python3 dashboard.py        # then open http://127.0.0.1:8000
```

For a live UNO Q run, open `http://<board-ip>:8000` instead (dashboard runs on the board).

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
3. Restart the App Lab project / `pipeline.py` (a fresh session log + map are created each run).
4. Send `a` to begin again.
