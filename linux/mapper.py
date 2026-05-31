"""Pose estimation and 2D mapping for DARKMAP-Q.

The mapper keeps a rough estimate of the rover pose using dead reckoning
(no wheel encoders), converts each ultrasonic SCAN reading into a world-frame
obstacle point, and renders a live matplotlib map (obstacles + path + current
pose). It can also dump the obstacle/path points to CSV and save the final map
as a PNG.

Conventions
-----------
- Distances are in centimeters.
- ``theta`` is the heading in radians, 0 = +X axis, increasing counter-clockwise.
- A relative scan ``angle_deg`` of 0 points straight ahead; negative = left,
  positive = right (matching the MCU sketch).
"""

from __future__ import annotations

import csv
import math
import os
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# Calibration values - tune these against the real rover during testing.
# These are RATES, and apply_move() scales them by each MOVE packet's
# duration_ms. So changing FORWARD_PULSE_MS / WF_TURN90_MS in the sketch needs
# NO change here (the new duration arrives in the packet). Only re-measure when
# the rover's physical speed/turn-rate changes (motors, battery, surface, load).
#
# 23.0 cm/s: measured 11.5 cm per 500 ms forward pulse -> 11.5 / 0.5 = 23.0.
SPEED_CM_PER_SEC = 23.0   # forward speed estimate
# 180.0 deg/s: ~90 deg per 500 ms in-place turn -> 90 / 0.5 = 180.
TURN_DEG_PER_SEC = 180.0  # in-place turn rate estimate

# Snap obstacle points to a 2 cm grid to dedup (ToF precision).
OBSTACLE_BIN_CM = 2.0

# Recon detection category -> marker color (shared concept with the dashboard).
CATEGORY_COLORS = {
    "human":       "#ff5470",
    "bag":         "#f5a623",
    "electronics": "#4ea8ff",
    "environment": "#22d3a0",
}
DEFAULT_TAG_COLOR = "#c0c0c0"


@dataclass
class Pose:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0  # radians


