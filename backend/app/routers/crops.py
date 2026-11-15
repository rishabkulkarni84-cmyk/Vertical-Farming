from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import Crop, Design, MarketPrice, Scenario, User
from ..schemas import MarketPriceIn, ScenarioIn, ScenarioPatch
from ..security import current_user
from ..services import farm_service as fs
from ..services.crops import METHOD, WEIGHTS
from ..services.layout import RackIn

router = APIRouter(prefix="/api", tags=["crops, market & scenarios"])


@router.get("/crops")
def list_crops(user: User = Depends(current_user), db: Session = Depends(get_db)):
    cs = db.scalars(select(Crop).order_by(Crop.name)).all()
    return {"crops": [{**c.data, "slug": c.slug, "name": c.name, "category": c.category} for c in cs],
            "provenance": cs[0].provenance if cs else "", "last_reviewed": cs[0].last_reviewed if cs else None,
            "method": METHOD, "weights": WEIGHTS}


@router.get("/farms/{farm_id}/recommendations")
def recommendations(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    return fs.recommendations_for(db, f)


# ---------------------------------------------------------------- market

def ser_price(p: MarketPrice) -> dict:
    return {"id": p.id, "crop_slug": p.crop_slug, "price": p.price, "unit": p.unit, "currency": p.currency, "location": p.location,
            "grade": p.grade, "source_type": p.source_type, "observed_on": p.observed_on, "created_at": p.created_at.isoformat()}


@router.get("/market/status")
def market_status(user: User = Depends(current_user)):
    s = get_settings()
    return {"provider": "NONE", "configured": False,
            "message": ("A market API URL is set, but no provider adapter is implemented yet; using user-entered prices."
                        if s.market_api_url else
                        "No live market-price provider is configured. Enter your own price assumptions; they are labelled USER_INPUT.")}


@router.get("/farms/{farm_id}/market-prices")
def list_prices(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    fs.get_farm(db, farm_id, user)
    rows = db.scalars(select(MarketPrice).where(MarketPrice.farm_id == farm_id).order_by(MarketPrice.created_at.desc()))
    return [ser_price(p) for p in rows]


@router.post("/farms/{farm_id}/market-prices", status_code=201)
def add_price(farm_id: int, body: MarketPriceIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    if not db.get(Crop, body.crop_slug):
        raise HTTPException(422, "Unknown crop")
    p = MarketPrice(farm_id=f.id, currency=f.currency, source_type="USER_INPUT",
                    **{**body.model_dump(), "observed_on": body.observed_on or date.today().isoformat()})
    db.add(p)
    fs.log(db, user, f.id, "market.price", f"{body.crop_slug} {body.price}/{body.unit}")
    db.commit()
    return ser_price(p)


@router.delete("/market-prices/{pid}", status_code=204)
def delete_price(pid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    p = db.get(MarketPrice, pid)
    if not p:
        raise HTTPException(404, "Price not found")
    fs.get_farm(db, p.farm_id, user)
    db.delete(p)
    db.commit()


# ---------------------------------------------------------------- scenarios

def _base(db, f, base_id) -> Design | None:
    if base_id is None:
        return next((d for d in f.designs if d.is_active), None)
    d = db.get(Design, base_id)
    if not d or d.farm_id != f.id:
        raise HTTPException(404, "Base design not found")
    return d


@router.get("/farms/{farm_id}/scenarios")
def list_scenarios(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    fs.get_farm(db, farm_id, user)
    return [fs.ser_scenario(s) for s in db.scalars(select(Scenario).where(Scenario.farm_id == farm_id).order_by(Scenario.created_at.desc()))]


@router.post("/farms/{farm_id}/scenarios/preview")
def preview(farm_id: int, body: ScenarioIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    return fs.run_scenario(db, f, _base(db, f, body.base_design_id), body.changes.model_dump(exclude_none=True))


@router.post("/farms/{farm_id}/scenarios", status_code=201)
def create_scenario(farm_id: int, body: ScenarioIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    base = _base(db, f, body.base_design_id)
    changes = body.changes.model_dump(exclude_none=True)
    s = Scenario(farm_id=f.id, base_design_id=base.id if base else None, name=body.name, changes=changes,
                 result=fs.run_scenario(db, f, base, changes))
    db.add(s)
    fs.log(db, user, f.id, "scenario.create", body.name)
    db.commit()
    return fs.ser_scenario(s)


def _own_scenario(db, sid, user):
    s = db.get(Scenario, sid)
    if not s:
        raise HTTPException(404, "Scenario not found")
    return s, fs.get_farm(db, s.farm_id, user)


@router.patch("/scenarios/{sid}")
def patch_scenario(sid: int, body: ScenarioPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, f = _own_scenario(db, sid, user)
    if body.name:
        s.name = body.name
    if body.changes is not None:
        s.changes = body.changes.model_dump(exclude_none=True)
        s.result = fs.run_scenario(db, f, _base(db, f, s.base_design_id) if s.base_design_id else None, s.changes)
    db.commit()
    return fs.ser_scenario(s)


@router.post("/scenarios/{sid}/evaluate")
def reevaluate(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, f = _own_scenario(db, sid, user)
    base = db.get(Design, s.base_design_id) if s.base_design_id else None
    s.result = fs.run_scenario(db, f, base, s.changes)
    db.commit()
    return fs.ser_scenario(s)


@router.post("/scenarios/{sid}/apply")
def apply(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Creates a NEW design from the scenario and makes it active; the base design is kept unchanged."""
    s, f = _own_scenario(db, sid, user)
    base = db.get(Design, s.base_design_id) if s.base_design_id else None
    res = fs.run_scenario(db, f, base, s.changes)
    if not res.get("feasible"):
        raise HTTPException(409, "Scenario is not feasible and cannot be applied")
    if res.get("after", {}).get("over_budget"):
        raise HTTPException(409, "Scenario setup cost is over the budget and cannot be applied")
    d = Design(farm_id=f.id, name=f"{s.name} (from scenario)"[:120], rack_config=res["config"], crop_slug=res["crop_slug"],
               origin="SCENARIO", strategy=(res.get("strategy") or "")[:200] or None)
    f.designs.append(d)
    fs.replace_racks(d, [RackIn(**r) for r in res["racks"]])
    db.flush()
    fs.activate(db, f, d)
    if s.changes.get("farming_type"):
        f.farming_type = s.changes["farming_type"]
    if s.changes.get("budget") is not None:
        f.budget = s.changes["budget"]
    fs.sync_bom(db, f, d)
    s.result, s.applied_design_id, s.applied_at = res, d.id, datetime.now(timezone.utc)
    fs.log(db, user, f.id, "scenario.apply", s.name)
    db.commit()
    return {"scenario": fs.ser_scenario(s), "design_id": d.id}


@router.delete("/scenarios/{sid}", status_code=204)
def delete_scenario(sid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    s, _ = _own_scenario(db, sid, user)
    db.delete(s)
    db.commit()
