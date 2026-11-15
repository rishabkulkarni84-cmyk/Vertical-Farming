import io
import json
from datetime import date

import pytest
from PIL import Image

from app.services import ai as ai_svc
from app.services import season
from app.services.autoplan import plan
from app.services.crops import load_catalogue
from app.services.layout import RackIn, validate_layout
from app.services.spatial import build_context
from app.services.units import to_m

from .conftest import new_user

CAT = {c["slug"]: c for c in load_catalogue()["crops"]}
DOOR = {"kind": "DOOR", "x": 1.2, "y": 0, "w": 0.8, "d": 0.05, "clearance_m": 0.8, "id": 1, "label": "Door"}


# ------------------------------------------------------------------ budget planner
@pytest.mark.parametrize("budget", [10000, 15000, 30000, 50000, 120000, 400000])
@pytest.mark.parametrize("room", [(10, 8, 9), (14, 10, 10), (6, 5, 8)])
def test_autoplan_never_exceeds_budget_and_is_valid(budget, room):
    ctx = build_context(to_m(room[0], "ft"), to_m(room[1], "ft"), to_m(room[2], "ft"), [DOOR])
    r = plan(ctx, budget, "INR", 1, None, CAT["leaf-lettuce"])
    if not r["feasible"]:
        assert "smallest working system" in r["reason"] or "fits" in r["reason"]
        return
    assert r["setup_total"] <= budget * 0.95 + 1e-6  # default 5% reserve
    assert r["remaining"] >= 0
    from app.services.layout import RackConfig
    cfg = RackConfig.from_dict(r["config"])
    assert validate_layout(ctx, cfg, [RackIn(**x) for x in r["racks"]]).valid


def test_autoplan_more_budget_never_fewer_plants():
    ctx = build_context(to_m(14, "ft"), to_m(10, "ft"), to_m(10, "ft"), [DOOR])
    plants = [plan(ctx, b, "INR", 1, None, CAT["leaf-lettuce"]).get("plants", 0) for b in (15000, 30000, 60000, 120000)]
    assert plants == sorted(plants)


def test_autoplan_explains_too_small_budget():
    ctx = build_context(3, 2.5, 2.7, [DOOR])
    r = plan(ctx, 2000, "INR", 1, None, CAT["leaf-lettuce"])
    assert not r["feasible"] and "smallest working system costs" in r["reason"]


def test_autoplan_respects_crop_height():
    ctx = build_context(4, 3, 2.7, [DOOR])
    r = plan(ctx, 200000, "INR", 1, None, CAT["swiss-chard"])
    gap = (r["config"]["rack_height_m"] - 0.15) / r["config"]["levels"]
    assert gap >= CAT["swiss-chard"]["mature_height_m"] + 0.12 - 1e-9


# ------------------------------------------------------------------ provider parsing (mocked HTTP)
def fake_post(payload):
    calls = {}

    def _p(url, body, headers):
        calls.update(url=url, body=body, headers=headers)
        return payload
    return _p, calls


def test_gemini_parsing_and_grounding(monkeypatch):
    p, calls = fake_post({"candidates": [{"content": {"parts": [{"text": '{"a": 1}'}]},
                                          "groundingMetadata": {"groundingChunks": [{"web": {"uri": "https://agmarknet.gov.in", "title": "Agmarknet"}}]}}]})
    monkeypatch.setattr(ai_svc, "_post", p)
    r = ai_svc.generate("gemini", "k", "gemini-x", "hi", b"img", "image/jpeg", web_search=True)
    assert r.text == '{"a": 1}' and r.sources[0]["url"] == "https://agmarknet.gov.in"
    assert calls["headers"]["x-goog-api-key"] == "k" and calls["body"]["tools"] == [{"google_search": {}}]
    assert calls["body"]["contents"][0]["parts"][0]["inline_data"]["mime_type"] == "image/jpeg"


def test_anthropic_parsing(monkeypatch):
    p, calls = fake_post({"content": [{"type": "web_search_tool_result", "content": [{"url": "https://x.in/p", "title": "P"}]},
                                      {"type": "text", "text": "ans", "citations": [{"url": "https://y.in", "title": "Y"}]}]})
    monkeypatch.setattr(ai_svc, "_post", p)
    r = ai_svc.generate("anthropic", "k", "", "hi", web_search=True)
    assert r.text == "ans" and {s["url"] for s in r.sources} == {"https://x.in/p", "https://y.in"}
    assert calls["headers"]["x-api-key"] == "k" and calls["body"]["model"] == ai_svc.PROVIDERS["anthropic"]["default_model"]
    assert calls["body"]["tools"][0]["name"] == "web_search"


