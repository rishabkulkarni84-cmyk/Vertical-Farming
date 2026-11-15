"""Plant capacity from a saved configuration: plants_per_level × levels_per_rack × rack_count."""
from __future__ import annotations

import math

from .layout import RackConfig

LIGHT_ALLOWANCE_M = 0.12  # space reserved per level for light fixture + tray (assumption)


def capacity(cfg: RackConfig, rack_count: int, crop: dict | None) -> dict:
    assumptions, warnings = [], []
    spacing = cfg.plant_spacing_m
    if spacing:
        assumptions.append(f"Plant spacing {spacing:.2f} m entered by user.")
    elif crop and crop.get("spacing_m"):
        spacing = crop["spacing_m"]
        assumptions.append(f"Plant spacing {spacing:.2f} m from crop catalogue ({crop['name']}, indicative).")

    if cfg.plants_per_level:
        ppl = int(cfg.plants_per_level)
        assumptions.append(f"Plants per level fixed at {ppl} by user.")
        per_row = per_col = None
    elif spacing:
        usable_l = cfg.rack_length_m - 2 * cfg.edge_margin_m
        usable_d = cfg.rack_depth_m - 2 * cfg.edge_margin_m
        per_row = max(0, math.floor(usable_l / spacing + 1e-9))
        per_col = max(0, math.floor(usable_d / spacing + 1e-9))
        ppl = per_row * per_col
        assumptions.append(f"{cfg.edge_margin_m:.2f} m unusable margin at tray edges; grid planting {per_row} × {per_col}.")
        if ppl == 0:
            warnings.append("Rack tray is narrower than one plant spacing; no plants fit per level.")
    else:
        return {"plants_per_level": None, "levels_per_rack": cfg.levels, "rack_count": rack_count, "total": None,
                "assumptions": assumptions, "warnings": ["Select a crop or enter plant spacing to calculate capacity."],
                "basis": "plants_per_level × levels_per_rack × rack_count"}

    gap = cfg.effective_level_gap
    levels = cfg.levels
    if crop and crop.get("mature_height_m"):
        need = crop["mature_height_m"] + LIGHT_ALLOWANCE_M
        if need > gap + 1e-9:
            warnings.append(f"{crop['name']} grows to ~{crop['mature_height_m']:.2f} m; with light/tray allowance it needs "
                            f"{need:.2f} m per level but the gap is {gap:.2f} m. Reduce levels or choose a shorter crop.")
    assumptions.append(f"Vertical gap per level {gap:.2f} m ({levels} levels).")
    assumptions.append("Theoretical planting positions — not a guaranteed harvest; losses, airflow and access reduce real output.")
    return {"plants_per_level": ppl, "levels_per_rack": levels, "rack_count": rack_count,
            "total": ppl * levels * rack_count, "per_row": per_row, "per_col": per_col, "spacing_m": spacing,
            "level_gap_m": round(gap, 3), "assumptions": assumptions, "warnings": warnings,
            "basis": "plants_per_level × levels_per_rack × rack_count"}
