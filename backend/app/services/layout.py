"""Deterministic, constraint-checked rack layout engine.

Hard constraints (never traded against score):
  OUT_OF_BOUNDS, HEIGHT, OBSTACLE_OVERLAP, OBSTACLE_CLEARANCE, DOOR_ZONE, RACK_OVERLAP,
  RACK_CLEARANCE, NO_ACCESS_AISLE, UNREACHABLE.
The generator proposes wall-aligned row patterns; every proposal is re-checked by the independent
validator, and only valid layouts are ranked.
"""
from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .geometry import EPS, Rect, SpatialHash, front_aisle, long_sides
from .spatial import SpatialContext


@dataclass
class RackConfig:
    rack_length_m: float = 1.2
    rack_depth_m: float = 0.45
    rack_height_m: float = 1.8
    levels: int = 4
    level_gap_m: float | None = None  # None -> (height - base) / levels
    base_clearance_m: float = 0.15  # floor to first tray
    plants_per_level: int | None = None  # None -> derived from crop spacing
    plant_spacing_m: float | None = None  # None -> crop default
    edge_margin_m: float = 0.05
    orientation: str = "ANY"  # ANY | X | Y
    max_racks: int | None = None
    walkway_m: float = 0.75
    obstacle_clearance_m: float = 0.15
    rack_gap_m: float = 0.05
    wall_clearance_m: float = 0.0
    ceiling_clearance_m: float = 0.3  # space above the rack for lights/air
    min_passage_m: float = 0.6  # narrowest route from the door a person can walk

    @classmethod
    def from_dict(cls, d: dict | None) -> "RackConfig":
        d = d or {}
        known = {k: v for k, v in d.items() if k in cls.__dataclass_fields__}
        cfg = cls(**known)
        cfg.validate()
        return cfg

    def validate(self) -> None:
        errs = []
        for f in ("rack_length_m", "rack_depth_m", "rack_height_m", "walkway_m"):
            if getattr(self, f) is None or getattr(self, f) <= 0:
                errs.append(f"{f} must be > 0")
        for f in ("obstacle_clearance_m", "rack_gap_m", "wall_clearance_m", "ceiling_clearance_m", "edge_margin_m"):
            if getattr(self, f) < 0:
                errs.append(f"{f} must be ≥ 0")
        if not (1 <= int(self.levels) <= 12):
            errs.append("levels must be between 1 and 12")
        if self.orientation not in ("ANY", "X", "Y"):
            errs.append("orientation must be ANY, X or Y")
        if self.max_racks is not None and self.max_racks < 1:
            errs.append("max_racks must be ≥ 1")
        if self.plant_spacing_m is not None and self.plant_spacing_m <= 0:
            errs.append("plant_spacing_m must be > 0")
        if self.rack_depth_m > self.rack_length_m:
            errs.append("rack_depth_m must not exceed rack_length_m (length is the long axis)")
        if self.level_gap_m is not None and self.base_clearance_m + self.levels * self.level_gap_m > self.rack_height_m + EPS:
            errs.append("levels × level gap plus base clearance exceeds rack height")
        if errs:
            raise ValueError("; ".join(errs))

    @property
    def effective_level_gap(self) -> float:
        if self.level_gap_m:
            return self.level_gap_m
        return (self.rack_height_m - self.base_clearance_m) / self.levels

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RackIn:
    label: str
    x: float
    y: float
    w: float
    d: float
    rotation: int = 0
    access_side: str | None = None

    @property
    def rect(self) -> Rect:
        return Rect(self.x, self.y, self.w, self.d)


@dataclass
class ValidationResult:
    valid: bool
    violations: list[dict] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)
    aisles: dict[str, dict] = field(default_factory=dict)  # label -> {side, rect}


# ---------------------------------------------------------------- validation

def _raster_res(room: Rect) -> float:
    return max(0.05, max(room.w, room.d) / 400)


