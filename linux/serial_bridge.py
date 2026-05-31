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
import socket
import sys
import time
from typing import Iterator, Optional


# VL53L4CD (Modulino Distance) sim model — mirrors firmware DIST_MAX_CM.
TOF_MAX_CM = 130.0     # usable range cap (~1-130 cm)
TOF_MIN_CM = 2.0
TOF_NOISE_CM = 0.7     # ~+/-7 mm accuracy
TOF_MISS_PROB = 0.01   # occasional dropped frame


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


class NetworkSource(TelemetrySource):
    """Accept CSV telemetry over TCP from the UNO Q board relay.

    The board's ``uno_q_forwarder.py`` connects as a client and streams
    newline-delimited SCAN / MOVE / STATE lines.  This source binds a TCP
    server on the laptop and yields lines from the active connection.
    On disconnect it waits for the board to reconnect.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 9009) -> None:
        self.host = host
        self.port = port
        self._server: Optional[socket.socket] = None
        self._conn: Optional[socket.socket] = None

    def lines(self) -> Iterator[str]:
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((self.host, self.port))
        self._server.listen(1)
        print(f"[net] listening on {self.host}:{self.port} (waiting for board)")

        buffer = ""
        while True:
            if self._conn is None:
                self._conn, addr = self._server.accept()
                self._conn.settimeout(None)
                print(f"[net] client connected from {addr[0]}:{addr[1]}")
                buffer = ""

            try:
                data = self._conn.recv(4096)
                if not data:
                    print("[net] client disconnected; waiting for reconnect...")
                    self._drop_client()
                    continue

                buffer += data.decode("utf-8", errors="replace")
                while "\n" in buffer:
                    line, buffer = buffer.split("\n", 1)
                    line = line.strip()
                    if line:
                        yield line
            except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                print(f"[net] connection lost ({exc}); waiting for reconnect...")
                self._drop_client()

    def _drop_client(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def close(self) -> None:
        self._drop_client()
        if self._server is not None:
            try:
                self._server.close()
            finally:
                self._server = None


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
        if self.rng.random() < TOF_MISS_PROB:
            return -1.0
        noisy = best + self.rng.uniform(-TOF_NOISE_CM, TOF_NOISE_CM)
        if noisy < TOF_MIN_CM or noisy > TOF_MAX_CM:
            return -1.0
        return noisy

    def _heading_line(self):
        yaw = math.degrees(self.theta)
        yaw = (yaw + 180.0) % 360.0 - 180.0
        yield f"HEADING,{self._t()},{yaw:.2f}"

    def _scan_lines(self):
        yield from self._heading_line()
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


# ---------------------------------------------------------------------------
# Room polygon helpers
# ---------------------------------------------------------------------------

def _circle_vertices(diameter: float, segments: int = 48) -> list:
    """Approximate a circle as a regular polygon centred on the origin."""
    radius = diameter / 2.0
    segments = max(12, segments)
    return [
        (radius * math.cos(2 * math.pi * i / segments),
         radius * math.sin(2 * math.pi * i / segments))
        for i in range(segments)
    ]


def _triangle_vertices(side: float) -> list:
    """Equilateral triangle centred on the origin; *side* is edge length in cm."""
    r = side / math.sqrt(3.0)  # circumradius
    return [
        (0.0, r),
        (-side / 2.0, -r / 2.0),
        (side / 2.0, -r / 2.0),
    ]


def _parse_room(spec: Optional[str]) -> list:
    """Parse a --room specification into a list of (x, y) vertex tuples.

    Supported formats
    -----------------
    square          -> 300 cm × 300 cm square centred on the origin
    square:N        -> N cm × N cm square centred on the origin
    rect:WxH        -> W cm wide × H cm tall rectangle centred on the origin
    circle          -> 300 cm diameter circle (48-sided polygon)
    circle:N        -> N cm diameter circle
    circle:N:S      -> N cm diameter, S polygon segments (default 48)
    triangle        -> equilateral triangle, 300 cm side length
    triangle:N      -> equilateral triangle, N cm side length
    l-shape         -> an L-shaped room (good for testing corner turns)
    poly:x1,y1,x2,y2,...  -> arbitrary polygon (even number of values, ≥ 3 pairs)

    Returns vertices in order (winding does not matter; edges are the pairs of
    consecutive vertices, with the last vertex connecting back to the first).
    """
    spec = (spec or "square").strip().lower()

    if spec == "square" or spec.startswith("square:"):
        size = 300.0
        if ":" in spec:
            size = float(spec.split(":", 1)[1])
        h = size / 2.0
        return [(-h, -h), (h, -h), (h, h), (-h, h)]

    if spec.startswith("rect:"):
        dims = spec[5:].lower().replace("x", ",").split(",")
        w, h = float(dims[0]) / 2.0, float(dims[1]) / 2.0
        return [(-w, -h), (w, -h), (w, h), (-w, h)]

    if spec == "circle" or spec.startswith("circle:"):
        diameter = 300.0
        segments = 48
        if ":" in spec:
            parts = spec.split(":")
            diameter = float(parts[1])
            if len(parts) >= 3:
                segments = int(parts[2])
        return _circle_vertices(diameter, segments)

    if spec == "triangle" or spec.startswith("triangle:"):
        side = 300.0
        if ":" in spec:
            side = float(spec.split(":", 1)[1])
        return _triangle_vertices(side)

    if spec == "l-shape":
        # An L-shaped room:  wide base + narrow upper-left arm.
        #  (-150,150)---(-50,150)
        #       |            |
        # (-150,50)--(150,50) |
        #       |             |
        # (-150,-150)---(150,-150)
        return [
            (-150, -150), (150, -150), (150, 50),
            (-50,  50),   (-50, 150), (-150, 150),
        ]

    if spec.startswith("poly:"):
        vals = [float(v) for v in spec[5:].split(",")]
        if len(vals) < 6 or len(vals) % 2 != 0:
            raise ValueError(
                "--room poly: needs at least 3 x,y pairs (6 comma-separated values)"
            )
        return [(vals[i], vals[i + 1]) for i in range(0, len(vals), 2)]

    raise ValueError(
        f"Unknown --room format: {spec!r}. "
        "Use: square, square:N, rect:WxH, circle, circle:N, circle:N:S, "
        "triangle, triangle:N, l-shape, or poly:x1,y1,x2,y2,..."
    )


def _room_edges(vertices: list) -> list:
    """Return the list of wall segments [(x1,y1,x2,y2), ...] for a polygon."""
    edges = []
    n = len(vertices)
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        edges.append((x1, y1, x2, y2))
    return edges


def _ray_wall_distance(ox: float, oy: float, world_angle: float,
                       edges: list, noise_rng: random.Random,
                       max_cm: float = TOF_MAX_CM) -> float:
    """Cast a ray from (ox, oy) at world_angle and return cm to nearest wall.

    Returns -1.0 on sensor miss (4 % probability) or when nothing is hit.
    """
    dx = math.cos(world_angle)
    dy = math.sin(world_angle)
    best_t = None

    for x1, y1, x2, y2 in edges:
        ex, ey = x2 - x1, y2 - y1
        denom = dx * ey - dy * ex
        if abs(denom) < 1e-9:
            continue
        t = ((x1 - ox) * ey - (y1 - oy) * ex) / denom
        u = ((x1 - ox) * dy - (y1 - oy) * dx) / denom
        if t > 1e-3 and 0.0 <= u <= 1.0:
            if best_t is None or t < best_t:
                best_t = t

    if best_t is None:
        return -1.0
    if noise_rng.random() < TOF_MISS_PROB:
        return -1.0
    noisy = best_t + noise_rng.uniform(-TOF_NOISE_CM, TOF_NOISE_CM)
    if noisy < TOF_MIN_CM or noisy > max_cm:
        return -1.0
    return noisy


# ---------------------------------------------------------------------------
# Wall-following simulator
# ---------------------------------------------------------------------------

class WallFollowSimSource(TelemetrySource):
    """Simulate the WALLFOLLOW Arduino mode against an arbitrary polygon room.

    The virtual rover executes the same decision logic as ``wallFollowStep()``
    on the MCU (left-hand rule — the wall is kept on the rover's left).
    Distances are computed by ray-casting against the room's walls, so any
    polygon you pass in is supported.

    Room shapes
    -----------
    Pass a ``room`` string (see ``_parse_room``) or supply ``vertices``
    directly as a list of (x, y) tuples.

    Examples::

        WallFollowSimSource(room="square:400")
        WallFollowSimSource(room="rect:500x300")
        WallFollowSimSource(room="l-shape")
        WallFollowSimSource(room="poly:0,0,400,0,400,300,0,300")
    """

    SCAN_ANGLES = [-75, -45, -20, 0, 20, 45, 75]

    # Mirror the Arduino constants (match darkmap_rover.ino defaults).
    TARGET_WALL_CM         = 20
    WALL_TOLERANCE_CM      = 5
    WF_CORNER_THRESHOLD_CM = 25
    WF_OPEN_THRESHOLD_CM   = 50
    FORWARD_PULSE_MS       = 300
    TURN_PULSE_MS          = 250
    BASE_SPEED             = 120
    TURN_SPEED             = 120
    SPEED_CM_PER_SEC       = 12.0
    TURN_DEG_PER_SEC       = 90.0
    # The Arduino WF_TURN90_MS is tuned for the real motor and is deliberately
    # NOT copied here.  In simulation TURN_DEG_PER_SEC is exactly 90°/s, so a
    # perfect 90° turn needs exactly 1000 ms.  The real rover will need a
    # different value (calibrate on hardware).
    WF_TURN90_MS           = 1000

    def __init__(self, steps: int = 300, room: Optional[str] = None,
                 vertices: Optional[list] = None, delay: float = 0.03,
                 seed: Optional[int] = 42) -> None:
        self.steps = steps
        self.delay = delay
        self.rng = random.Random(seed)

        verts = vertices if vertices is not None else _parse_room(room)
        self.edges = _room_edges(verts)

        # Place the rover near the centre, facing +X (east).
        self.x = 0.0
        self.y = 0.0
        self.theta = 0.0  # radians; 0 = +X axis
        self._acquired = False  # Phase 1 acquisition flag

    def _t(self) -> int:
        return int(time.time() * 1000) % 10_000_000

    def _dist(self, angle_deg: int) -> float:
        world = self.theta + math.radians(angle_deg)
        return _ray_wall_distance(self.x, self.y, world, self.edges, self.rng)

    def _left_wall_dist(self) -> float:
        """Closest left-side wall reading (min of the two left beams).

        Matches ``leftWallFromSweep()`` on the MCU, which takes the minimum of
        the -45 and -75 readings.  Using two angles prevents false OPEN
        triggers at wall ends where the outer beam sees past the segment.
        """
        readings = []
        for ang in (-75, -45):
            d = self._dist(ang)
            if d >= 0:
                readings.append(d)
        if not readings:
            return -1.0
        return min(readings)

    def _heading_line(self):
        yaw = math.degrees(self.theta)
        yaw = (yaw + 180.0) % 360.0 - 180.0
        yield f"HEADING,{self._t()},{yaw:.2f}"

    def _scan_lines(self):
        yield from self._heading_line()
        for ang in self.SCAN_ANGLES:
            d = self._dist(ang)
            d_out = int(d) if d >= 0 else -1
            yield f"SCAN,{self._t()},{ang},{d_out},WALLFOLLOW"

    def _apply_forward(self, ms: int):
        dist = self.SPEED_CM_PER_SEC * ms / 1000.0
        self.x += dist * math.cos(self.theta)
        self.y += dist * math.sin(self.theta)

    def _apply_turn_left(self, ms: int):
        self.theta += math.radians(self.TURN_DEG_PER_SEC * ms / 1000.0)
        self.theta = (self.theta + math.pi) % (2 * math.pi) - math.pi

    def _apply_turn_right(self, ms: int):
        self.theta -= math.radians(self.TURN_DEG_PER_SEC * ms / 1000.0)
        self.theta = (self.theta + math.pi) % (2 * math.pi) - math.pi

    def lines(self) -> Iterator[str]:
        yield f"STATE,{self._t()},WALLFOLLOW,sim_wallfollow_start"
        self._acquired = False

        for _ in range(self.steps):
            front_raw = self._dist(0)
            left_raw  = self._left_wall_dist()

            front = front_raw if front_raw >= 0 else 250.0
            left  = left_raw  if left_raw  >= 0 else 250.0

            # ----------------------------------------------------------
            # Phase 1: acquisition – drive straight to find a wall, then
            # reorient so the wall sits on the rover's left.
            # ----------------------------------------------------------
            if not self._acquired:
                if front <= self.WF_CORNER_THRESHOLD_CM:
                    yield f"STATE,{self._t()},WALLFOLLOW,wf_acquired"
                    self._apply_turn_left(self.WF_TURN90_MS)
                    yield (f"MOVE,{self._t()},TURN_LEFT,"
                           f"{self.WF_TURN90_MS},{self.TURN_SPEED}")
                    self._acquired = True
                else:
                    self._apply_forward(self.FORWARD_PULSE_MS)
                    yield (f"MOVE,{self._t()},FORWARD,"
                           f"{self.FORWARD_PULSE_MS},{self.BASE_SPEED}")
                yield from self._scan_lines()
                if self.delay > 0:
                    time.sleep(self.delay)
                continue

            # ----------------------------------------------------------
            # Phase 2: left-hand wall-following.
            # ----------------------------------------------------------
            if front <= self.WF_CORNER_THRESHOLD_CM:
                # Inner corner: something ahead. Turn away from the left wall.
                yield f"STATE,{self._t()},WALLFOLLOW,wf_corner"
                self._apply_turn_left(self.WF_TURN90_MS)
                yield (f"MOVE,{self._t()},TURN_LEFT,"
                       f"{self.WF_TURN90_MS},{self.TURN_SPEED}")

            elif left > self.WF_OPEN_THRESHOLD_CM:
                # Outer corner: left wall ended. Overshoot, then wrap toward it.
                self._apply_forward(self.FORWARD_PULSE_MS)
                yield (f"MOVE,{self._t()},FORWARD,"
                       f"{self.FORWARD_PULSE_MS},{self.BASE_SPEED}")
                self._apply_turn_right(self.WF_TURN90_MS)
                yield (f"MOVE,{self._t()},TURN_RIGHT,"
                       f"{self.WF_TURN90_MS},{self.TURN_SPEED}")

            elif left > self.TARGET_WALL_CM + self.WALL_TOLERANCE_CM:
                # Drifting away from the left wall: nudge back toward it.
                self._apply_turn_right(self.TURN_PULSE_MS // 2)
                yield (f"MOVE,{self._t()},TURN_RIGHT,"
                       f"{self.TURN_PULSE_MS // 2},{self.TURN_SPEED}")
                self._apply_forward(self.FORWARD_PULSE_MS)
                yield (f"MOVE,{self._t()},FORWARD,"
                       f"{self.FORWARD_PULSE_MS},{self.BASE_SPEED}")

            elif left < self.TARGET_WALL_CM - self.WALL_TOLERANCE_CM:
                # Too close to the left wall: nudge away from it.
                self._apply_turn_left(self.TURN_PULSE_MS // 2)
                yield (f"MOVE,{self._t()},TURN_LEFT,"
                       f"{self.TURN_PULSE_MS // 2},{self.TURN_SPEED}")
                self._apply_forward(self.FORWARD_PULSE_MS)
                yield (f"MOVE,{self._t()},FORWARD,"
                       f"{self.FORWARD_PULSE_MS},{self.BASE_SPEED}")

            else:
                self._apply_forward(self.FORWARD_PULSE_MS)
                yield (f"MOVE,{self._t()},FORWARD,"
                       f"{self.FORWARD_PULSE_MS},{self.BASE_SPEED}")

            yield from self._scan_lines()

            if self.delay > 0:
                time.sleep(self.delay)

        yield f"STATE,{self._t()},STOP,sim_done"


def make_source(kind: str, port: Optional[str] = None, file: Optional[str] = None,
                sim_steps: int = 120, delay: float = 0.05,
                room: Optional[str] = None,
                listen_host: str = "0.0.0.0",
                listen_port: int = 9009) -> TelemetrySource:
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
    if kind == "net":
        return NetworkSource(host=listen_host, port=listen_port)
    if kind == "sim":
        return SimSource(steps=sim_steps, delay=delay)
    if kind == "wallsim":
        return WallFollowSimSource(steps=sim_steps, room=room, delay=delay)
    raise ValueError(f"Unknown source kind: {kind!r}")
