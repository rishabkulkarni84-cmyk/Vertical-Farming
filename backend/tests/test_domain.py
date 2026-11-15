import random
from datetime import datetime, timezone

import pytest

from app.services import alerts, costs, simulator
from app.services.crops import load_catalogue, recommend, score_crop
from app.services.layout import RackConfig

CAT = {c["slug"]: {**c} for c in load_catalogue()["crops"]}


def ctx(**kw):
    base = {"farming_type": "HYDROPONIC_NFT", "temperature_c": 20, "humidity_pct": 60, "light_source": "GROW_LIGHTS",
            "experience_level": "BEGINNER", "preferred_crop": None, "crop_categories": [], "rack_config": {}, "rack_count": 3}
    return {**base, **kw}


def test_catalogue_has_provenance_and_unknowns_null():
    cat = load_catalogue()
    assert cat["provenance"] and cat["last_reviewed"]
    assert any(c["yield_g_per_plant"] is None for c in cat["crops"])  # unknowns are null, not invented


def test_lettuce_suitable_with_explanations():
    r = score_crop(CAT["leaf-lettuce"], ctx())
    assert r["suitable"] and r["score"] > 70
    assert r["reasons"] and r["source_type"] == "RULE"
    assert r["capacity"]["total"] == 60


def test_tall_crop_blocked_by_level_gap():
    r = score_crop(CAT["dwarf-cherry-tomato"], ctx())
    assert not r["suitable"] and r["score"] == 0
    assert any("level gap" in b for b in r["blockers"])


def test_fewer_levels_unblock_tall_crop():
    assert score_crop(CAT["basil"], ctx(rack_config={"levels": 3}))["suitable"]


def test_temperature_hard_filter():
    r = score_crop(CAT["spinach"], ctx(temperature_c=32))
    assert not r["suitable"]


def test_farming_method_filter():
    assert not score_crop(CAT["dwarf-cherry-tomato"], ctx(farming_type="HYDROPONIC_NFT"))["suitable"]


def test_missing_inputs_are_listed_and_neutral():
    r = score_crop(CAT["leaf-lettuce"], ctx(temperature_c=None, humidity_pct=None))
    assert "room temperature" in r["missing_inputs"]
    assert r["factors"]["environment"] == 0.5


def test_preference_raises_score():
    a = score_crop(CAT["kale"], ctx(rack_config={"levels": 3}))["score"]
    b = score_crop(CAT["kale"], ctx(rack_config={"levels": 3}, preferred_crop="kale"))["score"]
    assert b > a


def test_recommend_sorts_suitable_first():
    out = recommend(list(CAT.values()), ctx())
    flags = [r["suitable"] for r in out["results"]]
    assert flags == sorted(flags, reverse=True)
    assert out["top"]["suitable"]


# ------------------------------------------------------------------ costs
def test_bom_arithmetic_and_totals():
    items = costs.generate_bom(RackConfig(), 3, 60, CAT["leaf-lettuce"], "USD", 1.0, None)
    by = {i["key"]: i for i in items}
    assert by["racks"]["quantity"] == 3 and by["racks"]["unit_price"] == 120
    assert by["lights"]["quantity"] == 12  # 3 racks × 4 levels × 1 fixture
    assert all(i["price_source"] in ("ILLUSTRATIVE", "USER_INPUT") for i in items)
    t = costs.totals(items)
    expected = sum(i["quantity"] * i["unit_price"] for i in items if i["included"] and i["cost_type"] == "ONE_TIME")
    assert t["setup_total"] == pytest.approx(round(expected, 2))
    # optional & future items excluded by default
    assert not by["sensors"]["included"] and not by["controller"]["included"]


def test_bom_native_inr_prices_and_user_tariff():
    items = costs.generate_bom(RackConfig(), 2, 40, CAT["leaf-lettuce"], "INR", 83.0, 8.5)
    by = {i["key"]: i for i in items}
    # INR uses the native INR table (no exchange-rate conversion); rack price scales with length × levels
    assert by["racks"]["unit_price"] == pytest.approx(costs.INR_PRICES["rack_per_level_m"] * 1.2 * 4)
    assert by["lights"]["unit_price"] == costs.INR_PRICES["lights"]
    assert by["electricity"]["unit_price"] == 8.5 and by["electricity"]["price_source"] == "USER_INPUT"


def test_bom_other_currency_converts_illustrative_usd():
    items = costs.generate_bom(RackConfig(), 1, 20, None, "EUR", 0.9, None)
    by = {i["key"]: i for i in items}
    assert by["racks"]["unit_price"] == pytest.approx(120 * 0.9)
    assert by["pump"]["unit_price"] == pytest.approx(30 * 0.9)


def test_totals_change_when_line_changes():
    items = costs.generate_bom(RackConfig(), 1, 20, None, "USD", 1.0, None)
    before = costs.totals(items)["setup_total"]
    next(i for i in items if i["key"] == "racks")["unit_price"] = 200
    assert costs.totals(items)["setup_total"] == pytest.approx(before + 80)


def test_profitability_requires_inputs():
    p = costs.profitability(60, CAT["spinach"], None, 50, 1000)
    assert not p["available"] and len(p["missing"]) == 2


def test_profitability_math():
    p = costs.profitability(60, CAT["leaf-lettuce"], 10.0, 50, 1000)
    cycle = (30 + 45) / 2 + costs.TURNAROUND_DAYS
    rev = 60 * 0.150 * costs.SALEABLE_FRACTION * (30 / cycle) * 10
    assert p["estimated_gross_revenue"] == pytest.approx(round(rev, 2))
    assert p["estimated_margin"] == pytest.approx(round(rev - 50, 2))


# ------------------------------------------------------------------ simulator & alerts
def test_simulator_normal_stays_plausible():
    rng = random.Random(1)
    t, _ = simulator.targets_for(CAT["leaf-lettuce"])
    prev = None
    for i in range(200):
        prev = simulator.step(prev, t, "NORMAL", datetime(2026, 1, 1, i % 24, tzinfo=timezone.utc), 16, rng)
    assert 14 < prev["temperature_c"] < 26
    assert 5.0 < prev["ph"] < 7.0
    assert prev["tds_ppm"] == pytest.approx(prev["ec_ms_cm"] * 500, rel=1e-3)


def test_simulator_abnormal_breaches_limits():
    rng = random.Random(2)
    t, _ = simulator.targets_for(None)
    prev = None
    for _ in range(40):
        prev = simulator.step(prev, t, "ABNORMAL", datetime(2026, 1, 1, 10, tzinfo=timezone.utc), 16, rng)
    hits = alerts.evaluate(prev, alerts.default_thresholds(None))
    assert {h["metric"] for h in hits} >= {"ph", "water_level_pct"}
    assert any(h["severity"] == "CRITICAL" for h in hits)


def test_alert_rules_and_nulls():
    th = alerts.default_thresholds(CAT["leaf-lettuce"])
    assert alerts.evaluate({"temperature_c": 20, "ph": 6.0}, th) == []
    hits = alerts.evaluate({"temperature_c": 25, "ph": None}, th)
    assert len(hits) == 1 and hits[0]["severity"] == "WARNING"
    assert alerts.evaluate({"temperature_c": None}, th) == []  # missing readings never alert
    assert alerts.evaluate({"water_level_pct": 10}, th)[0]["severity"] == "CRITICAL"