def _mark(mask: np.ndarray, r: Rect, res: float, value: int = 0) -> None:
    c0, c1 = max(0, math.floor(r.x / res + EPS)), min(mask.shape[1], math.ceil(r.x2 / res - EPS))
    r0, r1 = max(0, math.floor(r.y / res + EPS)), min(mask.shape[0], math.ceil(r.y2 / res - EPS))
    if c1 > c0 and r1 > r0:
        mask[r0:r1, c0:c1] = value


def reachable_mask(ctx: SpatialContext, racks: list[Rect], passage: float) -> tuple[np.ndarray | None, float]:
    """Cells a person (of width `passage`) can reach from any door access zone."""
    if not ctx.has_door:
        return None, 0.0
    res = _raster_res(ctx.room)
    nx, ny = max(1, math.ceil(ctx.room.w / res - EPS)), max(1, math.ceil(ctx.room.d / res - EPS))
    free = np.ones((ny, nx), np.uint8)
    for z in ctx.blocking:
        _mark(free, z.rect, res)
    for r in racks:
        _mark(free, r, res)
    k = max(1, int(round(passage / res)))
    if k % 2 == 0:
        k -= 1
    k = max(1, k)
    eroded = cv2.erode(free, np.ones((k, k), np.uint8), borderType=cv2.BORDER_CONSTANT, borderValue=0) if k > 1 else free
    _, labels = cv2.connectedComponents(eroded, connectivity=4)
    seeds = set()
    for z in ctx.access:
        s = _slices(eroded.shape, z.rect, res)
        if s:
            seeds.update(int(v) for v in np.unique(labels[s][eroded[s] == 1]))
    seeds.discard(0)
    reach = np.isin(labels, list(seeds)) if seeds else np.zeros_like(eroded, bool)
    # dilate back so the reachable region covers the full corridor width
    reach = cv2.dilate(reach.astype(np.uint8), np.ones((k, k), np.uint8)) & free
    return reach.astype(bool), res


def _slices(shape: tuple[int, int], r: Rect, res: float) -> tuple[slice, slice] | None:
    c0, c1 = max(0, math.floor(r.x / res + EPS)), min(shape[1], math.ceil(r.x2 / res - EPS))
    r0, r1 = max(0, math.floor(r.y / res + EPS)), min(shape[0], math.ceil(r.y2 / res - EPS))
    return (slice(r0, r1), slice(c0, c1)) if c1 > c0 and r1 > r0 else None


def _rect_touches(mask: np.ndarray, r: Rect, res: float) -> bool:
    s = _slices(mask.shape, r, res)
    return bool(s and mask[s].any())


