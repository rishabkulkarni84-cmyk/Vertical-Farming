"""Composition layer: loads owned resources and evaluates a design end-to-end."""
from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import (ActivityEvent, CostItem, Crop, Design, Farm, MarketPrice, Obstacle, RackPlacement, Room, Scenario,
                      User)
from . import costs as cost_svc
from .capacity import capacity
from .crops import recommend
from .layout import RackConfig, RackIn, generate_layouts, validate_layout
from .spatial import build_context
from .units import from_m


# ------------------------------------------------------------- ownership

def get_farm(db: Session, farm_id: int, user: User) -> Farm:
    farm = db.get(Farm, farm_id)
    if not farm or farm.owner_id != user.id:
        raise HTTPException(404, "Farm not found")
    return farm


def get_design(db: Session, design_id: int, user: User) -> Design:
    d = db.get(Design, design_id)
    if not d:
        raise HTTPException(404, "Design not found")
    get_farm(db, d.farm_id, user)
    return d


def require_room(farm: Farm) -> Room:
    if not farm.room:
        raise HTTPException(409, "Enter room dimensions first (Room setup).")
    return farm.room


def log(db: Session, user: User | None, farm_id: int | None, action: str, detail: str = "") -> None:
    db.add(ActivityEvent(user_id=user.id if user else None, farm_id=farm_id, action=action, detail=detail[:300]))


# ------------------------------------------------------------- serializers

def ser_farm(f: Farm) -> dict:
    active = next((d for d in f.designs if d.is_active), None)
    return {
        "id": f.id, "name": f.name, "status": f.status, "farming_type": f.farming_type, "budget": f.budget,
        "currency": f.currency, "fx_rate_per_usd": f.fx_rate_per_usd, "electricity_rate": f.electricity_rate,
        "preferred_crop": f.preferred_crop, "crop_categories": f.crop_categories, "experience_level": f.experience_level,
        "automation_level": f.automation_level, "priorities": f.priorities, "desired_plant_count": f.desired_plant_count,
        "is_sample": f.is_sample, "wizard_step": f.wizard_step,
        "created_at": f.created_at.isoformat(), "updated_at": f.updated_at.isoformat(),
        "room": ser_room(f.room) if f.room else None,
        "active_design_id": active.id if active else None, "design_count": len(f.designs),
        "obstacle_count": len(f.obstacles), "image_count": len(f.images),
        "location": {"name": f.location_name, "latitude": f.latitude, "longitude": f.longitude, "source": f.location_source}
        if f.latitude is not None else None,
    }


def ser_room(r: Room) -> dict:
    u = r.input_unit
    return {
        "length_m": r.length_m, "width_m": r.width_m, "height_m": r.height_m, "input_unit": u,
        "length": round(from_m(r.length_m, u), 4), "width": round(from_m(r.width_m, u), 4), "height": round(from_m(r.height_m, u), 4),
        "grid_cell_m": r.grid_cell_m, "grid_cell": r.grid_cell_input, "grid_cell_unit": r.grid_cell_unit,
        "temperature_c": r.temperature_c, "humidity_pct": r.humidity_pct, "light_source": r.light_source,
        "water_access": r.water_access, "electrical_access": r.electrical_access,
        "market_location": r.market_location, "notes": r.notes,
        "floor_area_m2": round(r.length_m * r.width_m, 3),
    }


def ser_obstacle(o: Obstacle) -> dict:
    return {"id": o.id, "kind": o.kind, "label": o.label, "x": o.x, "y": o.y, "w": o.w, "d": o.d, "height_m": o.height_m,
            "clearance_m": o.clearance_m, "source": o.source, "confirmed": o.confirmed}


def ser_rack(r: RackPlacement) -> dict:
    return {"id": r.id, "label": r.label, "x": r.x, "y": r.y, "w": r.w, "d": r.d, "rotation": r.rotation, "access_side": r.access_side}


def ser_cost(i: CostItem) -> dict:
    return {k: getattr(i, k) for k in ("id", "key", "name", "category", "quantity", "unit", "unit_price", "currency", "price_source",
                                        "source_date", "cost_type", "status", "included", "quantity_locked", "notes")} | {
        "subtotal": round(i.quantity * i.unit_price, 2)}


# ------------------------------------------------------------- crops

def crop_dict(db: Session, slug: str | None) -> dict | None:
    if not slug:
        return None
    c = db.get(Crop, slug)
    return ({**c.data, "slug": c.slug, "name": c.name, "category": c.category} if c else None)


def all_crops(db: Session) -> list[dict]:
    return [{**c.data, "slug": c.slug, "name": c.name, "category": c.category}
            for c in db.scalars(select(Crop).order_by(Crop.name))]


def crop_context(farm: Farm, cfg: dict, rack_count: int, overrides: dict | None = None) -> dict:
    r = farm.room
    o = overrides or {}
    return {
        "farming_type": o.get("farming_type") or farm.farming_type,
        "temperature_c": r.temperature_c if r else None, "humidity_pct": r.humidity_pct if r else None,
        "light_source": r.light_source if r else "UNKNOWN", "experience_level": farm.experience_level,
        "preferred_crop": o.get("crop_slug") or farm.preferred_crop, "crop_categories": farm.crop_categories,
        "rack_config": cfg, "rack_count": rack_count,
    }


