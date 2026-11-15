"""Axis-aligned rectangle geometry used by the grid and the layout engine (metres)."""
from __future__ import annotations

from dataclasses import dataclass

EPS = 1e-6


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    w: float
    d: float

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.d

    @property
    def area(self) -> float:
        return max(0.0, self.w) * max(0.0, self.d)

    def intersects(self, other: Rect, tol: float = EPS) -> bool:
        """True when the interiors overlap (touching edges do not count)."""
        return (self.x < other.x2 - tol and other.x < self.x2 - tol and
                self.y < other.y2 - tol and other.y < self.y2 - tol)

    def overlap_area(self, other: Rect) -> float:
        ox = min(self.x2, other.x2) - max(self.x, other.x)
        oy = min(self.y2, other.y2) - max(self.y, other.y)
        return ox * oy if ox > 0 and oy > 0 else 0.0

    def expand(self, m: float) -> Rect:
        return Rect(self.x - m, self.y - m, self.w + 2 * m, self.d + 2 * m)

    def inside(self, outer: Rect, tol: float = EPS) -> bool:
        return (self.x >= outer.x - tol and self.y >= outer.y - tol and
                self.x2 <= outer.x2 + tol and self.y2 <= outer.y2 + tol)

    def clip(self, outer: Rect) -> "Rect | None":
        x, y = max(self.x, outer.x), max(self.y, outer.y)
        x2, y2 = min(self.x2, outer.x2), min(self.y2, outer.y2)
        if x2 - x <= EPS or y2 - y <= EPS:
            return None
        return Rect(x, y, x2 - x, y2 - y)

    def gap_to(self, other: Rect) -> float:
        """Minimum Euclidean edge-to-edge distance (0 if overlapping/touching)."""
        dx = max(0.0, max(other.x - self.x2, self.x - other.x2))
        dy = max(0.0, max(other.y - self.y2, self.y - other.y2))
        return (dx * dx + dy * dy) ** 0.5

    def to_dict(self) -> dict:
        return {"x": round(self.x, 4), "y": round(self.y, 4), "w": round(self.w, 4), "d": round(self.d, 4)}


def nearest_wall(r: Rect, room: Rect) -> str:
    """Which wall the rectangle is closest to: N (y=0), S (y=W), W (x=0), E (x=L)."""
    cx, cy = r.x + r.w / 2, r.y + r.d / 2
    dists = {"N": cy - room.y, "S": room.y2 - cy, "W": cx - room.x, "E": room.x2 - cx}
    return min(dists, key=dists.get)


def door_access_zone(door: Rect, clearance: float, room: Rect) -> Rect:
    """Door opening rectangle extended `clearance` metres into the room (swing / access zone)."""
    wall = nearest_wall(door, room)
    if wall == "N":
        z = Rect(door.x, door.y, door.w, door.d + clearance)
    elif wall == "S":
        z = Rect(door.x, door.y - clearance, door.w, door.d + clearance)
    elif wall == "W":
        z = Rect(door.x, door.y, door.w + clearance, door.d)
    else:
        z = Rect(door.x - clearance, door.y, door.w + clearance, door.d)
    return z.clip(room) or door


def front_aisle(rack: Rect, side: str, depth: float) -> Rect:
    if side == "N":
        return Rect(rack.x, rack.y - depth, rack.w, depth)
    if side == "S":
        return Rect(rack.x, rack.y2, rack.w, depth)
    if side == "W":
        return Rect(rack.x - depth, rack.y, depth, rack.d)
    return Rect(rack.x2, rack.y, depth, rack.d)


def long_sides(rack: Rect) -> list[str]:
    """The two sides of a rack along its long axis (where plants are accessed)."""
    if rack.w >= rack.d:
        return ["S", "N"]
    return ["E", "W"]


class SpatialHash:
    """Uniform-grid index over rectangles: query() returns ids whose cells overlap a rectangle.
    Turns all-pairs rack checks from O(n²) into ~O(n) for typical layouts."""

    def __init__(self, rects: list[Rect], cell: float):
        self.cell = max(cell, 0.05)
        self.rects = rects
        self.buckets: dict[tuple[int, int], list[int]] = {}
        for i, r in enumerate(rects):
            for key in self._keys(r):
                self.buckets.setdefault(key, []).append(i)

    def _keys(self, r: Rect):
        c = self.cell
        for gx in range(int(r.x // c), int(r.x2 // c) + 1):
            for gy in range(int(r.y // c), int(r.y2 // c) + 1):
                yield gx, gy

    def query(self, r: Rect, pad: float = 0.0) -> set[int]:
        q = r.expand(pad) if pad else r
        out: set[int] = set()
        for key in self._keys(q):
            out.update(self.buckets.get(key, ()))
        return out
