"""Planning grid.

columns = floor(L / G), rows = floor(W / G), full_cells = rows * columns.
Cells are indexed (row, col) with row along +y and col along +x from the origin (top-left corner).
Partial cells at the far edges (x >= columns*G or y >= rows*G) are reported as remainder strips,
never counted as full cells. Cell state is conservative: any overlap with a zone marks the cell.
"""
from __future__ import annotations

import math

from .geometry import Rect
from .spatial import SpatialContext

STATES = ["FREE", "OBSTACLE", "DOOR_CLEARANCE", "WALKWAY", "RACK", "RESTRICTED", "UNCERTAIN"]
# precedence when several zones touch a cell
PRECEDENCE = {"RACK": 6, "OBSTACLE": 5, "RESTRICTED": 4, "UNCERTAIN": 3, "DOOR_CLEARANCE": 2, "WALKWAY": 1, "FREE": 0}
MAX_CELLS = 40_000


def grid_dimensions(length: float, width: float, cell: float) -> dict:
    if cell <= 0:
        raise ValueError("Grid cell size must be positive")
    if length <= 0 or width <= 0:
        raise ValueError("Room dimensions must be positive")
    # small epsilon so 3.048 / 0.3048 == 10 despite floating-point error
    cols = math.floor(length / cell + 1e-9)
    rows = math.floor(width / cell + 1e-9)
    return {
        "columns": cols,
        "rows": rows,
        "full_cells": cols * rows,
        "cell_m": cell,
        "remainder_x_m": round(max(0.0, length - cols * cell), 6),
        "remainder_y_m": round(max(0.0, width - rows * cell), 6),
    }


def cell_rect(row: int, col: int, cell: float) -> Rect:
    return Rect(col * cell, row * cell, cell, cell)


def grid_to_physical(row: int, col: int, cell: float) -> tuple[float, float]:
    """Centre of a cell in metres."""
    return ((col + 0.5) * cell, (row + 0.5) * cell)


def physical_to_grid(x: float, y: float, cell: float) -> tuple[int, int]:
    return (math.floor(y / cell), math.floor(x / cell))


def compute_cells(ctx: SpatialContext, cell: float, racks: list[Rect] | None = None,
                  walkways: list[Rect] | None = None) -> dict:
    dims = grid_dimensions(ctx.room.w, ctx.room.d, cell)
    if dims["full_cells"] > MAX_CELLS:
        raise ValueError(f"Grid too fine: {dims['full_cells']} cells (max {MAX_CELLS}). Increase the cell size.")
    rows, cols = dims["rows"], dims["columns"]
    states = [["FREE"] * cols for _ in range(rows)]

    layers: list[tuple[Rect, str]] = []
    for z in ctx.blocking:
        st = "UNCERTAIN" if not z.confirmed else ("RESTRICTED" if z.kind == "RESTRICTED" else "OBSTACLE")
        layers.append((z.rect, st))
    for z in ctx.access:
        layers.append((z.rect, "DOOR_CLEARANCE" if z.confirmed else "UNCERTAIN"))
    for r in walkways or []:
        layers.append((r, "WALKWAY"))
    for r in racks or []:
        layers.append((r, "RACK"))

    for rect, st in layers:
        c0, c1 = max(0, math.floor(rect.x / cell)), min(cols - 1, math.ceil(rect.x2 / cell) - 1)
        r0, r1 = max(0, math.floor(rect.y / cell)), min(rows - 1, math.ceil(rect.y2 / cell) - 1)
        for r in range(r0, r1 + 1):
            for c in range(c0, c1 + 1):
                if cell_rect(r, c, cell).overlap_area(rect) > 1e-9 and PRECEDENCE[st] > PRECEDENCE[states[r][c]]:
                    states[r][c] = st

    counts = {s: 0 for s in STATES}
    for row in states:
        for s in row:
            counts[s] += 1
    return {**dims, "states": states, "counts": counts,
            "origin": "top-left corner of room; +x along length (columns), +y along width (rows)"}