def test_openai_parsing(monkeypatch):
    p, calls = fake_post({"output": [{"type": "web_search_call"}, {"type": "message", "content": [
        {"type": "output_text", "text": "hello", "annotations": [{"type": "url_citation", "url": "https://z.in", "title": "Z"}]}]}]})
    monkeypatch.setattr(ai_svc, "_post", p)
    r = ai_svc.generate("openai", "k", "gpt-x", "hi", b"img", "image/png", web_search=True)
    assert r.text == "hello" and r.sources == [{"title": "Z", "url": "https://z.in"}]
    assert calls["headers"]["Authorization"] == "Bearer k"
    assert calls["body"]["input"][0]["content"][1]["image_url"].startswith("data:image/png;base64,")


def test_extract_json_tolerates_fences_and_prose():
    assert ai_svc.extract_json('Sure!\n```json\n{"a": {"b": "x}"}}\n```\nThanks') == {"a": {"b": "x}"}}
    with pytest.raises(ai_svc.AIError):
        ai_svc.extract_json("no data here")
    with pytest.raises(ai_svc.AIError):
        ai_svc.extract_json('{"a": 1')


# ------------------------------------------------------------------ season rules
def test_india_seasons():
    assert season.season_for(12.97, 77.59, date(2026, 11, 8))["code"] == "RABI"
    assert season.season_for(19.07, 72.87, date(2026, 7, 1))["code"] == "KHARIF"
    assert season.season_for(28.6, 77.2, date(2026, 4, 15))["code"] == "ZAID"
    assert season.season_for(51.5, -0.1, date(2026, 1, 10))["code"] == "WINTER"
    assert season.season_for(-33.9, 151.2, date(2026, 1, 10))["code"] == "SUMMER"
    assert season.season_for(None, None)["code"] == "UNKNOWN"


def test_crop_season_fit():
    good, _ = season.crop_season_fit(CAT["leaf-lettuce"], "RABI", 20)
    hot, why = season.crop_season_fit(CAT["leaf-lettuce"], "ZAID", 36)
    assert good == 1.0 and hot < 0.5 and "cooling" in why


# ------------------------------------------------------------------ API: settings, photo, plan, advisor
def _png():
    b = io.BytesIO()
    Image.new("RGB", (64, 48), (200, 190, 170)).save(b, "PNG")
    return b.getvalue()


def test_ai_settings_never_return_key(client):
    c = new_user(client)
    assert c.get("/api/ai/settings").json()["configured"] is False
    r = c.put("/api/ai/settings", json={"provider": "gemini", "api_key": "AIzaSECRETKEY1234567", "model": "gemini-x"}).json()
    assert r["configured"] and r["key_hint"] == "AIza…4567" and "SECRET" not in json.dumps(r)
    # keep existing key when api_key omitted
    assert c.put("/api/ai/settings", json={"provider": "gemini", "model": "gemini-y"}).json()["model"] == "gemini-y"
    assert c.delete("/api/ai/settings").status_code == 204


def test_ai_features_require_setup(client):
    c = new_user(client)
    f = c.post("/api/farms", json={"name": "N"}).json()
    c.put(f"/api/farms/{f['id']}/room", json={"length": 10, "width": 8, "height": 9, "unit": "ft"})
    r = c.post(f"/api/farms/{f['id']}/ai/crop-advice")
    assert r.status_code == 409 and "API key" in r.json()["error"]["message"]


def test_photo_ai_analyze_and_apply(client, monkeypatch):
    c = new_user(client)
    c.put("/api/ai/settings", json={"provider": "anthropic", "api_key": "sk-ant-test-123456789"})
    f = c.post("/api/farms", json={"name": "Photo farm", "budget": 30000}).json()
    assert f["currency"] == "INR"
    img = c.post(f"/api/farms/{f['id']}/images", files={"file": ("r.png", _png(), "image/png")}).json()
    reply = {"room": {"length_m": 3.0, "width_m": 2.5, "height_m": 2.7, "confidence": "medium", "basis": "door ≈ 2 m"},
             "light": {"natural_light": "high", "notes": "big window"}, "objects": [
                 {"kind": "DOOR", "label": "Door", "wall": "N", "x_frac": 0.3, "y_frac": 0, "w_m": 0.8, "d_m": 0.1, "confidence": "high"},
                 {"kind": "WINDOW", "label": "Window", "wall": "E", "x_frac": 1, "y_frac": 0.4, "w_m": 1.2, "d_m": 0.1},
                 {"kind": "SOFA", "label": "ignored"},
                 {"kind": "FURNITURE", "label": "Desk", "wall": "NONE", "x_frac": 0.9, "y_frac": 0.9, "w_m": 9, "d_m": 0.6}],
             "summary": "Small room"}
    monkeypatch.setattr(ai_svc, "generate", lambda *a, **k: ai_svc.AIResult(json.dumps(reply), [], "m", "anthropic"))
    a = c.post(f"/api/images/{img['id']}/ai-analyze").json()
    assert a["source_type"] == "MODEL" and len(a["objects"]) == 3  # unknown kind dropped
    out = c.post(f"/api/images/{img['id']}/ai-apply", json={"unit": "ft"}).json()
    assert out["applied"] == {"dimensions": True, "objects": 3}
    room = c.get(f"/api/farms/{f['id']}/room").json()
    assert room["length_m"] == 3.0 and "estimated by AI" in room["notes"]
    obs = c.get(f"/api/farms/{f['id']}/obstacles").json()
    assert all(o["source"] == "MODEL" and not o["confirmed"] for o in obs)
    for o in obs:  # every suggestion lies inside the room
        assert o["x"] + o["w"] <= 3.0 + 1e-6 and o["y"] + o["d"] <= 2.5 + 1e-6
    door = next(o for o in obs if o["kind"] == "DOOR")
    assert door["y"] == 0 and door["clearance_m"] == 0.9
    # re-applying replaces, not duplicates, unconfirmed AI suggestions
    c.post(f"/api/images/{img['id']}/ai-apply", json={"unit": "ft"})
    assert len(c.get(f"/api/farms/{f['id']}/obstacles").json()) == 3


