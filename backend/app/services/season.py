"""Location → growing season and seasonal crop fit (deterministic RULE), plus optional live weather and geocoding
from free, key-less services (Open-Meteo, BigDataCloud). External calls fail gracefully; nothing is invented."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from datetime import date

UA = {"User-Agent": "Verdant-vertical-farm-planner/1.0"}


def in_india(lat: float | None, lon: float | None) -> bool:
    return lat is not None and lon is not None and 6 <= lat <= 37.5 and 68 <= lon <= 97.5


def season_for(lat: float | None, lon: float | None, d: date | None = None) -> dict:
    d = d or date.today()
    m = d.month
    if lat is None:
        return {"name": "Unknown", "code": "UNKNOWN", "detail": "Location not set — enable location for seasonal advice.", "basis": "RULE"}
    if in_india(lat, lon):
        if m in (6, 7, 8, 9, 10):
            s = ("Kharif (monsoon)", "KHARIF", "Hot and humid; leafy greens are scarce in open fields, so indoor greens often fetch better prices. Plan for dehumidification.")
        elif m in (11, 12, 1, 2):
            s = ("Rabi (winter)", "RABI", "Cool and dry; ideal indoor conditions for lettuce, spinach and herbs. Field supply of greens is high, so prices can soften.")
        else:
            s = ("Zaid (summer)", "ZAID", "Hot and dry; cooling costs rise for cool-season crops. Heat-tolerant herbs like basil do well, and greens are in short supply.")
        return {"name": s[0], "code": s[1], "detail": s[2], "region": "India", "basis": "RULE"}
    trop = abs(lat) < 23.5
    north = lat >= 0
    if trop:
        return {"name": "Tropical", "code": "TROPICAL", "detail": "Warm all year; plan cooling for cool-season crops.", "basis": "RULE"}
    seasons = {12: "Winter", 1: "Winter", 2: "Winter", 3: "Spring", 4: "Spring", 5: "Spring", 6: "Summer", 7: "Summer", 8: "Summer",
               9: "Autumn", 10: "Autumn", 11: "Autumn"}
    flip = {"Winter": "Summer", "Summer": "Winter", "Spring": "Autumn", "Autumn": "Spring"}
    name = seasons[m] if north else flip[seasons[m]]
    return {"name": name, "code": name.upper(), "detail": f"{name} in the {'northern' if north else 'southern'} hemisphere.", "basis": "RULE"}


def crop_season_fit(crop: dict, season_code: str, outdoor_temp: float | None) -> tuple[float, str]:
    """0–1 score of how well a crop suits the season/outdoor climate (indoor rooms still follow outdoor heat)."""
    rng = crop.get("temp_c")
    if not rng:
        return 0.5, "Temperature range unknown."
    lo, hi = rng
    t = outdoor_temp
    if t is None:
        t = {"KHARIF": 30, "ZAID": 34, "RABI": 20, "TROPICAL": 29, "SUMMER": 27, "WINTER": 8, "SPRING": 17, "AUTUMN": 15}.get(season_code)
    if t is None:
        return 0.5, "Season unknown."
    if lo <= t <= hi:
        return 1.0, f"Outdoor ≈{t:.0f} °C sits inside the crop's {lo}–{hi} °C range: little heating or cooling needed."
    gap = lo - t if t < lo else t - hi
    return max(0.0, 1 - gap / 12), f"Outdoor ≈{t:.0f} °C is {gap:.0f} °C {'below' if t < lo else 'above'} the crop's {lo}–{hi} °C range: expect {'heating' if t < lo else 'cooling'} costs."


def _get(url: str) -> dict:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=8) as r:
        return json.loads(r.read().decode())


_WEATHER_CACHE: dict[tuple[float, float], tuple[float, dict | None]] = {}
WEATHER_TTL_S = 3600
WEATHER_FAIL_TTL_S = 300


def weather(lat: float, lon: float) -> dict | None:
    """7-day forecast from Open-Meteo, cached for an hour per ~1 km cell (failures cached 5 min so pages stay fast)."""
    import time
    key = (round(lat, 2), round(lon, 2))
    hit = _WEATHER_CACHE.get(key)
    if hit and time.monotonic() - hit[0] < (WEATHER_TTL_S if hit[1] else WEATHER_FAIL_TTL_S):
        return hit[1]
    res = _fetch_weather(lat, lon)
    _WEATHER_CACHE[key] = (time.monotonic(), res)
    return res


def _fetch_weather(lat: float, lon: float) -> dict | None:
    try:
        q = urllib.parse.urlencode({"latitude": lat, "longitude": lon, "daily": "temperature_2m_max,temperature_2m_min,relative_humidity_2m_mean",
                                    "timezone": "auto", "forecast_days": 7})
        d = _get(f"https://api.open-meteo.com/v1/forecast?{q}")["daily"]
        tmax, tmin = d["temperature_2m_max"], d["temperature_2m_min"]
        rh = [x for x in d.get("relative_humidity_2m_mean", []) if x is not None]
        return {"mean_temp_c": round((sum(tmax) + sum(tmin)) / (len(tmax) + len(tmin)), 1), "max_temp_c": max(tmax), "min_temp_c": min(tmin),
                "mean_humidity_pct": round(sum(rh) / len(rh)) if rh else None, "source": "Open-Meteo 7-day forecast", "source_type": "EXTERNAL_DATA"}
    except Exception:
        return None


def reverse_geocode(lat: float, lon: float) -> str | None:
    try:
        d = _get(f"https://api.bigdatacloud.net/data/reverse-geocode-client?latitude={lat}&longitude={lon}&localityLanguage=en")
        parts = [d.get("city") or d.get("locality"), d.get("principalSubdivision"), d.get("countryName")]
        return ", ".join(p for p in parts if p) or None
    except Exception:
        return None


def geocode(name: str) -> dict | None:
    try:
        d = _get("https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": name, "count": 1, "language": "en"}))
        r = (d.get("results") or [None])[0]
        if not r:
            return None
        return {"latitude": r["latitude"], "longitude": r["longitude"],
                "name": ", ".join(p for p in (r.get("name"), r.get("admin1"), r.get("country")) if p)}
    except Exception:
        return None