# ------------------------------------------------------------- design evaluation

def context_for(farm: Farm):
    room = require_room(farm)
    return build_context(room.length_m, room.width_m, room.height_m, farm.obstacles)


def latest_price(db: Session, farm: Farm, slug: str | None) -> MarketPrice | None:
    if not slug:
        return None
    return db.scalars(select(MarketPrice).where(MarketPrice.farm_id == farm.id, MarketPrice.crop_slug == slug,
                                                MarketPrice.currency == farm.currency)
                      .order_by(MarketPrice.created_at.desc())).first()


def clamp_obstacles(farm: Farm) -> int:
    """Keep every obstacle inside the room after a resize; returns how many were moved or shrunk."""
    r = farm.room
    if not r:
        return 0
    changed = 0
    for o in farm.obstacles:
        w, d = min(o.w, r.length_m), min(o.d, r.width_m)
        x, y = min(max(0.0, o.x), r.length_m - w), min(max(0.0, o.y), r.width_m - d)
        if (x, y, w, d) != (o.x, o.y, o.w, o.d):
            o.x, o.y, o.w, o.d = round(x, 4), round(y, 4), round(w, 4), round(d, 4)
            changed += 1
    return changed


def evaluate(db: Session, farm: Farm, cfg: RackConfig, racks: list[RackIn], crop_slug: str | None,
             overrides: dict | None = None, items: list | None = None) -> dict:
    """Full, recomputed picture of a (possibly unsaved) design."""
    ctx = context_for(farm)
    val = validate_layout(ctx, cfg, racks)
    crop = crop_dict(db, crop_slug)
    cap = capacity(cfg, len(racks), crop)
    res = cost_svc.resources(cfg, len(racks), cap.get("total"), crop)
    fx = farm.fx_rate_per_usd or 1.0
    if items is None:
        items = cost_svc.generate_bom(cfg, len(racks), cap.get("total"), crop, farm.currency, fx, farm.electricity_rate)
    tot = cost_svc.totals(items)
    price = latest_price(db, farm, crop_slug)
    prof = cost_svc.profitability(cap.get("total"), crop, price.price if price else None, tot["monthly_total"], tot["setup_total"])
    if price:
        prof["price_source"] = {"type": price.source_type, "price": price.price, "currency": price.currency,
                                "location": price.location, "observed_on": price.observed_on}
    budget = (overrides or {}).get("budget", farm.budget)
    if budget is not None and tot["setup_total"] > budget + 1e-6:
        val.violations.append({"code": "OVER_BUDGET", "rack": None,
                               "message": f"Setup cost {tot['setup_total']:,.0f} {farm.currency} is over the budget of {budget:,.0f} {farm.currency}. "
                                          "Remove racks or levels, or use the budget planner."})
        val.valid = False
    suit = None
    if crop:
        from .crops import score_crop
        suit = score_crop(crop, crop_context(farm, cfg.to_dict(), len(racks), overrides))
    from .layout import _metrics
    return {
        "validation": {"valid": val.valid, "violations": val.violations, "warnings": val.warnings, "aisles": val.aisles},
        "metrics": _metrics(ctx, racks, val.aisles),
        "capacity": cap, "resources": res, "cost_totals": tot, "profitability": prof,
        "budget": budget, "over_budget": bool(budget is not None and tot["setup_total"] > budget),
        "crop": {"slug": crop["slug"], "name": crop["name"]} if crop else None,
        "crop_suitability": {"score": suit["score"], "suitable": suit["suitable"], "blockers": suit["blockers"]} if suit else None,
    }


def design_racks(d: Design) -> list[RackIn]:
    return [RackIn(r.label, r.x, r.y, r.w, r.d, r.rotation, r.access_side) for r in d.racks]


def ser_design(db: Session, farm: Farm, d: Design, full: bool = True) -> dict:
    base = {"id": d.id, "farm_id": d.farm_id, "name": d.name, "is_active": d.is_active, "rack_config": d.rack_config,
            "crop_slug": d.crop_slug, "origin": d.origin, "strategy": d.strategy, "rack_count": len(d.racks),
            "created_at": d.created_at.isoformat(), "updated_at": d.updated_at.isoformat()}
    if not full:
        return base
    cfg = RackConfig.from_dict(d.rack_config)
    ev = evaluate(db, farm, cfg, design_racks(d), d.crop_slug, items=d.cost_items or None)
    return {**base, "racks": [ser_rack(r) for r in d.racks], **ev}


