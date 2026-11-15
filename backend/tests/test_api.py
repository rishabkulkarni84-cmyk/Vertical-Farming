import io

from PIL import Image

from .conftest import H, new_user


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200 and r.json()["database"] == "ok"


def test_auth_flow(client):
    c = new_user(client)
    me = c.get("/api/auth/me").json()
    assert me["email"].endswith("@example.com")
    assert "password" not in str(me)
    c.post("/api/auth/logout")
    c.cookies.clear()
    assert c.get("/api/auth/me").status_code == 401


def test_login_rejects_bad_password(client):
    c = new_user(client)
    email = c.get("/api/auth/me").json()["email"]
    r = client.post("/api/auth/login", json={"email": email, "password": "wrong-password"}, headers=H)
    assert r.status_code == 401 and r.json()["error"]["code"] == "UNAUTHORIZED"


def test_signup_validation(client):
    r = client.post("/api/auth/signup", json={"email": "bad", "name": "", "password": "123"}, headers=H)
    assert r.status_code == 422 and r.json()["error"]["details"]


def test_csrf_header_required_for_cookie_writes(client):
    c = new_user(client)
    del c.headers["X-Requested-With"]
    assert c.post("/api/farms", json={"name": "x"}).status_code == 403


def test_ownership_enforced(client, farm):
    owner, fid = farm
    other = new_user(client)
    assert other.get(f"/api/farms/{fid}").status_code == 404
    assert other.put(f"/api/farms/{fid}/room", json={"length": 3, "width": 3, "height": 3, "unit": "m"}).status_code == 404
    obs = owner.get(f"/api/farms/{fid}/obstacles").json()[0]
    assert other.delete(f"/api/obstacles/{obs['id']}").status_code == 404
    assert other.get(f"/api/farms/{fid}/sensors").status_code == 404


def test_room_validation(user):
    f = user.post("/api/farms", json={"name": "V"}).json()
    r = user.put(f"/api/farms/{f['id']}/room", json={"length": 0, "width": 8, "height": 9, "unit": "ft"})
    assert r.status_code == 422
    r = user.put(f"/api/farms/{f['id']}/room", json={"length": 10, "width": 8, "height": 2, "unit": "ft"})
    assert r.status_code == 422 and "height" in r.json()["error"]["message"].lower()


def test_grid_endpoint_reference_room(farm):
    c, fid = farm
    g = c.get(f"/api/farms/{fid}/grid").json()
    assert (g["columns"], g["rows"], g["full_cells"]) == (10, 8, 80)
    assert g["counts"]["DOOR_CLEARANCE"] > 0


def test_obstacle_outside_room_rejected(farm):
    c, fid = farm
    r = c.post(f"/api/farms/{fid}/obstacles", json={"kind": "PILLAR", "x": 3.0, "y": 0, "w": 0.5, "d": 0.5})
    assert r.status_code == 422


def _save_best(c, fid, **cfg):
    gen = c.post(f"/api/farms/{fid}/layouts/generate", json=cfg).json()
    assert gen["feasible"], gen
    best = gen["options"][0]
    r = c.post(f"/api/farms/{fid}/designs", json={"name": "Plan A", "rack_config": gen["config"], "racks": best["racks"],
                                                  "strategy": best["strategy"]})
    assert r.status_code == 201, r.text
    return r.json()