def validate_layout(ctx: SpatialContext, cfg: RackConfig, racks: list[RackIn], check_reach: bool = True) -> ValidationResult:
    v: list[dict] = []
    warn: list[dict] = []
    aisles: dict[str, dict] = {}
    room = ctx.room
    inner = Rect(room.x + cfg.wall_clearance_m, room.y + cfg.wall_clearance_m,
                 room.w - 2 * cfg.wall_clearance_m, room.d - 2 * cfg.wall_clearance_m)

    if cfg.rack_height_m + cfg.ceiling_clearance_m > ctx.height + EPS:
        v.append({"code": "HEIGHT", "rack": None,
                  "message": f"Rack height {cfg.rack_height_m:.2f} m + {cfg.ceiling_clearance_m:.2f} m ceiling clearance "
                             f"exceeds room height {ctx.height:.2f} m."})

    labels = [r.label for r in racks]
    if len(set(labels)) != len(labels):
        v.append({"code": "DUPLICATE_LABEL", "rack": None, "message": "Rack labels must be unique."})

    for rk in racks:
        r = rk.rect
        expect = {(round(cfg.rack_length_m, 4), round(cfg.rack_depth_m, 4)), (round(cfg.rack_depth_m, 4), round(cfg.rack_length_m, 4))}
        if (round(r.w, 4), round(r.d, 4)) not in expect:
            v.append({"code": "FOOTPRINT_MISMATCH", "rack": rk.label,
                      "message": f"{rk.label} footprint {r.w:.2f}×{r.d:.2f} m does not match configured rack "
                                 f"{cfg.rack_length_m:.2f}×{cfg.rack_depth_m:.2f} m."})
        if not r.inside(inner):
            v.append({"code": "OUT_OF_BOUNDS", "rack": rk.label,
                      "message": f"{rk.label} extends outside the room" +
                                 (f" (wall clearance {cfg.wall_clearance_m:.2f} m)." if cfg.wall_clearance_m else ".")})
        for z in ctx.blocking:
            if r.intersects(z.rect):
                v.append({"code": "OBSTACLE_OVERLAP", "rack": rk.label, "message": f"{rk.label} overlaps {z.label}."})
            elif cfg.obstacle_clearance_m > 0 and r.gap_to(z.rect) < cfg.obstacle_clearance_m - EPS:
                v.append({"code": "OBSTACLE_CLEARANCE", "rack": rk.label,
                          "message": f"{rk.label} is {r.gap_to(z.rect):.2f} m from {z.label}; "
                                     f"minimum maintenance clearance is {cfg.obstacle_clearance_m:.2f} m."})
        for z in ctx.access:
            if r.intersects(z.rect):
                v.append({"code": "DOOR_ZONE", "rack": rk.label, "message": f"{rk.label} blocks the {z.label} access zone."})
        for z in ctx.soft:
            if r.expand(0.3).intersects(z.rect):
                warn.append({"code": "NEAR_WINDOW", "rack": rk.label,
                             "message": f"{rk.label} is close to {z.label}; it may shade or block the window."})

    rects = [rk.rect for rk in racks]
    index = SpatialHash(rects, max(cfg.rack_length_m, cfg.walkway_m))
    for i, a in enumerate(racks):
        ra = rects[i]
        for j in sorted(index.query(ra, cfg.rack_gap_m)):
            if j <= i:
                continue
            b, rb = racks[j], rects[j]
            if ra.intersects(rb):
                v.append({"code": "RACK_OVERLAP", "rack": a.label, "message": f"{a.label} overlaps {b.label}."})
            elif ra.gap_to(rb) < cfg.rack_gap_m - EPS:
                v.append({"code": "RACK_CLEARANCE", "rack": a.label,
                          "message": f"{a.label} and {b.label} are {ra.gap_to(rb):.2f} m apart; minimum is {cfg.rack_gap_m:.2f} m."})

    # every rack needs a clear aisle (walkway width) along at least one long side
    clear: dict[str, list[tuple[str, Rect]]] = {}
    for i, rk in enumerate(racks):
        r = rects[i]
        sides = long_sides(r)
        if rk.access_side in sides:
            sides = [rk.access_side] + [s for s in sides if s != rk.access_side]
        ok = []
        for s in sides:
            a = front_aisle(r, s, cfg.walkway_m)
            if not a.inside(room) or any(a.intersects(z.rect) for z in ctx.blocking):
                continue
            if any(j != i and a.intersects(rects[j]) for j in index.query(a)):
                continue
            ok.append((s, a))
        if not ok:
            v.append({"code": "NO_ACCESS_AISLE", "rack": rk.label,
                      "message": f"{rk.label} has no clear {cfg.walkway_m:.2f} m walkway along either long side."})
        else:
            clear[rk.label] = ok
            aisles[rk.label] = {"side": ok[0][0], "rect": ok[0][1].to_dict()}

    if check_reach and racks:
        reach, res = reachable_mask(ctx, rects, cfg.min_passage_m)
        if reach is None:
            warn.append({"code": "NO_DOOR", "rack": None,
                         "message": "No door is marked, so the walking route to each rack could not be verified."})
        else:
            # a rack is accessible if ANY of its clear walkways can be reached from the door
            for rk in racks:
                options = clear.get(rk.label)
                if not options:
                    continue
                reachable = next(((s, a) for s, a in options if _rect_touches(reach, a, res)), None)
                if reachable:
                    aisles[rk.label] = {"side": reachable[0], "rect": reachable[1].to_dict()}
                else:
                    v.append({"code": "UNREACHABLE", "rack": rk.label,
                              "message": f"{rk.label}'s walkway cannot be reached from the door through a "
                                         f"{cfg.min_passage_m:.2f} m wide passage."})

    return ValidationResult(valid=not v, violations=v, warnings=warn, aisles=aisles)


