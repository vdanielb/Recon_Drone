"""Telemetry input sources for the DARKMAP-Q Linux/mapping side.

The MCU emits CSV telemetry lines (SCAN / MOVE / STATE). This module abstracts
*where* those lines come from so the mapping pipeline can run identically
whether we are connected to real hardware, replaying a saved log, reading
stdin, or generating synthetic data with the built-in simulator.

All sources expose the same interface::

    with make_source(...) as source:
        for line in source.lines():
            handle(line)

Everything here is offline and dependency-light. ``pyserial`` is only imported
when a serial source is actually requested, so the simulator and file replay
work even on machines without pyserial installed.
"""

from __future__ import annotations

import math
import random
import sys
import time
from typing import Iterator, Optional


class TelemetrySource:
    """Base class. Subclasses implement ``lines()`` yielding text lines."""

    def __enter__(self) -> "TelemetrySource":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def lines(self) -> Iterator[str]:  # pragma: no cover - interface
        raise NotImplementedError

    def close(self) -> None:
        pass


class SerialSource(TelemetrySource):
    """Read CSV telemetry from the MCU over a serial port (pyserial)."""

    def __init__(self, port: Optional[str] = None, baud: int = 115200,
                 timeout: float = 1.0) -> None:
        try:
            import serial  # type: ignore
            from serial.tools import list_ports  # type: ignore
        except ImportError as exc:  # pragma: no cover - env dependent
            raise RuntimeError(
                "pyserial is required for the serial source. "
                "Install it with: pip install pyserial"
            ) from exc

        self._serial_mod = serial
        if port is None:
            port = self._autodetect(list_ports)
            if port is None:
                raise RuntimeError(
                    "No serial port found. Pass --port explicitly "
                    "(e.g. --port /dev/ttyACM0)."
                )
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._conn = None

    @staticmethod
    def _autodetect(list_ports) -> Optional[str]:
        candidates = list(list_ports.comports())
        # Prefer typical Arduino/USB-CDC device names.
        for p in candidates:
            name = (p.device or "").lower()
            if any(tag in name for tag in ("acm", "usbmodem", "ttyusb", "usbserial")):
                return p.device
        return candidates[0].device if candidates else None

    def _ensure_open(self):
        if self._conn is None:
            self._conn = self._serial_mod.Serial(
                self.port, self.baud, timeout=self.timeout
            )
        return self._conn

    def lines(self) -> Iterator[str]:
        conn = self._ensure_open()
        while True:
            raw = conn.readline()
            if not raw:
                continue  # timeout, keep waiting
            try:
                yield raw.decode("utf-8", errors="replace").strip()
            except Exception:
                continue

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None


class FileSource(TelemetrySource):
    """Replay telemetry from a previously saved session log file."""

    def __init__(self, path: str, delay: float = 0.0) -> None:
        self.path = path
        self.delay = delay
        self._fh = None

    def lines(self) -> Iterator[str]:
        self._fh = open(self.path, "r", encoding="utf-8")
        for raw in self._fh:
            line = raw.strip()
            if line:
                yield line
                if self.delay > 0:
                    time.sleep(self.delay)

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            finally:
                self._fh = None


class StdinSource(TelemetrySource):
    """Read telemetry lines from standard input (handy for piping/testing)."""

    def lines(self) -> Iterator[str]:
        for raw in sys.stdin:
            line = raw.strip()
            if line:
                yield line


