"""Rule-based thresholds and alert evaluation (source_type = RULE)."""
from __future__ import annotations

LABELS = {"temperature_c": ("Temperature", "°C"), "humidity_pct": ("Humidity", "%"), "ph": ("pH", ""),
          "ec_ms_cm": ("EC", "mS/cm"), "water_level_pct": ("Water level", "%")}

SUGGESTIONS = {
    ("temperature_c", "high"): "Increase ventilation, reduce light hours, or check room cooling.",
    ("temperature_c", "low"): "Check heating; cold slows growth and can damage warm-season crops.",
    ("humidity_pct", "high"): "Increase airflow or dehumidify to reduce disease risk.",
    ("humidity_pct", "low"): "Reduce ventilation or add humidification; watch for leaf tip burn.",
    ("ph", "high"): "Add pH-down solution gradually and re-test after mixing.",
    ("ph", "low"): "Add pH-up solution gradually and re-test after mixing.",
    ("ec_ms_cm", "high"): "Dilute the nutrient solution with fresh water.",
    ("ec_ms_cm", "low"): "Add nutrient concentrate per the product label.",
    ("water_level_pct", "low"): "Top up the reservoir and check for leaks; low level can run the pump dry.",
    ("water_level_pct", "high"): "Check for overflow or a blocked return line.",
}


def default_thresholds(crop: dict | None) -> list[dict]:
    def rng(key, ck, generic, warn_pad, crit_pad):
        r = (crop or {}).get(ck) if ck else None
        lo, hi = r if r else generic
        basis = f"{crop['name']} catalogue range (indicative)" if r else "Generic starting point for leafy greens — adjust for your system"
        return {"metric": key, "warn_min": round(lo - warn_pad, 3), "warn_max": round(hi + warn_pad, 3),
                "crit_min": round(lo - crit_pad, 3), "crit_max": round(hi + crit_pad, 3), "basis": basis, "enabled": True}
    return [
        rng("temperature_c", "temp_c", (16, 26), 0, 4),
        rng("humidity_pct", "humidity_pct", (45, 75), 0, 15),
        rng("ph", "ph", (5.5, 6.5), 0, 0.7),
        rng("ec_ms_cm", "ec_ms_cm", (0.8, 2.0), 0, 0.6),
        {"metric": "water_level_pct", "warn_min": 40, "warn_max": None, "crit_min": 20, "crit_max": None,
         "basis": "Reservoir level relative to full; generic default", "enabled": True},
    ]


def evaluate(record: dict, thresholds: list) -> list[dict]:
    """Return alert dicts for values outside thresholds. Null readings never alert."""
    out = []
    for t in thresholds:
        def g(k, t=t):
            return t[k] if isinstance(t, dict) else getattr(t, k)
        if not g("enabled"):
            continue
        metric = g("metric")
        val = record.get(metric)
        if val is None:
            continue
        name, unit = LABELS.get(metric, (metric, ""))
        sev = direction = limit = None
        if g("crit_min") is not None and val < g("crit_min"):
            sev, direction, limit = "CRITICAL", "low", g("crit_min")
        elif g("crit_max") is not None and val > g("crit_max"):
            sev, direction, limit = "CRITICAL", "high", g("crit_max")
        elif g("warn_min") is not None and val < g("warn_min"):
            sev, direction, limit = "WARNING", "low", g("warn_min")
        elif g("warn_max") is not None and val > g("warn_max"):
            sev, direction, limit = "WARNING", "high", g("warn_max")
        if sev:
            out.append({"metric": metric, "severity": sev, "value": round(val, 2),
                        "message": f"{name} {val:.2f}{(' ' + unit) if unit else ''} is {'below' if direction == 'low' else 'above'} "
                                   f"the {sev.lower()} limit {limit:g}{(' ' + unit) if unit else ''}.",
                        "suggestion": SUGGESTIONS.get((metric, direction), "Review the system.")})
    return out
