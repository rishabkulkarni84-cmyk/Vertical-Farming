"""Budget-driven auto planner.

The customer gives only a budget. This module chooses rack size, orientation, rack count, levels and equipment
to maximise plant sites (or estimated margin when a price and yield are known) subject to HARD limits:
  * every hard layout constraint (validate_layout) passes;
  * total one-time setup cost (all required BOM lines, plus optional lines it decides to add) <= budget × (1 − reserve).
Removing racks from a valid layout keeps it valid (aisles stay clear, reachability only improves), so prefixes of a
generated layout ordered nearest-to-door are evaluated for every rack count.
"""
from __future__ import annotations

import math
from dataclasses import asdict

from . import costs as cost_svc
from .capacity import LIGHT_ALLOWANCE_M, capacity
from .layout import RackConfig, RackIn, _nearest_first, generate_layouts, validate_layout
from .spatial import SpatialContext

RACK_SIZES = [  # (name, length, depth) — common off-the-shelf shelving footprints
    ("Compact 0.6 × 0.35 m", 0.6, 0.35),
    ("Standard 0.9 × 0.45 m", 0.9, 0.45),
    ("Wide 1.2 × 0.45 m", 1.2, 0.45),
    ("Long 1.5 × 0.45 m", 1.5, 0.45),
]
BASE_CLEARANCE = 0.15
MAX_RACK_HEIGHT = 2.0
DEFAULT_CROP_GAP = 0.35  # level gap assumed when no crop is chosen (leafy greens)


def _rack_height(room_h: float, ceiling_clearance: float) -> float:
    return math.floor(min(MAX_RACK_HEIGHT, room_h - ceiling_clearance) * 20) / 20