# ---------------------------------------------------------------- generation

def _row_pattern(V: float, D: float, walk: float, wc: float, gap: float, b2b: bool, aisle_first: bool) -> list[tuple[float, int]]:
    """Positions (v, facing) of rack rows across the room. facing +1 = aisle at larger v."""
    rows: list[tuple[float, int]] = []
    limit = V - wc
    if aisle_first:
        a_end = walk
        state = "after_aisle"
    else:
        if wc + D + walk > V + EPS:
            return rows
        rows.append((wc, +1))
        a_end = wc + D + walk
        state = "after_aisle"
    while True:
        if state == "after_aisle":
            if a_end + D > limit + EPS:
                break
            rows.append((a_end, -1))
            q = a_end
            state = "after_neg"
        else:  # after a row whose aisle is behind it (-1)
            if b2b:
                p = q + D + gap
                if p + D + walk > V + EPS:
                    break
                rows.append((p, +1))
                a_end = p + D + walk
                state = "after_aisle"
            else:
                a_end = q + D + walk
                state = "after_aisle"
    return rows


def _place_row(ctx: SpatialContext, cfg: RackConfig, axis: str, v: float, facing: int, U: float, shift: float,
               stats: dict) -> list[tuple[Rect, str]]:
    L, D, wc, step = cfg.rack_length_m, cfg.rack_depth_m, cfg.wall_clearance_m, 0.05
    out = []
    u = wc
    side = ("S" if facing > 0 else "N") if axis == "X" else ("E" if facing > 0 else "W")
    while u + L <= U - wc + EPS:
        if axis == "X":
            r = Rect(u, v + shift, L, D)
        else:
            r = Rect(v + shift, u, D, L)
        aisle = front_aisle(r, side, cfg.walkway_m)
        reason = None
        if any(r.intersects(z.rect) or r.gap_to(z.rect) < cfg.obstacle_clearance_m - EPS for z in ctx.blocking):
            reason = "obstacle"
        elif any(r.intersects(z.rect) for z in ctx.access):
            reason = "door_zone"
        elif any(aisle.intersects(z.rect) for z in ctx.blocking):
            reason = "aisle_blocked"
        if reason:
            stats[reason] = stats.get(reason, 0) + 1
            u += step
            continue
        out.append((r, side))
        u += L + cfg.rack_gap_m
    return out


def _metrics(ctx: SpatialContext, racks: list[RackIn], aisles: dict) -> dict:
    room_area = ctx.room.area
    footprint = sum(r.rect.area for r in racks)
    res = _raster_res(ctx.room)
    nx, ny = max(1, math.ceil(ctx.room.w / res - EPS)), max(1, math.ceil(ctx.room.d / res - EPS))
    blocked = np.zeros((ny, nx), np.uint8)
    reserved = np.zeros((ny, nx), np.uint8)
    for z in ctx.blocking:
        _mark(blocked, z.rect, res, 1)
    for z in ctx.access:
        _mark(reserved, z.rect, res, 1)
    for a in aisles.values():
        _mark(reserved, Rect(**a["rect"]), res, 1)
    cell_a = (ctx.room.w / nx) * (ctx.room.d / ny)
    blocked_a = float(blocked.sum()) * cell_a
    reserved_a = float(((reserved == 1) & (blocked == 0)).sum()) * cell_a
    return {
        "rack_count": len(racks),
        "rack_footprint_m2": round(footprint, 3),
        "room_area_m2": round(room_area, 3),
        "blocked_area_m2": round(blocked_a, 3),
        "reserved_area_m2": round(reserved_a, 3),
        "free_area_m2": round(max(0.0, room_area - blocked_a - reserved_a - footprint), 3),
        "utilization_pct": round(100 * footprint / room_area, 1) if room_area else 0.0,
        "utilization_definition": "total rack footprint ÷ room floor area × 100",
    }