class SimSource(TelemetrySource):
    """Built-in 'rover in a box' simulator.

    Generates realistic SCAN/MOVE/STATE packets so the entire mapping pipeline
    can be demonstrated with no hardware attached. The virtual rover drives
    around a rectangular room, runs the same pulse-based avoidance logic as the
    MCU, and reports ultrasonic distances to the nearest wall per scan angle.
    """

    SCAN_ANGLES = [-75, -45, -20, 0, 20, 45, 75]

    def __init__(self, steps: int = 120, room: float = 200.0,
                 delay: float = 0.05, seed: Optional[int] = 42) -> None:
        self.steps = steps
        self.room = room  # half-width of square room in cm (centered on origin)
        self.delay = delay
        self.rng = random.Random(seed)
        # Virtual rover pose (cm, radians). Mirrors mapper conventions.
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0
        # Calibration must match mapper defaults for a consistent demo.
        self.speed_cm_s = 12.0
        self.turn_deg_s = 90.0
        self.threshold = 30.0
        self.forward_ms = 300
        self.turn_ms = 250
        self.base_speed = 120

    def _t(self) -> int:
        return int(time.time() * 1000) % 10_000_000

    def _wall_distance(self, world_angle: float) -> float:
        """Distance to the nearest axis-aligned wall along ``world_angle``."""
        best = self.room * 4
        dx = math.cos(world_angle)
        dy = math.sin(world_angle)
        for wall, comp, pos in (
            (self.room, dx, self.x), (-self.room, dx, self.x),
            (self.room, dy, self.y), (-self.room, dy, self.y),
        ):
            if abs(comp) < 1e-6:
                continue
            t = (wall - pos) / comp
            if t > 0:
                best = min(best, t)
        # Add a little sensor noise; occasionally drop a reading (-1).
        if self.rng.random() < 0.04:
            return -1.0
        noisy = best + self.rng.uniform(-3.0, 3.0)
        if noisy < 3 or noisy > 250:
            return -1.0
        return noisy

    def _scan_lines(self):
        for ang in self.SCAN_ANGLES:
            world = self.theta + math.radians(ang)
            dist = self._wall_distance(world)
            dist_out = int(dist) if dist >= 0 else -1
            yield f"SCAN,{self._t()},{ang},{dist_out},AUTO"

    def lines(self) -> Iterator[str]:
        yield f"STATE,{self._t()},AUTO,sim_start"
        for _ in range(self.steps):
            front = self._wall_distance(self.theta)
            front_val = front if front >= 0 else 999

            if front_val > self.threshold:
                dist = self.speed_cm_s * self.forward_ms / 1000.0
                self.x += dist * math.cos(self.theta)
                self.y += dist * math.sin(self.theta)
                yield f"MOVE,{self._t()},FORWARD,{self.forward_ms},{self.base_speed}"
            else:
                yield f"STATE,{self._t()},AUTO,blocked"
                left = self._wall_distance(self.theta + math.radians(-75))
                right = self._wall_distance(self.theta + math.radians(75))
                left_s = left if left >= 0 else self.room * 2
                right_s = right if right >= 0 else self.room * 2
                dtheta = math.radians(self.turn_deg_s * self.turn_ms / 1000.0)
                if left_s >= right_s:
                    self.theta += dtheta
                    yield f"MOVE,{self._t()},TURN_LEFT,{self.turn_ms},{self.base_speed}"
                else:
                    self.theta -= dtheta
                    yield f"MOVE,{self._t()},TURN_RIGHT,{self.turn_ms},{self.base_speed}"

            for ln in self._scan_lines():
                yield ln

            if self.delay > 0:
                time.sleep(self.delay)
        yield f"STATE,{self._t()},STOP,sim_done"


def make_source(kind: str, port: Optional[str] = None, file: Optional[str] = None,
                sim_steps: int = 120, delay: float = 0.05) -> TelemetrySource:
    """Factory used by main.py to build the requested telemetry source."""
    kind = (kind or "sim").lower()
    if kind == "serial":
        return SerialSource(port=port)
    if kind == "file":
        if not file:
            raise ValueError("--file is required for the file source")
        return FileSource(file, delay=delay)
    if kind == "stdin":
        return StdinSource()
    if kind == "sim":
        return SimSource(steps=sim_steps, delay=delay)
    raise ValueError(f"Unknown source kind: {kind!r}")
