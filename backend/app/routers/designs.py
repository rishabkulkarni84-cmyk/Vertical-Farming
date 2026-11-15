from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CostItem, Design, User
from ..schemas import CostItemIn, CostItemPatch, DesignIn, DesignPatch, RackConfigIn, ValidateIn
from ..security import current_user
from ..services import farm_service as fs
from ..services.layout import RackConfig, RackIn, generate_layouts, validate_layout

router = APIRouter(prefix="/api", tags=["layout & design"])

DEFAULT_HEIGHTS = {"DOOR": 2.1, "WINDOW": 1.2, "PILLAR": None, "FURNITURE": 0.8, "EQUIPMENT": 1.0, "FIXED": 1.0, "RESTRICTED": 0.02}


def _cfg(body: RackConfigIn | dict | None) -> RackConfig:
    try:
        return RackConfig.from_dict(body.model_dump() if isinstance(body, RackConfigIn) else body)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


def _racks(rs) -> list[RackIn]:
    return [RackIn(**r.model_dump()) for r in rs]


def _invalid(val) -> JSONResponse:
    return JSONResponse(status_code=422, content={"error": {
        "code": "LAYOUT_INVALID", "message": "Layout violates hard constraints and was not saved.",
        "details": {"violations": val.violations, "warnings": val.warnings}}})


def _over_budget(db, f, cfg, racks, crop_slug):
    """Budget is a hard limit: a layout whose estimated setup cost exceeds the farm budget is not saved."""
    if f.budget is None:
        return None
    ev = fs.evaluate(db, f, cfg, racks, crop_slug)
    if ev["cost_totals"]["setup_total"] <= f.budget + 1e-6:
        return None
    from ..services.layout import ValidationResult
    return ValidationResult(valid=False, violations=[v for v in ev["validation"]["violations"] if v["code"] == "OVER_BUDGET"])


