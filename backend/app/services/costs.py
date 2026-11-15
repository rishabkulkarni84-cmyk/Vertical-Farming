"""Bill of materials, resource estimates and profitability.

All sample prices are ILLUSTRATIVE (USD reference values chosen by the Verdant authors for planning only, not quotes).
They are converted with the user-provided exchange rate (farm.fx_rate_per_usd). Users should replace them with real quotes.
"""
from __future__ import annotations

import math

from .layout import RackConfig

ILLUSTRATIVE_DATE = "2026-11-08"
LIGHT_W_PER_FIXTURE = 40.0  # assumption: one ~40 W LED bar per 1.2 m of shelf per level
PUMP_W = 25.0
FAN_W = 15.0
WATER_L_PER_PLANT_DAY = 0.15  # assumption for leafy greens incl. evaporation
SALEABLE_FRACTION = 0.85
TURNAROUND_DAYS = 5
ILLUSTRATIVE_KWH_USD = 0.15
ILLUSTRATIVE_WATER_USD_PER_L = 0.002

# Native INR planning prices (illustrative, typical Indian retail levels; not quotes). Used when currency == INR,
# so no exchange-rate assumption is needed. Rack and channel prices scale with rack length and levels.
INR_PRICES = {
    "rack_per_level_m": 800.0, "channel_per_m": 1000.0, "netcups": 3.0, "tank": 900.0, "pump": 1200.0, "plumbing": 700.0,
    "lights": 1400.0, "timers": 450.0, "fans": 1100.0, "meters": 1600.0, "safety": 1500.0, "sensors": 2500.0,
    "controller": 900.0, "nutrients": 60.0, "phadj": 350.0, "seeds": 2.0, "electricity": 8.0, "water": 0.05,
}
USD_RACK_PER_LEVEL_M = 25.0
USD_CHANNEL_PER_M = 20.83


def _fixtures_per_level(cfg: RackConfig) -> int:
    return max(1, math.ceil(cfg.rack_length_m / 1.2 - 1e-9))


def resources(cfg: RackConfig, rack_count: int, plants: int | None, crop: dict | None) -> dict:
    hours = (crop or {}).get("photoperiod_h") or 16
    fixtures = rack_count * cfg.levels * _fixtures_per_level(cfg)
    tanks = math.ceil(rack_count / 2) if rack_count else 0
    fans = math.ceil(rack_count / 2) if rack_count else 0
    light_kwh = fixtures * LIGHT_W_PER_FIXTURE * hours * 30 / 1000
    pump_kwh = tanks * PUMP_W * 24 * 30 / 1000
    fan_kwh = fans * FAN_W * 24 * 30 / 1000
    water_l = (plants or 0) * WATER_L_PER_PLANT_DAY * 30
    return {
        "light_fixtures": fixtures, "tanks": tanks, "fans": fans, "photoperiod_h": hours,
        "lighting_kw": round(fixtures * LIGHT_W_PER_FIXTURE / 1000, 3),
        "energy_kwh_month": round(light_kwh + pump_kwh + fan_kwh, 1),
        "energy_breakdown": {"lighting": round(light_kwh, 1), "pumps": round(pump_kwh, 1), "fans": round(fan_kwh, 1)},
        "water_l_month": round(water_l, 1),
        "assumptions": [f"{LIGHT_W_PER_FIXTURE:.0f} W LED fixture per 1.2 m shelf per level, on {hours} h/day.",
                        f"One {PUMP_W:.0f} W pump per reservoir (1 reservoir per 2 racks) running 24 h/day.",
                        f"One {FAN_W:.0f} W fan per 2 racks running 24 h/day.",
                        f"{WATER_L_PER_PLANT_DAY} L water per plant per day (indicative, leafy greens)."],
    }