@dataclass
class Mapper:
    """Maintains pose, obstacle point cloud, and the rover path."""

    speed_cm_per_sec: float = SPEED_CM_PER_SEC
    turn_deg_per_sec: float = TURN_DEG_PER_SEC

    pose: Pose = field(default_factory=Pose)
    obstacle_points: List[Tuple[float, float]] = field(default_factory=list)
    path_points: List[Tuple[float, float]] = field(default_factory=list)
    last_distance_cm: Optional[float] = None
    last_scan: List[Tuple[int, float]] = field(default_factory=list)  # (angle, dist)
    # Camera/YOLO recon tags: {x, y, category, label, conf, note}
    detection_tags: List[dict] = field(default_factory=list)
    # When True, HEADING packets own theta; skip turn dead-reckoning on MOVE.
    _imu_heading: bool = field(default=False, repr=False)
    _obstacle_cells: set = field(default_factory=set, repr=False)

    def __post_init__(self) -> None:
        # Seed the path with the starting position.
        self.path_points.append((self.pose.x, self.pose.y))

    # ----- pose updates (dead reckoning) -----------------------------------
    def set_heading(self, yaw_deg: float) -> None:
        """Set pose heading from MPU6050 HEADING telemetry (CCW-positive degrees)."""
        self.pose.theta = math.radians(yaw_deg)
        self.pose.theta = _wrap_angle(self.pose.theta)
        self._imu_heading = True

    def apply_move(self, action: str, duration_ms: float, speed: float = 0.0) -> None:
        """Update the pose estimate from a MOVE event."""
        action = action.upper()
        seconds = max(0.0, duration_ms / 1000.0)

        if action in ("FORWARD", "BACKWARD"):
            dist = self.speed_cm_per_sec * seconds
            if action == "BACKWARD":
                dist = -dist
            self.pose.x += dist * math.cos(self.pose.theta)
            self.pose.y += dist * math.sin(self.pose.theta)
            self.path_points.append((self.pose.x, self.pose.y))

        elif action in ("TURN_LEFT", "LEFT") and not self._imu_heading:
            self.pose.theta += math.radians(self.turn_deg_per_sec * seconds)

        elif action in ("TURN_RIGHT", "RIGHT") and not self._imu_heading:
            self.pose.theta -= math.radians(self.turn_deg_per_sec * seconds)

        elif action == "STOP":
            pass

        self.pose.theta = _wrap_angle(self.pose.theta)

    # ----- scans -----------------------------------------------------------
    def add_scan(self, angle_deg: float, distance_cm: float) -> bool:
        """Convert a scan reading to a world obstacle point.

        Returns True if a valid obstacle point was added. Invalid readings
        (distance < 0) update ``last_scan`` but are not plotted.
        """
        self.last_distance_cm = distance_cm
        valid = distance_cm is not None and distance_cm >= 0
        self.last_scan.append((int(angle_deg), float(distance_cm)))
        # Keep last_scan bounded to roughly one sweep for scene classification.
        if len(self.last_scan) > 7:
            self.last_scan = self.last_scan[-7:]

        if not valid:
            return False

        world_angle = self.pose.theta + math.radians(angle_deg)
        px = self.pose.x + distance_cm * math.cos(world_angle)
        py = self.pose.y + distance_cm * math.sin(world_angle)
        cell = (round(px / OBSTACLE_BIN_CM), round(py / OBSTACLE_BIN_CM))
        if cell not in self._obstacle_cells:
            self._obstacle_cells.add(cell)
            self.obstacle_points.append((px, py))
        return True

    # ----- detection tags (camera + YOLO) ----------------------------------
    def add_detection_tag(self, category: str, label: str, conf: float,
                          distance_cm: Optional[float],
                          bearing_deg: float = 0.0,
                          note: str = "") -> dict:
        """Place a recon detection on the map.

        WHERE comes from the latest front ultrasonic distance (passed in);
        WHAT comes from the camera/YOLO classifier. If ``distance_cm`` is
        valid, the tag is projected along the rover heading (plus the camera
        bearing offset). Otherwise it is placed just ahead of the rover pose
        and annotated note="distance_unknown".
        """
        valid = distance_cm is not None and distance_cm >= 0
        world_angle = self.pose.theta + math.radians(bearing_deg)
        if valid:
            tx = self.pose.x + distance_cm * math.cos(world_angle)
            ty = self.pose.y + distance_cm * math.sin(world_angle)
        else:
            # Small forward offset so the marker is not under the rover icon.
            offset = 12.0
            tx = self.pose.x + offset * math.cos(world_angle)
            ty = self.pose.y + offset * math.sin(world_angle)
            note = note or "distance_unknown"

        tag = {
            "x": round(tx, 1),
            "y": round(ty, 1),
            "category": category,
            "label": label,
            "conf": round(float(conf), 3),
            "note": note,
        }
        self.detection_tags.append(tag)
        return tag

    # ----- persistence -----------------------------------------------------
    def save_points_csv(self, path: str) -> None:
        _ensure_parent(path)
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            # Extra trailing columns are blank for path/obstacle rows; this
            # keeps the schema backward-compatible while carrying detections.
            w.writerow(["type", "x_cm", "y_cm", "category", "label", "conf", "note"])
            for (x, y) in self.path_points:
                w.writerow(["path", f"{x:.2f}", f"{y:.2f}", "", "", "", ""])
            for (x, y) in self.obstacle_points:
                w.writerow(["obstacle", f"{x:.2f}", f"{y:.2f}", "", "", "", ""])
            for t in self.detection_tags:
                w.writerow(["detection", f"{t['x']:.2f}", f"{t['y']:.2f}",
                            t["category"], t["label"], f"{t['conf']:.3f}",
                            t.get("note", "")])

    def save_map(self, path: str = "data/logs/map.png") -> Optional[str]:
        """Render the current map to a PNG (headless-safe)."""
        try:
            import matplotlib
            matplotlib.use("Agg")  # no display needed
            import matplotlib.pyplot as plt
        except ImportError:
            print("[mapper] matplotlib not installed; skipping PNG save.")
            return None

        _ensure_parent(path)
        fig, ax = plt.subplots(figsize=(7, 7))
        self._draw(ax, plt)
        fig.savefig(path, dpi=120, bbox_inches="tight")
        plt.close(fig)
        return path

    # ----- drawing helper shared by save + live view ----------------------
    def _draw(self, ax, plt) -> None:
        ax.clear()
        if self.obstacle_points:
            ox, oy = zip(*self.obstacle_points)
            ax.scatter(ox, oy, s=8, c="#d9534f", label="obstacles")
        if len(self.path_points) >= 2:
            pxs, pys = zip(*self.path_points)
            ax.plot(pxs, pys, "-", c="#0275d8", linewidth=1.5, label="path")
        # Detection tags (camera + YOLO) drawn above obstacles.
        seen_categories = set()
        for t in self.detection_tags:
            color = CATEGORY_COLORS.get(t["category"], DEFAULT_TAG_COLOR)
            # Only label the legend once per category to keep it uncluttered.
            lbl = t["category"] if t["category"] not in seen_categories else None
            seen_categories.add(t["category"])
            ax.scatter([t["x"]], [t["y"]], s=70, marker="D",
                       facecolors="none", edgecolors=color, linewidths=1.8,
                       zorder=5, label=lbl)
            ax.annotate(t["label"], (t["x"], t["y"]),
                        textcoords="offset points", xytext=(6, 4),
                        fontsize=7, color=color, zorder=6)

        # Current rover pose marker + heading arrow.
        ax.plot(self.pose.x, self.pose.y, marker="o", markersize=9,
                color="#5cb85c", label="rover")
        ax.arrow(self.pose.x, self.pose.y,
                 18 * math.cos(self.pose.theta), 18 * math.sin(self.pose.theta),
                 head_width=6, head_length=6, fc="#5cb85c", ec="#5cb85c")

        ax.set_aspect("equal", adjustable="datalim")
        ax.grid(True, linestyle=":", alpha=0.5)
        ax.set_title("DARKMAP-Q  -  Offline 2D Map (cm)")
        ax.set_xlabel("x (cm)")
        ax.set_ylabel("y (cm)")
        ax.legend(loc="upper right", fontsize=8)


