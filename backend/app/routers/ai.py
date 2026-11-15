import io
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from PIL import Image
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import AiSetting, CostItem, Design, Farm, MarketPrice, Obstacle, Room, RoomImage, User
from ..security import current_user
from ..services import ai as ai_svc
from ..services import farm_service as fs
from ..services import season as season_svc
from ..services.autoplan import plan as autoplan
from ..services.crops import recommend
from ..services.layout import RackConfig, RackIn

router = APIRouter(prefix="/api", tags=["ai, location & budget plan"])


# ================================================================ AI settings

class AiSettingsIn(BaseModel):
    provider: str = Field(pattern="^(gemini|anthropic|openai)$")
    api_key: str | None = Field(default=None, max_length=400)  # omit to keep the saved key
    model: str = Field(default="", max_length=120)
    web_search: bool = True


class AiTestIn(BaseModel):
    provider: str = Field(pattern="^(gemini|anthropic|openai)$")
    api_key: str | None = Field(default=None, max_length=400)


def _mask(k: str) -> str:
    return f"{k[:4]}…{k[-4:]}" if len(k) > 10 else "••••"


def ai_config(db: Session, user: User) -> dict | None:
    row = db.scalar(select(AiSetting).where(AiSetting.user_id == user.id))
    if row:
        return {"provider": row.provider, "key": row.api_key, "model": row.model or ai_svc.PROVIDERS[row.provider]["default_model"],
                "web_search": row.web_search, "origin": "USER"}
    s = get_settings()
    if s.ai_provider and s.ai_api_key:
        return {"provider": s.ai_provider, "key": s.ai_api_key, "model": s.ai_model or ai_svc.PROVIDERS[s.ai_provider]["default_model"],
                "web_search": True, "origin": "SERVER_ENV"}
    return None


def require_ai(db: Session, user: User) -> dict:
    cfg = ai_config(db, user)
    if not cfg:
        raise HTTPException(409, "AI is not set up yet. Add your API key in Settings → AI assistant.")
    return cfg


@router.get("/ai/settings")
def get_ai_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cfg = ai_config(db, user)
    return {"configured": bool(cfg), "provider": cfg and cfg["provider"], "model": cfg and cfg["model"], "web_search": cfg["web_search"] if cfg else True,
            "key_hint": _mask(cfg["key"]) if cfg else None, "origin": cfg and cfg["origin"],
            "providers": [{"id": k, **v} for k, v in ai_svc.PROVIDERS.items()]}


@router.put("/ai/settings")
def put_ai_settings(body: AiSettingsIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(AiSetting).where(AiSetting.user_id == user.id))
    key = (body.api_key or "").strip() or (row.api_key if row and row.provider == body.provider else None)
    if not key:
        raise HTTPException(422, "Enter the API key for this provider.")
    if row:
        row.provider, row.api_key, row.model, row.web_search = body.provider, key, body.model.strip(), body.web_search
    else:
        db.add(AiSetting(user_id=user.id, provider=body.provider, api_key=key, model=body.model.strip(), web_search=body.web_search))
    fs.log(db, user, None, "ai.settings", body.provider)
    db.commit()
    return get_ai_settings(user, db)


@router.delete("/ai/settings", status_code=204)
def delete_ai_settings(user: User = Depends(current_user), db: Session = Depends(get_db)):
    row = db.scalar(select(AiSetting).where(AiSetting.user_id == user.id))
    if row:
        db.delete(row)
        db.commit()


