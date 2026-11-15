"""Spatial context: room boundary + obstacles converted into blocking / access / soft zones."""
from __future__ import annotations

from dataclasses import dataclass, field

from .geometry import Rect, door_access_zone

# How each obstacle kind affects rack placement.
BLOCKING_KINDS = {"PILLAR", "FURNITURE", "EQUIPMENT", "FIXED", "RESTRICTED"}
SOFT_KINDS = {"WINDOW"}  # wall feature: never blocks floor, produces a warning only
ACCESS_KINDS = {"DOOR"}  # door opening + swing/access zone: no racks, but walkable

OBSTACLE_KINDS = BLOCKING_KINDS | SOFT_KINDS | ACCESS_KINDS


@dataclass
class Zone:
    rect: Rect
    kind: str
    label: str
    obstacle_id: int | None = None
    confirmed: bool = True


@dataclass
class SpatialContext:
    room: Rect
    height: float
    blocking: list[Zone] = field(default_factory=list)
    access: list[Zone] = field(default_factory=list)
    soft: list[Zone] = field(default_factory=list)

    @property
    def has_door(self) -> bool:
        return bool(self.access)


def build_context(length_m: float, width_m: float, height_m: float, obstacles: list) -> SpatialContext:
    """`obstacles` are ORM rows or dicts with kind/x/y/w/d/clearance_m/label/id/confirmed."""
    room = Rect(0.0, 0.0, length_m, width_m)
    ctx = SpatialContext(room=room, height=height_m)
    for o in obstacles:
        def g(k, default=None, o=o):
            return o.get(k, default) if isinstance(o, dict) else getattr(o, k, default)
        kind = g("kind")
        r = Rect(g("x"), g("y"), g("w"), g("d")).clip(room)
        if r is None:
            continue
        label = g("label") or kind.title()
        oid, confirmed = g("id"), g("confirmed", True)
        if kind in ACCESS_KINDS:
            ctx.access.append(Zone(door_access_zone(r, float(g("clearance_m", 0.0) or 0.0), room), kind, label, oid, confirmed))
        elif kind in SOFT_KINDS:
            ctx.soft.append(Zone(r, kind, label, oid, confirmed))
        else:
            ctx.blocking.append(Zone(r, kind, label, oid, confirmed))
    return ctx