def test_layout_save_reopen_and_invalid_edit(farm):
    c, fid = farm
    d = _save_best(c, fid)
    assert d["validation"]["valid"] and d["capacity"]["total"] > 0
    again = c.get(f"/api/designs/{d['id']}").json()
    assert [(r["x"], r["y"]) for r in again["racks"]] == [(r["x"], r["y"]) for r in d["racks"]]
    # move a rack onto the door zone → rejected, stored layout unchanged
    bad = [dict(r) for r in d["racks"]]
    bad[0].update(x=1.2, y=0.1)
    r = c.patch(f"/api/designs/{d['id']}", json={"racks": bad})
    assert r.status_code == 422 and r.json()["error"]["code"] == "LAYOUT_INVALID"
    assert any(v["code"] in ("DOOR_ZONE", "RACK_OVERLAP") for v in r.json()["error"]["details"]["violations"])
    assert c.get(f"/api/designs/{d['id']}").json()["racks"][0]["x"] == d["racks"][0]["x"]
    geo = c.get(f"/api/designs/{d['id']}/geometry").json()
    assert len(geo["racks"]) == len(d["racks"]) and geo["model_type"] == "PLANNING_MODEL"
    assert geo["racks"][0]["x"] == d["racks"][0]["x"]  # 2D/3D share stored coordinates


def test_infeasible_generation_explained(farm):
    c, fid = farm
    out = c.post(f"/api/farms/{fid}/layouts/generate", json={"rack_length_m": 5}).json()
    assert not out["feasible"] and out["diagnosis"]


def test_costs_edit_updates_total(farm):
    c, fid = farm
    d = _save_best(c, fid)
    costs = c.get(f"/api/designs/{d['id']}/costs").json()
    rack_line = next(i for i in costs["items"] if i["key"] == "racks")
    before = costs["totals"]["setup_total"]
    after = c.patch(f"/api/cost-items/{rack_line['id']}", json={"unit_price": rack_line["unit_price"] + 50}).json()
    assert after["totals"]["setup_total"] == round(before + 50 * rack_line["quantity"], 2)
    edited = next(i for i in after["items"] if i["key"] == "racks")
    assert edited["price_source"] == "USER_INPUT"
    added = c.post(f"/api/designs/{d['id']}/cost-items", json={"name": "Extra tray", "category": "Trays", "quantity": 2, "unit_price": 10}).json()
    assert added["totals"]["setup_total"] == round(after["totals"]["setup_total"] + 20, 2)


def test_market_price_unlocks_profitability(farm):
    c, fid = farm
    d = _save_best(c, fid)
    assert not c.get(f"/api/designs/{d['id']}/costs").json()["profitability"]["available"]
    assert c.post(f"/api/farms/{fid}/market-prices", json={"crop_slug": "leaf-lettuce", "price": 8.0}).json()["source_type"] == "USER_INPUT"
    p = c.get(f"/api/designs/{d['id']}/costs").json()["profitability"]
    assert p["available"] and p["price_source"]["type"] == "USER_INPUT"


def test_recommendations(farm):
    c, fid = farm
    _save_best(c, fid)
    r = c.get(f"/api/farms/{fid}/recommendations").json()
    assert r["results"] and r["top"]["suitable"] and "Rule-based" in r["method"]


def test_scenario_clone_compare_apply(farm):
    c, fid = farm
    d = _save_best(c, fid)
    s = c.post(f"/api/farms/{fid}/scenarios", json={"name": "Fewer racks", "changes": {"rack_count": 1, "levels": 5}}).json()
    res = s["result"]
    assert res["feasible"] and res["before"]["rack_count"] == d["rack_count"] and res["after"]["rack_count"] == 1
    assert res["delta"]["rack_count"] == 1 - d["rack_count"]
    # base design untouched
    assert c.get(f"/api/designs/{d['id']}").json()["rack_count"] == d["rack_count"]
    applied = c.post(f"/api/scenarios/{s['id']}/apply").json()
    designs = c.get(f"/api/farms/{fid}/designs").json()
    assert len(designs) == 2 and next(x for x in designs if x["id"] == applied["design_id"])["is_active"]
    bad = c.post(f"/api/farms/{fid}/scenarios", json={"name": "Huge", "changes": {"rack_length_m": 6}}).json()
    assert not bad["result"]["feasible"]
    assert c.post(f"/api/scenarios/{bad['id']}/apply").status_code == 409