def _label(racks: list[tuple[Rect, str]]) -> list[RackIn]:
    racks = sorted(racks, key=lambda t: (round(t[0].y, 3), round(t[0].x, 3)))
    return [RackIn(f"R{i + 1}", r.x, r.y, r.w, r.d, 0 if r.w >= r.d else 90, side) for i, (r, side) in enumerate(racks)]


def generate_layouts(ctx: SpatialContext, cfg: RackConfig, max_options: int = 4) -> dict:
    stats: dict[str, int] = {}
    axes = ["X", "Y"] if cfg.orientation == "ANY" else [cfg.orientation]
    candidates: list[tuple[str, list[RackIn]]] = []
    for axis in axes:
        U, V = (ctx.room.w, ctx.room.d) if axis == "X" else (ctx.room.d, ctx.room.w)
        for b2b in (True, False):
            for aisle_first in (False, True):
                rows = _row_pattern(V, cfg.rack_depth_m, cfg.walkway_m, cfg.wall_clearance_m, cfg.rack_gap_m, b2b, aisle_first)
                if not rows:
                    continue
                for align in ("wall", "centre"):
                    shift = 0.0
                    if align == "centre":
                        last_v, last_f = rows[-1]
                        used_end = last_v + cfg.rack_depth_m + (cfg.walkway_m if last_f > 0 else 0)
                        shift = max(0.0, (V - cfg.wall_clearance_m - used_end) / 2)
                        if shift < 0.05:
                            continue
                    placed: list[tuple[Rect, str]] = []
                    for v, f in rows:
                        placed += _place_row(ctx, cfg, axis, v, f, U, shift, stats)
                    if not placed:
                        continue
                    name = (f"{'Rows along length' if axis == 'X' else 'Rows along width'}"
                            f"{', back-to-back pairs' if b2b else ', single-sided rows'}"
                            f"{', aisle at wall' if aisle_first else ''}{', centred' if align == 'centre' else ''}")
                    candidates.append((name, _label(placed)))

    options: list[dict] = []
    seen: set = set()
    for name, racks in candidates:
        # prune until valid: drop racks that break hard constraints (e.g. unreachable behind an obstacle)
        for _ in range(len(racks) + 1):
            res = validate_layout(ctx, cfg, racks)
            if res.valid or not racks:
                break
            bad = {x["rack"] for x in res.violations if x["rack"]}
            if not bad:
                break
            stats["pruned_" + res.violations[0]["code"].lower()] = stats.get("pruned_" + res.violations[0]["code"].lower(), 0) + len(bad)
            racks = [r for r in racks if r.label not in bad]
        if not racks or not res.valid:
            continue
        if cfg.max_racks and len(racks) > cfg.max_racks:
            racks = _nearest_first(ctx, racks)[: cfg.max_racks]
            res = validate_layout(ctx, cfg, racks)
            if not res.valid:
                continue
        racks = [RackIn(f"R{i + 1}", r.x, r.y, r.w, r.d, r.rotation, res.aisles.get(r.label, {}).get("side"))
                 for i, r in enumerate(sorted(racks, key=lambda r: (round(r.y, 3), round(r.x, 3))))]
        res = validate_layout(ctx, cfg, racks)
        sig = tuple(sorted((round(r.x, 2), round(r.y, 2), r.rotation) for r in racks))
        if sig in seen or not res.valid:
            continue
        seen.add(sig)
        options.append({"strategy": name, "racks": [asdict(r) for r in racks], "validation": _vr(res),
                        "metrics": _metrics(ctx, racks, res.aisles)})

    if options:
        best = max(o["metrics"]["rack_count"] for o in options)
        for o in options:
            m = o["metrics"]
            cap = m["rack_count"] / best
            access = _open_sides(ctx, cfg, o)
            compact = min(1.0, m["utilization_pct"] / 40)
            o["score_breakdown"] = {"capacity": round(cap, 3), "accessibility": round(access, 3), "compactness": round(compact, 3)}
            o["score"] = round(100 * (0.6 * cap + 0.25 * access + 0.15 * compact), 1)
        options.sort(key=lambda o: (-o["score"], o["strategy"]))
    return {
        "options": options[:max_options],
        "feasible": bool(options),
        "rejections": stats,
        "diagnosis": [] if options else diagnose(ctx, cfg, stats),
        "scoring": "score = 100 × (0.6·capacity + 0.25·accessibility + 0.15·compactness); capacity = racks ÷ best option's racks; "
                   "accessibility = share of rack long sides facing a walkway; compactness = min(1, utilization ÷ 40%). "
                   "Only layouts that pass every hard constraint are scored.",
    }


