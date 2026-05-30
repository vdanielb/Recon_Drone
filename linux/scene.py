"""Rule-based scene classification for DARKMAP-Q.

This is intentionally simple: it turns one ultrasonic sweep into a coarse label
describing the local environment. It is NOT machine learning, but it
demonstrates onboard ("edge") decision logic and gives the operator/judges a
human-readable read of what the rover "sees".

Input: a sweep, i.e. a list of (relative_angle_deg, distance_cm) tuples. A
distance of -1 (or negative) means "no echo / out of range" and is treated as
open space.

WALLFOLLOW mode adds two extra labels:
  WF_CORNER    - wall detected ahead during wall-following
  WF_WALL_NEAR - rover is within TARGET_WALL_CM of the right wall
"""

from __future__ import annotations

from typing import List, Sequence, Tuple

# Thresholds in centimeters.
NEAR_CM = 25.0     # an obstacle this close counts as "blocked"
OPEN_CM = 80.0     # beyond this we consider the direction clearly open
FAR = 1e9          # stand-in distance for "no echo" (open)


def _bucket(scan: Sequence[Tuple[int, float]]):
    """Split a sweep into (left, front, right) min-distances."""
    left, front, right = [], [], []
    for angle, dist in scan:
        d = dist if (dist is not None and dist >= 0) else FAR
        if angle <= -35:
            left.append(d)
        elif angle >= 35:
            right.append(d)
        else:
            front.append(d)
    return (
        min(left) if left else FAR,
        min(front) if front else FAR,
        min(right) if right else FAR,
    )


def classify(scan: Sequence[Tuple[int, float]], mode: str = "") -> str:
    """Return a coarse scene label for a single sweep.

    When *mode* is ``"WALLFOLLOW"`` two additional labels are possible:
    ``WF_CORNER`` (wall ahead during wall-following) and ``WF_WALL_NEAR``
    (right wall inside the follow band).
    """
    if not scan:
        return "UNKNOWN"

    left, front, right = _bucket(scan)

    front_blocked = front < NEAR_CM
    left_blocked = left < NEAR_CM
    right_blocked = right < NEAR_CM

    if mode.upper() == "WALLFOLLOW":
        if front_blocked:
            return "WF_CORNER"
        if right_blocked:
            return "WF_WALL_NEAR"

    if front_blocked and left_blocked and right_blocked:
        return "DEAD_END"
    if front_blocked:
        return "WALL_AHEAD"
    if left_blocked and not right_blocked:
        return "LEFT_BLOCKED"
    if right_blocked and not left_blocked:
        return "RIGHT_BLOCKED"
    # Open front but walls on both sides at medium range => corridor.
    if left < OPEN_CM and right < OPEN_CM and front >= OPEN_CM:
        return "CORRIDOR"
    if front >= OPEN_CM and left >= OPEN_CM and right >= OPEN_CM:
        return "OPEN_AREA"
    return "OPEN_AREA"


def risk_level(distance_cm: float) -> str:
    """Local risk tag for the closest obstacle (defense-pitch flavor)."""
    if distance_cm is None or distance_cm < 0:
        return "CLEAR"
    if distance_cm < 15:
        return "HIGH"
    if distance_cm <= 35:
        return "MEDIUM"
    return "CLEAR"