def generate_bom(cfg: RackConfig, rack_count: int, plants: int | None, crop: dict | None, currency: str, fx: float,
                 electricity_rate: float | None) -> list[dict]:
    """Return auto-generated BOM lines keyed by `key` (prices in farm currency)."""
    res = resources(cfg, rack_count, plants, crop)
    lv = rack_count * cfg.levels
    p = plants or 0

    inr = currency == "INR"

    def line(key, name, cat, qty, unit, usd, cost_type="ONE_TIME", status="REQUIRED", notes=None, price=None, source="ILLUSTRATIVE"):
        if price is None:
            price = INR_PRICES[key] if inr and key in INR_PRICES else usd * fx
        return {"key": key, "name": name, "category": cat, "quantity": float(qty), "unit": unit,
                "unit_price": round(price, 4), "currency": currency,
                "price_source": source, "source_date": ILLUSTRATIVE_DATE if source == "ILLUSTRATIVE" else None,
                "cost_type": cost_type, "status": status, "included": status == "REQUIRED", "notes": notes}

    kwh_price = electricity_rate if electricity_rate is not None else (INR_PRICES["electricity"] if inr else ILLUSTRATIVE_KWH_USD * fx)
    kwh_source = "USER_INPUT" if electricity_rate is not None else "ILLUSTRATIVE"
    cycle_days = (sum((crop or {}).get("days_to_harvest") or [40, 40]) / 2) + TURNAROUND_DAYS
    seedlings_month = p * 30 / cycle_days if p else 0

    return [
        line("racks", f"Shelving rack {cfg.rack_length_m:.2f}×{cfg.rack_depth_m:.2f}×{cfg.rack_height_m:.2f} m, {cfg.levels} levels",
             "Racks & structure", rack_count, "pcs", 0,
             price=(INR_PRICES["rack_per_level_m"] if inr else USD_RACK_PER_LEVEL_M * fx) * cfg.rack_length_m * cfg.levels),
        line("channels", f"Grow trays / NFT channels {cfg.rack_length_m:.2f} m (one set per level)", "Trays & channels", lv, "sets", 0,
             price=(INR_PRICES["channel_per_m"] if inr else USD_CHANNEL_PER_M * fx) * cfg.rack_length_m),
        line("netcups", "Net cups + growing medium plugs", "Growing media", p, "pcs", 0.10),
        line("tank", "Nutrient reservoir (≈60 L) with lid", "Water system", res["tanks"], "pcs", 40),
        line("pump", "Submersible circulation pump", "Water system", res["tanks"], "pcs", 30),
        line("plumbing", "Tubing, fittings and return lines", "Water system", rack_count, "kits", 15),
        line("lights", f"LED grow light bar ({LIGHT_W_PER_FIXTURE:.0f} W)", "Lighting & electrical", res["light_fixtures"], "pcs", 45),
        line("timers", "Timers and power strips", "Lighting & electrical", max(1, math.ceil(rack_count / 2)) if rack_count else 0, "pcs", 20),
        line("fans", "Clip-on circulation fan", "Ventilation", res["fans"], "pcs", 25),
        line("meters", "pH + EC/TDS handheld meters", "Nutrients & testing", 1 if rack_count else 0, "set", 40),
        line("safety", "RCD/GFCI protection, drip trays, cable management", "Safety & installation", 1 if rack_count else 0, "set", 35),
        line("sensors", "Temperature/humidity/water sensors (optional)", "Sensors & controllers", 1 if rack_count else 0, "kit", 60, status="OPTIONAL"),
        line("controller", "ESP32 controller + relay board (future hardware)", "Automation", 1 if rack_count else 0, "kit", 15, status="FUTURE",
             notes="Hardware integration is not implemented yet."),
        line("nutrients", "Hydroponic nutrients", "Nutrients & testing", round(p * 0.05, 2), "units", 1.0, cost_type="MONTHLY",
             notes="≈0.05 units per plant per month (assumption)"),
        line("phadj", "pH up/down solutions", "Nutrients & testing", 1 if rack_count else 0, "set", 5, cost_type="MONTHLY"),
        line("seeds", "Seeds / seedlings", "Growing media", round(seedlings_month, 1), "pcs", 0.05, cost_type="MONTHLY",
             notes=f"Replanting every ≈{cycle_days:.0f} days"),
        line("electricity", "Electricity", "Utilities", res["energy_kwh_month"], "kWh", 0, cost_type="MONTHLY",
             price=kwh_price, source=kwh_source),
        line("water", "Water", "Utilities", res["water_l_month"], "L", ILLUSTRATIVE_WATER_USD_PER_L, cost_type="MONTHLY"),
    ]


def totals(items: list) -> dict:
    def g(i, k):
        return i[k] if isinstance(i, dict) else getattr(i, k)
    setup = sum(g(i, "quantity") * g(i, "unit_price") for i in items if g(i, "included") and g(i, "cost_type") == "ONE_TIME")
    monthly = sum(g(i, "quantity") * g(i, "unit_price") for i in items if g(i, "included") and g(i, "cost_type") == "MONTHLY")
    by_cat: dict[str, float] = {}
    for i in items:
        if g(i, "included"):
            by_cat[g(i, "category")] = by_cat.get(g(i, "category"), 0) + g(i, "quantity") * g(i, "unit_price")
    return {"setup_total": round(setup, 2), "monthly_total": round(monthly, 2),
            "by_category": {k: round(v, 2) for k, v in by_cat.items()},
            "illustrative_lines": sum(1 for i in items if g(i, "included") and g(i, "price_source") == "ILLUSTRATIVE"),
            "definition": "Setup = included one-time lines. Monthly = included recurring lines. FUTURE and excluded lines are not counted."}


def profitability(plants: int | None, crop: dict | None, price_per_kg: float | None, monthly_cost: float,
                  setup_cost: float, yield_override_g: float | None = None) -> dict:
    missing: list[str] = []
    yg = yield_override_g or (crop or {}).get("yield_g_per_plant")
    if not plants:
        missing.append("plant capacity")
    if not yg:
        missing.append("yield per plant (not in catalogue — enter your own estimate)")
    if price_per_kg is None:
        missing.append("selling price (enter a market price assumption)")
    if missing:
        return {"available": False, "missing": missing,
                "notes": ["Revenue is not estimated without these inputs; no prices or yields are invented."]}
    cycle_days = (sum(crop.get("days_to_harvest") or [40, 40]) / 2) + TURNAROUND_DAYS
    yield_cycle = plants * yg / 1000 * SALEABLE_FRACTION
    cycles_month = 30 / cycle_days
    revenue = yield_cycle * cycles_month * price_per_kg
    margin = revenue - monthly_cost
    return {
        "available": True, "period": "per 30-day month at steady state",
        "estimated_saleable_yield_kg_cycle": round(yield_cycle, 2),
        "cycle_days": round(cycle_days, 1), "cycles_per_month": round(cycles_month, 2),
        "estimated_gross_revenue": round(revenue, 2), "included_costs": round(monthly_cost, 2),
        "estimated_margin": round(margin, 2),
        "payback_months": round(setup_cost / margin, 1) if margin > 0 else None,
        "assumptions": [f"Yield {yg:g} g/plant ({'user' if yield_override_g else 'catalogue, indicative'}).",
                        f"{int(SALEABLE_FRACTION * 100)}% of harvest saleable.",
                        f"Cycle = average days to harvest + {TURNAROUND_DAYS} days turnaround.",
                        "Included costs = monthly recurring BOM lines only; labour, rent and packaging excluded.",
                        "Estimate only — not a guarantee of yield, demand, price or profit."],
    }