@router.post("/farms/{farm_id}/layouts/generate")
def generate(farm_id: int, body: RackConfigIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    cfg = _cfg(body)
    out = generate_layouts(fs.context_for(f), cfg)
    crop_slug = f.preferred_crop
    for o in out["options"]:
        ev = fs.evaluate(db, f, cfg, [RackIn(**r) for r in o["racks"]], crop_slug)
        o["capacity"] = ev["capacity"]
        o["setup_cost"] = ev["cost_totals"]["setup_total"]
        o["over_budget"] = ev["over_budget"]
    out["config"] = cfg.to_dict()
    return out


@router.get("/farms/{farm_id}/designs")
def list_designs(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    return [fs.ser_design(db, f, d, full=False) for d in f.designs]


@router.post("/farms/{farm_id}/designs", status_code=201)
def save_design(farm_id: int, body: DesignIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    cfg = _cfg(body.rack_config)
    racks = _racks(body.racks)
    val = validate_layout(fs.context_for(f), cfg, racks)
    if not val.valid:
        return _invalid(val)
    prev_crop = next((x.crop_slug for x in f.designs if x.is_active), None)
    over = _over_budget(db, f, cfg, racks, body.crop_slug or f.preferred_crop or prev_crop)
    if over:
        return _invalid(over)
    racks = [RackIn(r.label, r.x, r.y, r.w, r.d, r.rotation, val.aisles.get(r.label, {}).get("side")) for r in racks]
    prev = next((x for x in f.designs if x.is_active), None)
    crop_slug = body.crop_slug or f.preferred_crop or (prev.crop_slug if prev else None)
    d = Design(farm_id=f.id, name=body.name, rack_config=cfg.to_dict(), crop_slug=crop_slug,
               origin="GENERATED", strategy=(body.strategy or "")[:200] or None)
    f.designs.append(d)
    fs.replace_racks(d, racks)
    db.flush()
    if body.activate or len(f.designs) == 1:
        fs.activate(db, f, d)
    fs.sync_bom(db, f, d)
    fs.log(db, user, f.id, "design.save", f"{d.name}: {len(racks)} racks")
    db.commit()
    return fs.ser_design(db, f, d)


@router.get("/designs/{design_id}")
def get_design(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    return fs.ser_design(db, fs.get_farm(db, d.farm_id, user), d)


@router.patch("/designs/{design_id}")
def patch_design(design_id: int, body: DesignPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    cfg = _cfg(body.rack_config) if body.rack_config else RackConfig.from_dict(d.rack_config)
    racks = _racks(body.racks) if body.racks is not None else fs.design_racks(d)
    if body.racks is not None or body.rack_config is not None:
        val = validate_layout(fs.context_for(f), cfg, racks)
        if not val.valid:
            return _invalid(val)
        over = _over_budget(db, f, cfg, racks, d.crop_slug)
        if over:
            return _invalid(over)
        racks = [RackIn(r.label, r.x, r.y, r.w, r.d, r.rotation, val.aisles.get(r.label, {}).get("side")) for r in racks]
        fs.replace_racks(d, racks)
        d.rack_config = cfg.to_dict()
        d.origin = "EDITED"
    if body.name is not None:
        d.name = body.name
    if "crop_slug" in body.model_fields_set:
        if body.crop_slug and not fs.crop_dict(db, body.crop_slug):
            raise HTTPException(422, "Unknown crop")
        d.crop_slug = body.crop_slug
    db.flush()
    fs.sync_bom(db, f, d)
    fs.log(db, user, f.id, "design.update", d.name)
    db.commit()
    return fs.ser_design(db, f, d)


@router.post("/designs/{design_id}/validate")
def validate(design_id: int, body: ValidateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    cfg = _cfg(body.rack_config) if body.rack_config else RackConfig.from_dict(d.rack_config)
    return fs.evaluate(db, f, cfg, _racks(body.racks), d.crop_slug)


@router.post("/farms/{farm_id}/layouts/validate")
def validate_unsaved(farm_id: int, body: ValidateIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    return fs.evaluate(db, f, _cfg(body.rack_config), _racks(body.racks), f.preferred_crop)


@router.post("/designs/{design_id}/activate")
def activate(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    fs.activate(db, f, d)
    db.commit()
    return fs.ser_design(db, f, d, full=False)


@router.post("/designs/{design_id}/duplicate", status_code=201)
def duplicate(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    nd = Design(farm_id=f.id, name=f"{d.name} (copy)"[:120], rack_config=dict(d.rack_config), crop_slug=d.crop_slug,
                origin=d.origin, strategy=d.strategy)
    f.designs.append(nd)
    fs.replace_racks(nd, fs.design_racks(d))
    db.flush()
    fs.sync_bom(db, f, nd)
    db.commit()
    return fs.ser_design(db, f, nd, full=False)


@router.delete("/designs/{design_id}", status_code=204)
def delete_design(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    was_active = d.is_active
    db.delete(d)
    db.flush()
    if was_active:
        rest = [x for x in f.designs if x.id != design_id]
        if rest:
            fs.activate(db, f, rest[-1])
    db.commit()


@router.get("/designs/{design_id}/geometry")
def geometry(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Single source of truth for the 2D plan and the 3D planning model."""
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    room = fs.require_room(f)
    ctx = fs.context_for(f)
    cfg = RackConfig.from_dict(d.rack_config)
    racks = fs.design_racks(d)
    val = validate_layout(ctx, cfg, racks)
    crop = fs.crop_dict(db, d.crop_slug)
    from ..services.capacity import capacity
    cap = capacity(cfg, len(racks), crop)
    gap = cfg.effective_level_gap
    zones = ([{"type": "ACCESS", "kind": z.kind, "label": z.label, "obstacle_id": z.obstacle_id, **z.rect.to_dict()} for z in ctx.access])
    return {
        "units": "m", "origin": "room top-left corner; +x length, +y width, +z up",
        "room": {"length": room.length_m, "width": room.width_m, "height": room.height_m},
        "obstacles": [{**fs.ser_obstacle(o), "render_height": o.height_m or DEFAULT_HEIGHTS.get(o.kind) or room.height_m} for o in f.obstacles],
        "access_zones": zones,
        "racks": [{"label": r.label, "x": r.x, "y": r.y, "w": r.w, "d": r.d, "rotation": r.rotation, "height": cfg.rack_height_m,
                   "access_side": val.aisles.get(r.label, {}).get("side"),
                   "levels": [round(cfg.base_clearance_m + i * gap, 4) for i in range(cfg.levels)]} for r in racks],
        "aisles": [{"rack": k, **v["rect"]} for k, v in val.aisles.items()],
        "planting": {"per_row": cap.get("per_row"), "per_col": cap.get("per_col"), "plants_per_level": cap.get("plants_per_level"),
                     "spacing_m": cap.get("spacing_m"), "edge_margin_m": cfg.edge_margin_m, "crop": crop["name"] if crop else None},
        "lights": {"per_level": True, "fixture_drop_m": 0.05},
        "validation": {"valid": val.valid, "violations": val.violations, "warnings": val.warnings},
        "model_type": "PLANNING_MODEL",
        "model_note": "Generated from saved design coordinates; not connected to live hardware (not a digital twin).",
    }


@router.get("/designs/{design_id}/capacity")
def get_capacity(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    from ..services.capacity import capacity
    return capacity(RackConfig.from_dict(d.rack_config), len(d.racks), fs.crop_dict(db, d.crop_slug))


# ---------------------------------------------------------------- costs / BOM

def _cost_view(db, f, d) -> dict:
    ev = fs.ser_design(db, f, d)
    return {"design_id": d.id, "currency": f.currency, "fx_rate_per_usd": f.fx_rate_per_usd,
            "items": [fs.ser_cost(i) for i in d.cost_items], "totals": ev["cost_totals"], "resources": ev["resources"],
            "profitability": ev["profitability"], "budget": f.budget, "over_budget": ev["over_budget"],
            "capacity": ev["capacity"], "crop": ev["crop"],
            "price_note": "ILLUSTRATIVE prices are planning placeholders converted at your exchange-rate assumption; replace them with real quotes."}


@router.get("/designs/{design_id}/costs")
def get_costs(design_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    if not d.cost_items:
        fs.sync_bom(db, f, d)
        db.commit()
    return _cost_view(db, f, d)


@router.post("/designs/{design_id}/costs/regenerate")
def regenerate_costs(design_id: int, reset: bool = False, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    if reset:
        d.cost_items.clear()
        db.flush()
    fs.sync_bom(db, f, d)
    db.commit()
    return _cost_view(db, f, d)


@router.post("/designs/{design_id}/cost-items", status_code=201)
def add_cost(design_id: int, body: CostItemIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    d = fs.get_design(db, design_id, user)
    f = fs.get_farm(db, d.farm_id, user)
    d.cost_items.append(CostItem(**body.model_dump(), currency=f.currency, price_source="USER_INPUT", quantity_locked=True))
    db.commit()
    return _cost_view(db, f, d)


def _own_cost(db, item_id, user) -> tuple[CostItem, Design]:
    i = db.get(CostItem, item_id)
    if not i:
        raise HTTPException(404, "Cost item not found")
    return i, fs.get_design(db, i.design_id, user)


@router.patch("/cost-items/{item_id}")
def patch_cost(item_id: int, body: CostItemPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i, d = _own_cost(db, item_id, user)
    data = body.model_dump(exclude_unset=True)
    for k, v in data.items():
        setattr(i, k, v)
    if "unit_price" in data:
        i.price_source, i.source_date = "USER_INPUT", None
    if "quantity" in data:
        i.quantity_locked = True
    db.commit()
    return _cost_view(db, fs.get_farm(db, d.farm_id, user), d)


@router.delete("/cost-items/{item_id}")
def delete_cost(item_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i, d = _own_cost(db, item_id, user)
    db.delete(i)
    db.commit()
    db.refresh(d)
    return _cost_view(db, fs.get_farm(db, d.farm_id, user), d)