def sync_bom(db: Session, farm: Farm, d: Design) -> None:
    """Create or refresh auto-generated BOM lines; keeps user-edited prices and locked quantities."""
    cfg = RackConfig.from_dict(d.rack_config)
    crop = crop_dict(db, d.crop_slug)
    cap = capacity(cfg, len(d.racks), crop)
    lines = cost_svc.generate_bom(cfg, len(d.racks), cap.get("total"), crop, farm.currency, farm.fx_rate_per_usd or 1.0,
                                  farm.electricity_rate)
    existing = {i.key: i for i in d.cost_items if i.key}
    for ln in lines:
        it = existing.get(ln["key"])
        if it is None:
            d.cost_items.append(CostItem(**ln))
            continue
        it.name = ln["name"]
        if not it.quantity_locked:
            it.quantity = ln["quantity"]
        if it.price_source == "ILLUSTRATIVE" or (ln["key"] == "electricity" and ln["price_source"] == "USER_INPUT"):
            it.unit_price, it.price_source, it.source_date, it.currency = ln["unit_price"], ln["price_source"], ln["source_date"], ln["currency"]


def replace_racks(d: Design, racks: list[RackIn]) -> None:
    d.racks.clear()
    for r in racks:
        d.racks.append(RackPlacement(label=r.label, x=r.x, y=r.y, w=r.w, d=r.d, rotation=r.rotation, access_side=r.access_side))


def activate(db: Session, farm: Farm, d: Design) -> None:
    for other in farm.designs:
        other.is_active = other.id == d.id
    d.is_active = True


# ------------------------------------------------------------- scenarios

def run_scenario(db: Session, farm: Farm, base: Design | None, changes: dict) -> dict:
    base_cfg = dict(base.rack_config) if base else RackConfig().to_dict()
    cfg_d = {**base_cfg}
    for k in ("rack_length_m", "rack_depth_m", "rack_height_m", "levels", "walkway_m", "plant_spacing_m", "orientation"):
        if changes.get(k) is not None:
            cfg_d[k] = changes[k]
    if changes.get("levels") is not None or changes.get("rack_height_m") is not None:
        cfg_d["level_gap_m"] = None
    if changes.get("rack_count"):
        cfg_d["max_racks"] = changes["rack_count"]
    crop_slug = changes.get("crop_slug") or (base.crop_slug if base else farm.preferred_crop)
    overrides = {k: changes[k] for k in ("budget", "farming_type", "crop_slug") if changes.get(k) is not None}
    try:
        cfg = RackConfig.from_dict(cfg_d)
    except ValueError as e:
        return {"feasible": False, "errors": [str(e)], "config": cfg_d}

    ctx = context_for(farm)
    gen = generate_layouts(ctx, cfg, max_options=1)
    before = None
    if base:
        b = evaluate(db, farm, RackConfig.from_dict(base.rack_config), design_racks(base), base.crop_slug)
        before = _summary(b, len(base.racks))
    if not gen["feasible"]:
        return {"feasible": False, "diagnosis": gen["diagnosis"], "config": cfg.to_dict(), "crop_slug": crop_slug,
                "before": before, "after": None, "errors": []}
    opt = gen["options"][0]
    racks = [RackIn(**r) for r in opt["racks"]]
    notes = []
    if changes.get("rack_count") and len(racks) < changes["rack_count"]:
        notes.append(f"Only {len(racks)} of the requested {changes['rack_count']} racks fit without breaking constraints.")
    ev = evaluate(db, farm, cfg, racks, crop_slug, overrides)
    after = _summary(ev, len(racks))
    return {"feasible": True, "config": cfg.to_dict(), "crop_slug": crop_slug, "strategy": opt["strategy"],
            "racks": opt["racks"], "before": before, "after": after, "notes": notes,
            "delta": {k: round(after[k] - before[k], 2) if before and isinstance(after.get(k), (int, float)) and isinstance(before.get(k), (int, float)) else None
                      for k in after},
            "validation": ev["validation"], "errors": []}


def _summary(ev: dict, rack_count: int) -> dict:
    p = ev["profitability"]
    return {
        "rack_count": rack_count, "plant_capacity": ev["capacity"].get("total"),
        "utilization_pct": ev["metrics"]["utilization_pct"], "setup_cost": ev["cost_totals"]["setup_total"],
        "monthly_cost": ev["cost_totals"]["monthly_total"], "energy_kwh_month": ev["resources"]["energy_kwh_month"],
        "water_l_month": ev["resources"]["water_l_month"],
        "crop_score": ev["crop_suitability"]["score"] if ev["crop_suitability"] else None,
        "monthly_margin": p.get("estimated_margin") if p.get("available") else None,
        "over_budget": ev["over_budget"], "valid": ev["validation"]["valid"],
    }


def ser_scenario(s: Scenario) -> dict:
    return {"id": s.id, "name": s.name, "base_design_id": s.base_design_id, "changes": s.changes, "result": s.result,
            "applied_design_id": s.applied_design_id, "applied_at": s.applied_at.isoformat() if s.applied_at else None,
            "created_at": s.created_at.isoformat(), "updated_at": s.updated_at.isoformat()}


def recommendations_for(db: Session, farm: Farm) -> dict:
    active = next((d for d in farm.designs if d.is_active), None)
    cfg = active.rack_config if active else RackConfig().to_dict()
    n = len(active.racks) if active else 0
    out = recommend(all_crops(db), crop_context(farm, cfg, n))
    out["design_id"] = active.id if active else None
    out["rack_count"] = n
    if not active:
        out["note"] = "No saved layout yet: capacity uses default rack settings and 0 racks."
    return out