# ---------------------------------------------------------------------------
# Live viewer (interactive). Kept separate so headless/save path has no deps
# on an interactive backend.
# ---------------------------------------------------------------------------
class LiveMap:
    """Throttled interactive matplotlib view of a Mapper."""

    def __init__(self, mapper: Mapper, redraw_every: int = 7) -> None:
        self.mapper = mapper
        self.redraw_every = max(1, redraw_every)
        self._since = 0
        self._ok = False
        try:
            import matplotlib.pyplot as plt
            self._plt = plt
            plt.ion()
            self._fig, self._ax = plt.subplots(figsize=(7, 7))
            self._fig.show()
            self._ok = True
        except Exception as exc:  # pragma: no cover - display dependent
            print(f"[mapper] live plotting unavailable ({exc}); "
                  f"running headless.")

    def notify(self, force: bool = False) -> None:
        if not self._ok:
            return
        self._since += 1
        if not force and self._since < self.redraw_every:
            return
        self._since = 0
        self.mapper._draw(self._ax, self._plt)
        self._fig.canvas.draw_idle()
        self._plt.pause(0.001)

    def hold(self) -> None:
        """Block so the final window stays open (interactive sessions)."""
        if self._ok:
            self._plt.ioff()
            self._plt.show()


def _wrap_angle(theta: float) -> float:
    return (theta + math.pi) % (2 * math.pi) - math.pi


def _ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)