def test_simulator_records_are_simulated_and_alerts(farm):
    c, fid = farm
    _save_best(c, fid)
    assert c.post(f"/api/farms/{fid}/simulator/start").json()["status"] == "RUNNING"
    out = c.post(f"/api/farms/{fid}/simulator/tick?count=5").json()
    assert len(out["records"]) == 5 and all(r["source_type"] == "SIMULATED" for r in out["records"])
    ts = [r["ts"] for r in out["records"]]
    assert ts == sorted(ts)
    assert c.post(f"/api/farms/{fid}/simulator/pause").json()["status"] == "PAUSED"
    t = c.post(f"/api/farms/{fid}/alerts/test").json()
    assert {a["metric"] for a in t["alerts_created"]} >= {"ph", "water_level_pct"}
    alerts = c.get(f"/api/farms/{fid}/alerts?status=OPEN").json()
    assert alerts and all(a["source_type"] == "RULE" and a["data_source"] == "SIMULATED" for a in alerts)
    assert c.patch(f"/api/alerts/{alerts[0]['id']}", json={"status": "ACKNOWLEDGED"}).json()["status"] == "ACKNOWLEDGED"
    series = c.get(f"/api/farms/{fid}/sensors/series?range=1h").json()
    assert series["count"] >= 6 and series["source_type"] == "SIMULATED"
    csv = c.get(f"/api/farms/{fid}/sensors/export.csv")
    assert csv.status_code == 200 and "SIMULATED" in csv.text
    assert c.post(f"/api/farms/{fid}/simulator/stop").json()["status"] == "STOPPED"


def test_thresholds_validation(farm):
    c, fid = farm
    r = c.put(f"/api/farms/{fid}/thresholds", json=[{"metric": "ph", "warn_min": 5.5, "crit_min": 6.0}])
    assert r.status_code == 422


def test_image_upload_and_rejection(farm):
    c, fid = farm
    buf = io.BytesIO()
    Image.new("RGB", (320, 240), (180, 170, 150)).save(buf, "PNG")
    r = c.post(f"/api/farms/{fid}/images", files={"file": ("../../etc/room.png", buf.getvalue(), "image/png")})
    assert r.status_code == 201, r.text
    img = r.json()
    assert img["original_name"] == "room.png" and img["analysis_status"] == "COMPLETE"
    assert img["analysis"]["object_detection"]["status"] == "NOT_ENABLED"
    assert c.get(img["url"]).status_code == 200
    bad = c.post(f"/api/farms/{fid}/images", files={"file": ("x.png", b"not an image", "image/png")})
    assert bad.status_code == 415
    assert c.delete(f"/api/images/{img['id']}").status_code == 204


def test_reports(farm):
    c, fid = farm
    _save_best(c, fid)
    rep = c.get(f"/api/farms/{fid}/report").json()
    assert rep["assumptions"] and rep["monitoring"]["source_type"] == "SIMULATED" and rep["grid"]["full_cells"] == 80
    pdf = c.get(f"/api/farms/{fid}/report.pdf")
    assert pdf.status_code == 200 and pdf.content[:4] == b"%PDF"
    assert "unit_price" in c.get(f"/api/farms/{fid}/bom.csv").text


def test_insights_sources(farm):
    c, fid = farm
    _save_best(c, fid)
    ins = c.post(f"/api/farms/{fid}/insights/refresh").json()
    assert ins and all(i["source_type"] in ("RULE", "USER_INPUT") for i in ins)


def test_duplicate_archive_delete(farm):
    c, fid = farm
    _save_best(c, fid)
    dup = c.post(f"/api/farms/{fid}/duplicate").json()
    assert dup["room"]["length_m"] and dup["design_count"] == 1
    assert c.patch(f"/api/farms/{dup['id']}", json={"status": "ARCHIVED"}).json()["status"] == "ARCHIVED"
    assert dup["id"] in [f["id"] for f in c.get("/api/farms?status=ARCHIVED").json()]
    assert c.delete(f"/api/farms/{dup['id']}").status_code == 204
    assert c.get(f"/api/farms/{dup['id']}").status_code == 404