def test_budget_autoplan_api_and_budget_lock(farm):
    c, fid = farm
    c.patch(f"/api/farms/{fid}", json={"budget": 30000, "currency": "INR"})
    r = c.post(f"/api/farms/{fid}/autoplan", json={}).json()
    assert r["feasible"] and r["setup_total"] <= 30000 and r["design_id"]
    d = c.get(f"/api/designs/{r['design_id']}").json()
    assert d["is_active"] and d["validation"]["valid"] and d["cost_totals"]["setup_total"] <= 30000
    assert d["origin"] == "BUDGET_PLAN"
    # manual edit that would exceed the budget is rejected
    c.patch(f"/api/farms/{fid}", json={"budget": 5000})
    bad = c.patch(f"/api/designs/{d['id']}", json={"racks": d["racks"]})
    assert bad.status_code == 422 and bad.json()["error"]["details"]["violations"][0]["code"] == "OVER_BUDGET"
    tiny = c.post(f"/api/farms/{fid}/autoplan", json={}).json()
    assert not tiny["feasible"] and tiny["reason"]


def test_budget_required_for_autoplan(user):
    f = user.post("/api/farms", json={"name": "No budget"}).json()
    user.put(f"/api/farms/{f['id']}/room", json={"length": 10, "width": 8, "height": 9, "unit": "ft"})
    assert user.post(f"/api/farms/{f['id']}/autoplan", json={}).status_code == 422


def test_crop_advice_filters_to_growable_and_applies(client, monkeypatch):
    c = new_user(client)
    c.put("/api/ai/settings", json={"provider": "openai", "api_key": "sk-test-abcdefghijkl"})
    f = c.post("/api/farms", json={"name": "Advice", "budget": 40000}).json()
    c.put(f"/api/farms/{f['id']}/room", json={"length": 10, "width": 8, "height": 9, "unit": "ft"})
    c.post(f"/api/farms/{f['id']}/obstacles", json={"kind": "DOOR", "x": 1.2, "y": 0, "w": 0.8, "d": 0.05})
    monkeypatch.setattr(season, "weather", lambda *a: None)
    monkeypatch.setattr(season, "reverse_geocode", lambda *a: "Bengaluru, Karnataka, India")
    loc = c.put(f"/api/farms/{f['id']}/location", json={"latitude": 12.97, "longitude": 77.59, "source": "BROWSER_GPS"}).json()
    assert loc["location"]["name"].startswith("Bengaluru") and loc["season"]["region"] == "India"
    reply = {"season_summary": "Cool, dry", "recommendations": [
        {"slug": "basil", "why": "Restaurants", "demand_trend": "rising", "price_per_kg_low": 300, "price_per_kg_high": 500, "price_basis": "mandi"},
        {"slug": "dwarf-cherry-tomato", "why": "would not fit NFT"},
        {"slug": "made-up-crop", "why": "x"}], "trending_notes": ["Microgreens rising"]}
    monkeypatch.setattr(ai_svc, "generate", lambda *a, **k: ai_svc.AIResult(json.dumps(reply), [{"title": "S", "url": "https://s.in"}], "m", "openai"))
    adv = c.post(f"/api/farms/{f['id']}/ai/crop-advice").json()
    assert [r["slug"] for r in adv["recommendations"]] == ["basil"]  # infeasible / unknown crops removed
    assert adv["source_type"] == "MODEL" and adv["sources"][0]["url"] == "https://s.in"
    res = c.post(f"/api/farms/{f['id']}/ai/crop-advice/apply", json={"slug": "basil"}).json()
    assert res["feasible"] and res["crop"]["slug"] == "basil" and res["setup_total"] <= 40000
    prices = c.get(f"/api/farms/{f['id']}/market-prices").json()
    assert prices[0]["source_type"] == "AI_ESTIMATE" and prices[0]["price"] == 400