@router.post("/ai/test")
def test_ai(body: AiTestIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    key = (body.api_key or "").strip()
    if not key:
        cfg = ai_config(db, user)
        if not cfg or cfg["provider"] != body.provider:
            raise HTTPException(422, "Enter the API key to test.")
        key = cfg["key"]
    try:
        models = ai_svc.list_models(body.provider, key)
    except ai_svc.AIError as e:
        raise HTTPException(400, str(e)) from None
    row = db.scalar(select(AiSetting).where(AiSetting.user_id == user.id))
    if row and row.provider == body.provider:
        row.last_ok_at = datetime.now(timezone.utc)
        db.commit()
    return {"ok": True, "models": models[:200], "default_model": ai_svc.PROVIDERS[body.provider]["default_model"]}


# ================================================================ location & season

class LocationIn(BaseModel):
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    name: str | None = Field(default=None, max_length=160)
    source: str = Field(default="USER_INPUT", pattern="^(BROWSER_GPS|USER_INPUT)$")


@router.put("/farms/{farm_id}/location")
def set_location(farm_id: int, body: LocationIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    lat, lon, name = body.latitude, body.longitude, (body.name or "").strip() or None
    if (lat is None or lon is None) and name:
        g = season_svc.geocode(name)
        if not g:
            raise HTTPException(422, f"Couldn't find “{name}”. Try a nearby city name.")
        lat, lon, name = g["latitude"], g["longitude"], g["name"]
    if lat is None or lon is None:
        raise HTTPException(422, "Allow location access or type your city.")
    if not name:
        name = season_svc.reverse_geocode(lat, lon) or f"{lat:.3f}, {lon:.3f}"
    f.latitude, f.longitude, f.location_name, f.location_source = round(lat, 4), round(lon, 4), name, body.source
    if f.room and not f.room.market_location:
        f.room.market_location = name[:160]
    fs.log(db, user, f.id, "location.set", name)
    db.commit()
    return season_view(f, db)


def season_view(f: Farm, db: Session) -> dict:
    s = season_svc.season_for(f.latitude, f.longitude)
    w = season_svc.weather(f.latitude, f.longitude) if f.latitude is not None else None
    fits = []
    for c in fs.all_crops(db):
        score, why = season_svc.crop_season_fit(c, s["code"], w["mean_temp_c"] if w else None)
        fits.append({"slug": c["slug"], "name": c["name"], "fit": round(score, 2), "why": why})
    fits.sort(key=lambda x: -x["fit"])
    return {"location": {"name": f.location_name, "latitude": f.latitude, "longitude": f.longitude, "source": f.location_source},
            "season": s, "weather": w, "crop_fit": fits, "date": date.today().isoformat()}


@router.get("/farms/{farm_id}/season")
def get_season(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return season_view(fs.get_farm(db, farm_id, user), db)


# ================================================================ photo → room info

def _image_for_ai(img: RoomImage) -> tuple[bytes, str]:
    p = Path(get_settings().storage_dir) / img.stored_name
    im = Image.open(p)
    im = im.convert("RGB")
    im.thumbnail((1600, 1600))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


def _num(v, lo, hi):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return None
    return round(v, 3) if lo <= v <= hi else None


def clean_room_analysis(raw: dict) -> dict:
    room = raw.get("room") or {}
    objs = []
    for o in raw.get("objects") or []:
        kind = str(o.get("kind", "")).upper()
        if kind not in {"DOOR", "WINDOW", "PILLAR", "FURNITURE", "EQUIPMENT", "FIXED"}:
            continue
        objs.append({"kind": kind, "label": str(o.get("label") or kind.title())[:80], "wall": str(o.get("wall") or "NONE").upper()[:4],
                     "x_frac": min(1.0, max(0.0, _num(o.get("x_frac"), -1, 2) or 0.0)), "y_frac": min(1.0, max(0.0, _num(o.get("y_frac"), -1, 2) or 0.0)),
                     "w_m": _num(o.get("w_m"), 0.02, 20) or 0.5, "d_m": _num(o.get("d_m"), 0.02, 20) or 0.5,
                     "height_m": _num(o.get("height_m"), 0.02, 20), "confidence": str(o.get("confidence") or "low")})
    light = raw.get("light") or {}
    return {
        "room": {"length_m": _num(room.get("length_m"), 0.5, 100), "width_m": _num(room.get("width_m"), 0.5, 100),
                 "height_m": _num(room.get("height_m"), 1.0, 20), "confidence": str(room.get("confidence") or "low"),
                 "basis": str(room.get("basis") or "")[:300]},
        "light": {"natural_light": str(light.get("natural_light") or "unknown"), "notes": str(light.get("notes") or "")[:300]},
        "floor": raw.get("floor"), "power_outlets_visible": raw.get("power_outlets_visible"), "water_source_visible": raw.get("water_source_visible"),
        "objects": objs[:20], "warnings": [str(w)[:200] for w in (raw.get("warnings") or [])][:10], "summary": str(raw.get("summary") or "")[:600],
    }


@router.post("/images/{image_id}/ai-analyze")
def ai_analyze(image_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    img = db.get(RoomImage, image_id)
    if not img:
        raise HTTPException(404, "Image not found")
    f = fs.get_farm(db, img.farm_id, user)
    cfg = require_ai(db, user)
    known = ""
    if f.room:
        known = (f"The owner measured the room as {f.room.length_m:.2f} m long × {f.room.width_m:.2f} m wide × {f.room.height_m:.2f} m high; "
                 "use these as the true scale and focus on objects, light and layout.")
    data, mime = _image_for_ai(img)
    try:
        res = ai_svc.generate(cfg["provider"], cfg["key"], cfg["model"], ai_svc.ROOM_PROMPT.format(known=known), data, mime, web_search=False)
        parsed = clean_room_analysis(ai_svc.extract_json(res.text))
    except ai_svc.AIError as e:
        raise HTTPException(502, str(e)) from None
    img.analysis = {**(img.analysis or {}), "ai": {**parsed, "provider": res.provider, "model": res.model, "source_type": "MODEL",
                                                    "analyzed_at": datetime.now(timezone.utc).isoformat()}}
    fs.log(db, user, f.id, "ai.photo", res.model)
    db.commit()
    return img.analysis["ai"]


class ApplyIn(BaseModel):
    dimensions: bool = True
    objects: bool = True
    unit: str = Field(default="ft", pattern="^(m|cm|ft|in)$")


@router.post("/images/{image_id}/ai-apply")
def ai_apply(image_id: int, body: ApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    img = db.get(RoomImage, image_id)
    if not img:
        raise HTTPException(404, "Image not found")
    f = fs.get_farm(db, img.farm_id, user)
    a = (img.analysis or {}).get("ai")
    if not a:
        raise HTTPException(409, "Run the AI photo analysis first.")
    r = a["room"]
    applied = {"dimensions": False, "objects": 0}
    if body.dimensions and r["length_m"] and r["width_m"] and r["height_m"]:
        L, W = max(r["length_m"], r["width_m"]), min(r["length_m"], r["width_m"])
        if f.room:
            f.room.length_m, f.room.width_m, f.room.height_m, f.room.input_unit = L, W, r["height_m"], body.unit
        else:
            f.room = Room(length_m=L, width_m=W, height_m=r["height_m"], input_unit=body.unit, grid_cell_m=0.3048 if body.unit in ("ft", "in") else 0.25,
                          grid_cell_input=1 if body.unit in ("ft", "in") else 0.25, grid_cell_unit="ft" if body.unit in ("ft", "in") else "m",
                          light_source="GROW_LIGHTS")
        f.room.notes = ((f.room.notes or "") + f"\nRoom size estimated by AI from a photo ({r['confidence']} confidence): {r['basis']}. Check with a tape measure.").strip()[:2000]
        applied["dimensions"] = True
        db.flush()
        fs.clamp_obstacles(f)
    if body.objects and f.room:
        for o in list(f.obstacles):
            if o.source == "MODEL" and not o.confirmed:
                db.delete(o)
        L, W = f.room.length_m, f.room.width_m
        for o in a["objects"]:
            w, d = min(o["w_m"], L), min(o["d_m"], W)
            x, y = o["x_frac"] * L, o["y_frac"] * W
            if o["kind"] in ("DOOR", "WINDOW"):
                t = 0.05
                if o["wall"] == "N":
                    y, d = 0, t
                elif o["wall"] == "S":
                    y, d = W - t, t
                elif o["wall"] == "W":
                    x, d, w = 0, max(d, w), t
                elif o["wall"] == "E":
                    x, d, w = L - t, max(d, w), t
                d, w = min(d, W), min(w, L)
            x, y = min(max(0, x), L - w), min(max(0, y), W - d)
            f.obstacles.append(Obstacle(kind=o["kind"], label=o["label"], x=round(x, 3), y=round(y, 3), w=round(w, 3), d=round(d, 3),
                                        height_m=o["height_m"], clearance_m=0.9 if o["kind"] == "DOOR" else 0.0, source="MODEL", confirmed=False))
            applied["objects"] += 1
    if a["light"]["natural_light"] in ("medium", "high") and f.room and f.room.light_source == "GROW_LIGHTS":
        f.room.light_source = "MIXED"
    fs.log(db, user, f.id, "ai.apply", f"{applied}")
    db.commit()
    return {"applied": applied, "farm": fs.ser_farm(f)}


# ================================================================ budget auto-plan

class AutoPlanIn(BaseModel):
    reserve_pct: float = Field(default=5, ge=0, le=50)
    crop_slug: str | None = None
    save: bool = True
    include_optional: bool = True


def _plan_crop(db: Session, f: Farm, slug: str | None) -> dict | None:
    active = next((d for d in f.designs if d.is_active), None)
    slug = slug or (active.crop_slug if active else None) or f.preferred_crop
    if slug:
        return fs.crop_dict(db, slug)
    recs = recommend(fs.all_crops(db), fs.crop_context(f, RackConfig().to_dict(), 1))
    return fs.crop_dict(db, recs["top"]["slug"]) if recs["top"] else None


def run_autoplan(db: Session, f: Farm, user: User, body: AutoPlanIn) -> dict:
    fs.require_room(f)
    if not f.budget:
        raise HTTPException(422, "Enter the customer's budget first (Room setup → Budget).")
    crop = _plan_crop(db, f, body.crop_slug)
    price = fs.latest_price(db, f, crop["slug"]) if crop else None
    res = autoplan(fs.context_for(f), f.budget, f.currency, f.fx_rate_per_usd or 1.0, f.electricity_rate, crop,
                   price.price if price else None, body.reserve_pct, include_optional=body.include_optional)
    res["crop"] = {"slug": crop["slug"], "name": crop["name"]} if crop else None
    if not res["feasible"] or not body.save:
        return res
    sym = "₹" if f.currency == "INR" else f.currency + " "
    d = Design(farm_id=f.id, name=f"Budget plan — {sym}{f.budget:,.0f}", rack_config=res["config"], crop_slug=crop["slug"] if crop else None,
               origin="BUDGET_PLAN", strategy=f"{res['rack_name']} · {res['strategy']}"[:200])
    f.designs.append(d)
    fs.replace_racks(d, [RackIn(**r) for r in res["racks"]])
    for it in res["items"]:
        d.cost_items.append(CostItem(**it))
    db.flush()
    fs.activate(db, f, d)
    old = sorted((x for x in f.designs if x.origin == "BUDGET_PLAN" and x.id != d.id), key=lambda x: x.id, reverse=True)
    for x in old[2:]:  # keep the two previous budget plans for comparison; older auto-plans are removed
        f.designs.remove(x)
        db.delete(x)
    fs.log(db, user, f.id, "budget.plan", f"{len(res['racks'])} racks, {res['setup_total']:.0f} {f.currency}")
    db.commit()
    res["design_id"] = d.id
    res.pop("items", None)
    return res


@router.post("/farms/{farm_id}/autoplan")
def autoplan_endpoint(farm_id: int, body: AutoPlanIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    res = run_autoplan(db, f, user, body)
    res.pop("items", None)
    return res


# ================================================================ AI crop advisor

def _candidates(db: Session, f: Farm) -> tuple[list[dict], dict]:
    """Rule engine first: only crops the system can physically grow are offered to the AI."""
    room = fs.require_room(f)
    rack_h = max(0.6, min(2.0, room.height_m - 0.3))
    cfg = RackConfig(rack_height_m=rack_h, levels=2).to_dict()  # lenient: crop fit is re-checked by the budget planner
    recs = recommend(fs.all_crops(db), fs.crop_context(f, cfg, 1))
    return [r for r in recs["results"] if r["suitable"]], recs


@router.post("/farms/{farm_id}/ai/crop-advice")
def crop_advice(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    cfg = require_ai(db, user)
    cands, _ = _candidates(db, f)
    if not cands:
        raise HTTPException(409, "No crop in the catalogue fits this room; check ceiling height and growing method.")
    sv = season_view(f, db)
    active = next((d for d in f.designs if d.is_active), None)
    plants = levels = "unknown"
    if active:
        ev = fs.ser_design(db, f, active)
        plants, levels = ev["capacity"].get("total") or "unknown", active.rack_config.get("levels")
    loc = f.location_name or (f.room.market_location if f.room else None) or "unknown (ask the user to enable location)"
    prompt = ai_svc.CROP_PROMPT.format(
        location=loc, lat=f.latitude, lon=f.longitude, date=date.today().isoformat(),
        season=f"{sv['season']['name']} — {sv['season']['detail']}" + (f" Outdoor 7-day mean {sv['weather']['mean_temp_c']} °C." if sv["weather"] else ""),
        budget=f"{f.budget:,.0f}" if f.budget else "not set", currency=f.currency, plants=plants, levels=levels,
        method=f.farming_type, temp=f"{f.room.temperature_c} °C" if f.room and f.room.temperature_c is not None else "unknown",
        experience=f.experience_level.lower(), candidates=", ".join(f"{c['slug']} ({c['name']})" for c in cands),
        search_line="Use web search to check CURRENT local mandi/wholesale and retail prices and demand trends; cite what you used."
        if cfg["web_search"] else "Web search is off: base prices on your knowledge, mark them as unverified and keep ranges wide.")
    try:
        res = ai_svc.generate(cfg["provider"], cfg["key"], cfg["model"], prompt, web_search=cfg["web_search"])
        raw = ai_svc.extract_json(res.text)
    except ai_svc.AIError as e:
        raise HTTPException(502, str(e)) from None
    valid = {c["slug"]: c for c in cands}
    recs = []
    for r in raw.get("recommendations") or []:
        slug = str(r.get("slug", ""))
        if slug not in valid:
            continue  # never recommend a crop the rule engine says cannot be grown here
        lo, hi = _num(r.get("price_per_kg_low"), 0.01, 1e6), _num(r.get("price_per_kg_high"), 0.01, 1e6)
        recs.append({"slug": slug, "name": valid[slug]["name"], "rank": len(recs) + 1, "why": str(r.get("why") or "")[:600],
                     "demand_trend": str(r.get("demand_trend") or "unknown"), "price_low": lo, "price_high": hi,
                     "price_basis": str(r.get("price_basis") or "")[:300], "best_selling_channel": str(r.get("best_selling_channel") or "")[:200],
                     "risk": str(r.get("risk") or "")[:300], "rule_score": valid[slug]["score"],
                     "season_fit": next((x["fit"] for x in sv["crop_fit"] if x["slug"] == slug), None)})
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "provider": res.provider, "model": res.model, "web_search": cfg["web_search"],
           "source_type": "MODEL", "sources": res.sources, "location": sv["location"], "season": sv["season"], "weather": sv["weather"],
           "season_summary": str(raw.get("season_summary") or "")[:800], "recommendations": recs,
           "trending_notes": [str(x)[:300] for x in (raw.get("trending_notes") or [])][:8],
           "avoid": [{"slug": str(a.get("slug")), "reason": str(a.get("reason") or "")[:300]} for a in (raw.get("avoid") or [])][:8],
           "disclaimer": str(raw.get("disclaimer") or "AI estimates — verify prices locally before investing.")[:400],
           "currency": f.currency}
    if not recs:
        raise HTTPException(502, "The AI did not return usable crop suggestions. Try again.")
    f.ai_crop_advice = out
    fs.log(db, user, f.id, "ai.crops", res.model)
    db.commit()
    return out


@router.get("/farms/{farm_id}/ai/crop-advice")
def last_crop_advice(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return fs.get_farm(db, farm_id, user).ai_crop_advice or None


class AdviceApplyIn(BaseModel):
    slug: str
    reserve_pct: float = Field(default=5, ge=0, le=50)


@router.post("/farms/{farm_id}/ai/crop-advice/apply")
def apply_advice(farm_id: int, body: AdviceApplyIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Choose a crop, record the AI price estimate (labelled), and re-run the budget planner for that crop."""
    f = fs.get_farm(db, farm_id, user)
    if not fs.crop_dict(db, body.slug):
        raise HTTPException(422, "Unknown crop")
    rec = next((r for r in (f.ai_crop_advice or {}).get("recommendations", []) if r["slug"] == body.slug), None)
    if rec and rec.get("price_low") and rec.get("price_high"):
        db.add(MarketPrice(farm_id=f.id, crop_slug=body.slug, price=round((rec["price_low"] + rec["price_high"]) / 2, 2), currency=f.currency,
                           location=f.location_name, grade=f"AI estimate ({rec['price_low']:g}–{rec['price_high']:g}/kg)"[:60],
                           source_type="AI_ESTIMATE", observed_on=date.today().isoformat()))
    f.preferred_crop = body.slug
    db.flush()
    return run_autoplan(db, f, user, AutoPlanIn(crop_slug=body.slug, reserve_pct=body.reserve_pct))


@router.get("/geo/search")
def geo_search(q: str = Query(min_length=2, max_length=120), user: User = Depends(current_user)):
    g = season_svc.geocode(q)
    if not g:
        raise HTTPException(404, "Place not found")
    return g
