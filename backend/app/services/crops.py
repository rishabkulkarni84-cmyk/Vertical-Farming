"""Transparent rule-based crop suitability engine (no trained model is deployed).

Pipeline: hard filters → weighted factor scores (0–1) → total score 0–100 with per-factor explanations.
Missing inputs score a neutral 0.5 and are listed under `missing_inputs`.
"""
from __future__ import annotations

import json
from pathlib import Path

from .capacity import LIGHT_ALLOWANCE_M, capacity
from .layout import RackConfig

CATALOGUE_PATH = Path(__file__).resolve().parent.parent / "data" / "crops.json"

WEIGHTS = {"environment": 0.25, "space": 0.20, "cycle": 0.15, "experience": 0.15, "preference": 0.15, "light": 0.10}
DIFFICULTY_RANK = {"BEGINNER": 0, "INTERMEDIATE": 1, "ADVANCED": 2}
METHOD = (
    "Rule-based scoring. Hard filters remove crops that cannot work (farming method unsupported, plant taller than the level "
    "gap, room temperature far outside the crop range). Remaining crops get factor scores weighted: environment 25%, "
    "space/capacity 20%, crop cycle 15%, experience fit 15%, user preference 15%, light 10%. Missing inputs score 0.5 (neutral)."
)


def load_catalogue() -> dict:
    return json.loads(CATALOGUE_PATH.read_text())


def _range_fit(value: float | None, rng: list | None, tolerance: float) -> tuple[float | None, str]:
    if value is None or not rng:
        return None, ""
    lo, hi = rng
    if lo <= value <= hi:
        return 1.0, f"{value:g} is within {lo:g}–{hi:g}"
    dist = lo - value if value < lo else value - hi
    return max(0.0, 1 - dist / tolerance), f"{value:g} is {dist:g} outside {lo:g}–{hi:g}"


def score_crop(crop: dict, ctx: dict) -> dict:
    """ctx: farming_type, temperature_c, humidity_pct, light_source, experience_level, preferred_crop,
    crop_categories, rack_config (dict), rack_count."""
    reasons, missing, blockers = [], [], []
    factors: dict[str, float] = {}
    cfg = RackConfig.from_dict(ctx.get("rack_config"))

    # ---- hard filters
    ft = ctx.get("farming_type")
    if ft and ft not in crop["farming_types"]:
        blockers.append(f"Not typically grown with {ft.replace('_', ' ').lower()}.")
    gap = cfg.effective_level_gap
    if crop.get("mature_height_m") and crop["mature_height_m"] + LIGHT_ALLOWANCE_M > gap + 1e-9:
        blockers.append(f"Needs ≈{crop['mature_height_m'] + LIGHT_ALLOWANCE_M:.2f} m per level (plant + light allowance); "
                        f"current level gap is {gap:.2f} m.")
    t = ctx.get("temperature_c")
    if t is not None and crop.get("temp_c"):
        lo, hi = crop["temp_c"]
        if t < lo - 5 or t > hi + 5:
            blockers.append(f"Room temperature {t:g} °C is more than 5 °C outside the crop range {lo}–{hi} °C.")

    # ---- environment
    tf, tmsg = _range_fit(t, crop.get("temp_c"), 6)
    hf, hmsg = _range_fit(ctx.get("humidity_pct"), crop.get("humidity_pct"), 20)
    parts = [x for x in (tf, hf) if x is not None]
    if t is None:
        missing.append("room temperature")
    if ctx.get("humidity_pct") is None:
        missing.append("room humidity")
    factors["environment"] = sum(parts) / len(parts) if parts else 0.5
    if tmsg:
        reasons.append(f"Temperature: {tmsg} °C.")
    if hmsg:
        reasons.append(f"Humidity: {hmsg} %.")

    # ---- space / capacity using the actual design
    cap = capacity(RackConfig.from_dict({**cfg.to_dict(), "plant_spacing_m": None, "plants_per_level": None}),
                   ctx.get("rack_count") or 0, crop)
    total = cap.get("total")
    if total is None:
        factors["space"] = 0.5
        missing.append("plant spacing")
    else:
        factors["space"] = min(1.0, (cap["plants_per_level"] or 0) / 12)
        reasons.append(f"Space: {cap['plants_per_level']} plants per level × {cap['levels_per_rack']} levels × "
                       f"{cap['rack_count']} racks = {total} planting positions.")
    if crop.get("mature_height_m"):
        headroom = gap - (crop["mature_height_m"] + LIGHT_ALLOWANCE_M)
        if headroom >= 0:
            reasons.append(f"Height: fits the {gap:.2f} m level gap with {headroom:.2f} m spare.")

    # ---- cycle
    dth = crop.get("days_to_harvest")
    if dth:
        mid = sum(dth) / 2
        factors["cycle"] = max(0.0, min(1.0, (100 - mid) / 70))
        reasons.append(f"Cycle: roughly {dth[0]}–{dth[1]} days to harvest.")
    else:
        factors["cycle"] = 0.5
        missing.append("days to harvest")

    # ---- experience
    exp = DIFFICULTY_RANK.get(ctx.get("experience_level") or "BEGINNER", 0)
    diff = DIFFICULTY_RANK.get(crop.get("difficulty") or "INTERMEDIATE", 1)
    factors["experience"] = 1.0 if diff <= exp else (0.4 if diff - exp == 1 else 0.1)
    reasons.append(f"Difficulty: {crop.get('difficulty', 'unknown').title()} crop for a {(ctx.get('experience_level') or 'beginner').lower()} grower.")

    # ---- preference
    pref = ctx.get("preferred_crop")
    cats = ctx.get("crop_categories") or []
    if pref and pref == crop["slug"]:
        factors["preference"] = 1.0
        reasons.append("Preference: this is the crop you asked for.")
    elif cats:
        factors["preference"] = 0.8 if crop["category"] in cats else 0.2
        reasons.append(f"Preference: category {crop['category'].title()} " + ("matches" if crop["category"] in cats else "is not in") + " your selected categories.")
    else:
        factors["preference"] = 0.5

    # ---- light
    src = ctx.get("light_source") or "UNKNOWN"
    dli = crop.get("dli")
    if src == "UNKNOWN":
        factors["light"] = 0.5
        missing.append("light source")
    elif src == "SUNLIGHT":
        factors["light"] = 0.3 if (dli and dli[0] >= 17) else 0.6
        reasons.append("Light: window light alone is usually inconsistent indoors; grow lights recommended.")
    else:
        factors["light"] = 0.6 if (dli and dli[0] >= 17) else 1.0
        if dli and dli[0] >= 17:
            reasons.append(f"Light: high requirement (DLI {dli[0]}–{dli[1]} mol/m²/day) means more lighting power.")

    score = round(100 * sum(WEIGHTS[k] * factors[k] for k in WEIGHTS), 1)
    return {
        "slug": crop["slug"], "name": crop["name"], "category": crop["category"],
        "suitable": not blockers, "score": score if not blockers else 0.0, "raw_score": score,
        "factors": {k: round(v, 3) for k, v in factors.items()}, "weights": WEIGHTS,
        "reasons": reasons, "blockers": blockers, "missing_inputs": missing,
        "capacity": cap, "source_type": "RULE",
    }


def recommend(crops: list[dict], ctx: dict) -> dict:
    results = [score_crop(c, ctx) for c in crops]
    results.sort(key=lambda r: (not r["suitable"], -r["score"], r["name"]))
    return {"method": METHOD, "results": results,
            "top": next((r for r in results if r["suitable"]), None),
            "model_status": "No trained ML model is deployed; recommendations come from documented rules."}