def plan(ctx: SpatialContext, budget: float, currency: str, fx: float, electricity_rate: float | None, crop: dict | None,
         price_per_kg: float | None = None, reserve_pct: float = 5.0, walkway_m: float = 0.75,
         include_optional: bool = True) -> dict:
    spend_limit = round(budget * (1 - reserve_pct / 100), 2)
    need_gap = (crop["mature_height_m"] + LIGHT_ALLOWANCE_M) if crop and crop.get("mature_height_m") else DEFAULT_CROP_GAP
    rack_h = _rack_height(ctx.height, 0.3)
    notes, tried = [], []
    if rack_h < BASE_CLEARANCE + need_gap:
        return {"feasible": False, "reason": f"The ceiling ({ctx.height:.2f} m) is too low for even one growing level.", "tried": []}
    max_levels = max(1, min(8, int((rack_h - BASE_CLEARANCE) / need_gap + 1e-9)))

    best = None
    cheapest_cost = None
    all_cands: list[dict] = []
    for name, L, D in RACK_SIZES:
        base_cfg = RackConfig(rack_length_m=L, rack_depth_m=D, rack_height_m=rack_h, levels=max_levels, walkway_m=walkway_m)
        gen = generate_layouts(ctx, base_cfg, max_options=1)
        if not gen["feasible"]:
            tried.append({"rack": name, "max_racks": 0, "note": gen["diagnosis"][0]["reason"] if gen["diagnosis"] else "does not fit"})
            continue
        racks = _nearest_first(ctx, [RackIn(**r) for r in gen["options"][0]["racks"]])
        size_best = None
        for levels in range(1, max_levels + 1):
            cfg = RackConfig(rack_length_m=L, rack_depth_m=D, rack_height_m=rack_h, levels=levels, walkway_m=walkway_m)
            memo: dict[int, dict] = {}

            def evaluate(n: int, cfg=cfg, memo=memo) -> dict:
                if n not in memo:
                    cap = capacity(cfg, n, crop or {"name": "leafy greens (assumed)", "spacing_m": 0.2})
                    plants = cap.get("total") or 0
                    tot = cost_svc.totals(cost_svc.generate_bom(cfg, n, plants, crop, currency, fx, electricity_rate))
                    memo[n] = {"plants": plants, "setup": tot["setup_total"], "monthly": tot["monthly_total"]}
                return memo[n]

            # setup cost never decreases as racks are added -> binary-search the largest affordable count
            lo, hi, n_max = 1, len(racks), 0
            cheapest_cost = evaluate(1)["setup"] if cheapest_cost is None else min(cheapest_cost, evaluate(1)["setup"])
            while lo <= hi:
                mid = (lo + hi) // 2
                if evaluate(mid)["setup"] <= spend_limit:
                    n_max, lo = mid, mid + 1
                else:
                    hi = mid - 1
            if n_max == 0:
                continue
            # margin is ~linear in rack count, so its optimum is at an end of the affordable range
            counts = {n_max} if price_per_kg is None or not crop else {n_max, max(1, n_max - 1), 1}
            for n in sorted(counts, reverse=True):
                e = evaluate(n)
                prof = cost_svc.profitability(e["plants"], crop, price_per_kg, e["monthly"], e["setup"]) if crop else {"available": False}
                margin = prof.get("estimated_margin") if prof.get("available") else None
                cand = {"rack_name": name, "cfg": cfg, "n": n, "plants": e["plants"], "setup": e["setup"], "monthly": e["monthly"],
                        "margin": margin, "key": (e["plants"], -e["setup"]), "racks": racks[:n], "strategy": gen["options"][0]["strategy"]}
                all_cands.append(cand)
                if size_best is None or cand["key"] > size_best["key"]:
                    size_best = cand
        tried.append({"rack": name, "max_racks": len(racks), "best_racks": size_best["n"] if size_best else 0,
                      "best_levels": size_best["cfg"].levels if size_best else None, "plants": size_best["plants"] if size_best else 0,
                      "setup": size_best["setup"] if size_best else None, "margin": size_best["margin"] if size_best else None})
        if size_best and (best is None or size_best["key"] > best["key"]):
            best = size_best

    if best is None:
        return {"feasible": False, "tried": tried, "spend_limit": spend_limit,
                "reason": (f"The smallest working system costs about {cheapest_cost:,.0f} {currency}, above the usable budget of "
                           f"{spend_limit:,.0f} {currency} ({reserve_pct:g}% kept in reserve)." if cheapest_cost else
                           "No rack size fits this room with the required walkway and door clearance.")}

    # Objective: maximise estimated monthly margin when a price is known AND some option is profitable;
    # otherwise maximise plant sites. Ties go to the lower setup cost.
    profitable = [c for c in all_cands if c["margin"] is not None and c["margin"] > 0]
    objective = "plant sites"
    if profitable:
        best = max(profitable, key=lambda c: (c["margin"], c["plants"], -c["setup"]))
        objective = "estimated monthly margin"
    elif any(c["margin"] is not None for c in all_cands):
        notes.append("No option is profitable at the current price assumption, so the plan maximises plant sites instead. "
                     "Try a higher-value crop or check the price.")
    cfg, n = best["cfg"], best["n"]
    racks = sorted(best["racks"], key=lambda r: (round(r.y, 3), round(r.x, 3)))
    racks = [RackIn(f"R{i + 1}", r.x, r.y, r.w, r.d, r.rotation, None) for i, r in enumerate(racks)]
    val = validate_layout(ctx, cfg, racks)
    if not val.valid:  # prefixes of a valid layout are valid by construction; guard anyway
        raise RuntimeError(f"Budget planner produced an invalid layout: {val.violations[:2]}")
    racks = [RackIn(r.label, r.x, r.y, r.w, r.d, r.rotation, val.aisles.get(r.label, {}).get("side")) for r in racks]

    items = cost_svc.generate_bom(cfg, n, best["plants"], crop, currency, fx, electricity_rate)
    setup = cost_svc.totals(items)["setup_total"]
    added_optional = []
    if include_optional:
        for it in items:
            if it["status"] == "OPTIONAL" and setup + it["quantity"] * it["unit_price"] <= spend_limit:
                it["included"] = True
                setup += it["quantity"] * it["unit_price"]
                added_optional.append(it["name"])
    if added_optional:
        notes.append("Added within budget: " + ", ".join(added_optional) + ".")
    tot = cost_svc.totals(items)
    if tot["setup_total"] > budget + 1e-6:
        raise RuntimeError("Budget planner exceeded the budget")
    notes.append(f"Rack height set to {cfg.rack_height_m:.2f} m to leave 0.30 m for lights and air under the {ctx.height:.2f} m ceiling.")
    notes.append(f"{cfg.levels} levels chosen so each level has ≥ {need_gap:.2f} m for the crop plus light.")
    return {
        "feasible": True, "budget": budget, "currency": currency, "reserve_pct": reserve_pct, "spend_limit": spend_limit,
        "objective": objective,
        "rack_name": best["rack_name"], "config": cfg.to_dict(), "racks": [asdict(r) for r in racks], "strategy": best["strategy"],
        "plants": best["plants"], "setup_total": tot["setup_total"], "monthly_total": tot["monthly_total"],
        "remaining": round(budget - tot["setup_total"], 2), "margin": best["margin"], "items": items,
        "optional_included": added_optional, "tried": tried, "notes": notes,
    }
