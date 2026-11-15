"""Simulated IoT sensor generator. Every record it produces carries source_type = SIMULATED.

Values follow a mean-reverting random walk toward targets (crop mid-ranges when known, else generic
simulation targets). Modes: NORMAL stays in range; WARNING drifts temperature/humidity past warning
limits; ABNORMAL pushes pH and water level past critical limits — for testing alerts.
"""
from __future__ import annotations

import random
from datetime import datetime

GENERIC_TARGETS = {"temperature_c": 22.0, "humidity_pct": 60.0, "ph": 6.0, "ec_ms_cm": 1.4, "water_level_pct": 85.0}
NOISE = {"temperature_c": 0.15, "humidity_pct": 0.8, "ph": 0.03, "ec_ms_cm": 0.02, "water_level_pct": 0.3}
METRICS = ["temperature_c", "humidity_pct", "ph", "ec_ms_cm", "tds_ppm", "water_level_pct", "light_ppfd", "pump_on", "fan_on"]


def targets_for(crop: dict | None) -> tuple[dict, str]:
    t = dict(GENERIC_TARGETS)
    basis = "Generic simulation targets (not a growing standard)."
    if crop:
        for key, ck in (("temperature_c", "temp_c"), ("humidity_pct", "humidity_pct"), ("ph", "ph"), ("ec_ms_cm", "ec_ms_cm")):
            if crop.get(ck):
                t[key] = sum(crop[ck]) / 2
        basis = f"Mid-points of the {crop['name']} catalogue ranges (indicative)."
    return t, basis


def step(prev: dict | None, targets: dict, mode: str, ts: datetime, photoperiod_h: int = 16,
         rng: random.Random | None = None) -> dict:
    rng = rng or random.Random()
    prev = prev or {}
    out: dict = {}
    drift = {k: 0.0 for k in GENERIC_TARGETS}
    goal = dict(targets)
    if mode == "WARNING":
        goal["temperature_c"] = targets["temperature_c"] + 6
        goal["humidity_pct"] = min(95, targets["humidity_pct"] + 20)
    elif mode == "ABNORMAL":
        goal["ph"] = targets["ph"] + 1.6
        goal["water_level_pct"] = 12
        goal["temperature_c"] = targets["temperature_c"] + 9
    for k in GENERIC_TARGETS:
        cur = prev.get(k, targets[k])
        pull = 0.25 if mode != "NORMAL" else 0.12
        cur = cur + (goal[k] - cur) * pull + drift[k] + rng.gauss(0, NOISE[k])
        out[k] = cur
    # water level slowly drops in NORMAL mode then is "topped up"
    if mode == "NORMAL":
        out["water_level_pct"] = prev.get("water_level_pct", 90) - abs(rng.gauss(0.05, 0.02))
        if out["water_level_pct"] < 70:
            out["water_level_pct"] = 92.0
    out["humidity_pct"] = max(5.0, min(100.0, out["humidity_pct"]))
    out["water_level_pct"] = max(0.0, min(100.0, out["water_level_pct"]))
    out["ph"] = max(0.0, min(14.0, out["ph"]))
    out["ec_ms_cm"] = max(0.0, out["ec_ms_cm"])
    out["tds_ppm"] = out["ec_ms_cm"] * 500  # 500-scale conversion
    lights_on = (ts.hour + ts.minute / 60) % 24 < photoperiod_h
    out["light_ppfd"] = max(0.0, rng.gauss(250, 5)) if lights_on else 0.0
    out["pump_on"] = out["water_level_pct"] > 15
    out["fan_on"] = out["temperature_c"] > targets["temperature_c"] + 1 or out["humidity_pct"] > targets["humidity_pct"] + 10
    return {k: (round(v, 3) if isinstance(v, float) else v) for k, v in out.items()}
