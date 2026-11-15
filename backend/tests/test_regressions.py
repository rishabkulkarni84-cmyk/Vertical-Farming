"""Regression tests for bugs found in the code review (each test fails on the previous code)."""
from datetime import datetime, timedelta, timezone

from app import config
from app.db import SessionLocal
from app.models import SensorRecord
from app.services import season

from .conftest import new_user


def _farm(c, **kw):
    f = c.post("/api/farms", json={"name": "R", **kw}).json()
    c.put(f"/api/farms/{f['id']}/room", json={"length": 10, "width": 8, "height": 9, "unit": "ft"})
    c.post(f"/api/farms/{f['id']}/obstacles", json={"kind": "DOOR", "x": 1.2, "y": 0, "w": 0.8, "d": 0.05})
    return f["id"]


def test_price_in_old_currency_is_not_used_after_currency_change(client):
    c = new_user(client)
    fid = _farm(c, currency="USD", budget=5000, preferred_crop="leaf-lettuce")
    plan = c.post(f"/api/farms/{fid}/autoplan", json={}).json()
    c.post(f"/api/farms/{fid}/market-prices", json={"crop_slug": "leaf-lettuce", "price": 9})  # $9/kg
    assert c.get(f"/api/designs/{plan['design_id']}/costs").json()["profitability"]["available"]
    c.patch(f"/api/farms/{fid}", json={"currency": "INR", "budget": 300000})
    prof = c.get(f"/api/designs/{plan['design_id']}/costs").json()["profitability"]
    assert not prof["available"]  # a $9 price must never be read as ₹9


def test_currency_change_resets_typed_prices_and_flags_custom_lines(client):
    c = new_user(client)
    fid = _farm(c, currency="USD", budget=5000)
    did = c.post(f"/api/farms/{fid}/autoplan", json={}).json()["design_id"]
    items = c.get(f"/api/designs/{did}/costs").json()["items"]
    rack = next(i for i in items if i["key"] == "racks")
    c.patch(f"/api/cost-items/{rack['id']}", json={"unit_price": 150})
    c.post(f"/api/designs/{did}/cost-items", json={"name": "Shelf liner", "category": "Other", "quantity": 1, "unit_price": 10})
    c.patch(f"/api/farms/{fid}", json={"currency": "INR", "budget": 300000})
    after = c.get(f"/api/designs/{did}/costs").json()["items"]
    assert {i["currency"] for i in after} == {"INR"}
    r = next(i for i in after if i["key"] == "racks")
    assert r["price_source"] == "ILLUSTRATIVE" and r["unit_price"] > 1000  # INR sample price, not "150"
    custom = next(i for i in after if i["name"] == "Shelf liner")
    assert "entered in USD" in custom["notes"]


def test_shrinking_room_keeps_obstacles_inside(client):
    c = new_user(client)
    fid = _farm(c)
    c.post(f"/api/farms/{fid}/obstacles", json={"kind": "PILLAR", "x": 2.5, "y": 2.0, "w": 0.4, "d": 0.4})
    c.put(f"/api/farms/{fid}/room", json={"length": 6, "width": 5, "height": 9, "unit": "ft"})
    L, W = 6 * 0.3048, 5 * 0.3048
    for o in c.get(f"/api/farms/{fid}/obstacles").json():
        assert o["x"] + o["w"] <= L + 1e-6 and o["y"] + o["d"] <= W + 1e-6
    p = next(o for o in c.get(f"/api/farms/{fid}/obstacles").json() if o["kind"] == "PILLAR")
    assert c.patch(f"/api/obstacles/{p['id']}", json={"label": "still editable"}).status_code == 200


def test_replanning_does_not_pile_up_designs(client):
    c = new_user(client)
    fid = _farm(c, budget=60000)
    for _ in range(5):
        c.post(f"/api/farms/{fid}/autoplan", json={})
    designs = c.get(f"/api/farms/{fid}/designs").json()
    assert len([d for d in designs if d["origin"] == "BUDGET_PLAN"]) == 3
    assert sum(d["is_active"] for d in designs) == 1


def test_alert_summary_is_per_user(client):
    a, b = new_user(client), new_user(client)
    fid = _farm(a)
    a.post(f"/api/farms/{fid}/alerts/test")
    s = a.get("/api/alerts/summary").json()
    assert s["open"] >= 2 and s["critical"] >= 1
    assert b.get("/api/alerts/summary").json() == {"open": 0, "critical": 0, "warning": 0}


def test_weather_is_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(season, "_fetch_weather", lambda lat, lon: calls.append(1) or {"mean_temp_c": 25})
    season._WEATHER_CACHE.clear()
    for _ in range(5):
        assert season.weather(12.9716, 77.5946)["mean_temp_c"] == 25
    assert len(calls) == 1


def test_default_secret_key_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "BASE_DIR", tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("SECRET_KEY", config.DEFAULT_SECRET)
    config.get_settings.cache_clear()
    try:
        s1 = config.get_settings().secret_key
        config.get_settings.cache_clear()
        s2 = config.get_settings().secret_key
    finally:
        monkeypatch.setenv("ENVIRONMENT", "test")
        config.get_settings.cache_clear()
    assert s1 != config.DEFAULT_SECRET and len(s1) > 40 and s1 == s2  # random, and stable across restarts


def test_series_buckets_average_in_database(client):
    c = new_user(client)
    fid = _farm(c)
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for i, t in enumerate([20.0, 22.0, 24.0]):
            db.add(SensorRecord(farm_id=fid, ts=now - timedelta(seconds=10 + i), source_type="SIMULATED", temperature_c=t, ph=None))
        db.add(SensorRecord(farm_id=fid, ts=now - timedelta(hours=3), source_type="SIMULATED", temperature_c=99.0))  # outside 1h
        db.commit()
    s = c.get(f"/api/farms/{fid}/sensors/series?range=1h&buckets=10").json()
    assert s["count"] == 3 and len(s["points"]) == 1
    assert s["points"][0]["temperature_c"] == 22.0 and s["points"][0]["ph"] is None


def test_long_strategy_names_fit_the_column(client):
    """PostgreSQL enforces VARCHAR lengths; generated names reached 80 characters (column was 60)."""
    from app.models import Design
    c = new_user(client)
    fid = _farm(c, budget=500000)
    r = c.post(f"/api/farms/{fid}/autoplan", json={}).json()
    with SessionLocal() as db:
        d = db.get(Design, r["design_id"])
        assert len(d.strategy) <= Design.__table__.c.strategy.type.length
    assert Design.__table__.c.strategy.type.length >= 200