def _open_sides(ctx: SpatialContext, cfg: RackConfig, option: dict) -> float:
    rects = [Rect(r["x"], r["y"], r["w"], r["d"]) for r in option["racks"]]
    index = SpatialHash(rects, max(cfg.rack_length_m, cfg.walkway_m))
    total, opened = 0, 0
    for i, r in enumerate(rects):
        for s in long_sides(r):
            total += 1
            a = front_aisle(r, s, cfg.walkway_m)
            if a.inside(ctx.room) and not any(a.intersects(z.rect) for z in ctx.blocking) and \
                    not any(j != i and a.intersects(rects[j]) for j in index.query(a)):
                opened += 1
    return opened / total if total else 0.0


def _nearest_first(ctx: SpatialContext, racks: list[RackIn]) -> list[RackIn]:
    if not ctx.access:
        return racks
    door = ctx.access[0].rect
    dx, dy = door.x + door.w / 2, door.y + door.d / 2
    return sorted(racks, key=lambda r: (r.x + r.w / 2 - dx) ** 2 + (r.y + r.d / 2 - dy) ** 2)


def _vr(res: ValidationResult) -> dict:
    return {"valid": res.valid, "violations": res.violations, "warnings": res.warnings, "aisles": res.aisles}


def diagnose(ctx: SpatialContext, cfg: RackConfig, stats: dict) -> list[dict]:
    """Explain why no layout fits and suggest concrete, feasible adjustments."""
    out = []
    room = ctx.room
    if cfg.rack_height_m + cfg.ceiling_clearance_m > ctx.height + EPS:
        max_h = ctx.height - cfg.ceiling_clearance_m
        out.append({"reason": f"Racks ({cfg.rack_height_m:.2f} m) plus ceiling clearance do not fit the {ctx.height:.2f} m ceiling.",
                    "suggestion": f"Use racks no taller than {max_h:.2f} m." if max_h > 0.3 else "The ceiling is too low for racks."})
    longest = max(room.w, room.d) - 2 * cfg.wall_clearance_m
    if cfg.rack_length_m > longest + EPS:
        out.append({"reason": f"Rack length {cfg.rack_length_m:.2f} m exceeds the longest usable wall ({longest:.2f} m).",
                    "suggestion": f"Choose racks of at most {longest:.2f} m length."})
    need = cfg.rack_depth_m + cfg.walkway_m + cfg.wall_clearance_m
    widest = max(room.w, room.d)
    if need > widest + EPS:
        out.append({"reason": f"One rack ({cfg.rack_depth_m:.2f} m deep) plus its {cfg.walkway_m:.2f} m walkway needs {need:.2f} m.",
                    "suggestion": f"Reduce walkway to {max(0.45, widest - cfg.rack_depth_m - cfg.wall_clearance_m):.2f} m or use shallower racks."})
    if stats.get("obstacle") or stats.get("door_zone") or stats.get("aisle_blocked"):
        out.append({"reason": f"Candidate positions were rejected: {stats.get('obstacle', 0)} by obstacles/clearance, "
                              f"{stats.get('door_zone', 0)} by door access zones, {stats.get('aisle_blocked', 0)} by blocked walkways.",
                    "suggestion": "Move or remove obstacles, reduce obstacle clearance, or try shorter racks to fit between them."})
    if any(k.startswith("pruned_unreachable") for k in stats):
        out.append({"reason": "Some racks could be placed but their walkways are not reachable from the door.",
                    "suggestion": "Leave a continuous passage from the door, or lower the minimum passage width if appropriate."})
    if not out:
        out.append({"reason": "No combination of rows satisfied all hard constraints.",
                    "suggestion": "Try a smaller rack, a narrower walkway, or a different orientation."})
    return out
