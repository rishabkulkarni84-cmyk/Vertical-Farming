import copy
import io
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from PIL import Image, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..config import get_settings
from ..db import get_db
from ..models import (ActivityEvent, Alert, CostItem, Design, Farm, Obstacle, RackPlacement, Room, RoomImage, SensorRecord,
                      SimulatorState, User)
from ..schemas import FarmIn, FarmPatch, ObstacleIn, ObstaclePatch, RoomIn
from ..security import current_user
from ..services import farm_service as fs
from ..services.geometry import Rect
from ..services.grid import compute_cells
from ..services.image_analysis import analyze
from ..services.layout import RackConfig, validate_layout
from ..services.units import to_m

router = APIRouter(prefix="/api", tags=["farms"])
ALLOWED_IMAGE = {"JPEG": ("image/jpeg", ".jpg"), "PNG": ("image/png", ".png"), "WEBP": ("image/webp", ".webp")}


@router.get("/dashboard")
def dashboard(user: User = Depends(current_user), db: Session = Depends(get_db)):
    farms = db.scalars(select(Farm).where(Farm.owner_id == user.id, Farm.status == "ACTIVE").order_by(Farm.updated_at.desc())).all()
    ids = [f.id for f in farms]
    open_alerts = db.scalar(select(func.count(Alert.id)).where(Alert.farm_id.in_(ids), Alert.status == "OPEN")) if ids else 0
    sims = {s.farm_id: s.status for s in db.scalars(select(SimulatorState).where(SimulatorState.farm_id.in_(ids)))} if ids else {}
    items = []
    for f in farms:
        active = next((d for d in f.designs if d.is_active), None)
        summary = None
        if active and f.room:
            ev = fs.ser_design(db, f, active)
            summary = {"rack_count": len(active.racks), "capacity": ev["capacity"].get("total"),
                       "utilization_pct": ev["metrics"]["utilization_pct"], "setup_total": ev["cost_totals"]["setup_total"],
                       "monthly_total": ev["cost_totals"]["monthly_total"], "crop": ev["crop"], "valid": ev["validation"]["valid"]}
        latest = db.scalars(select(SensorRecord).where(SensorRecord.farm_id == f.id).order_by(SensorRecord.ts.desc())).first()
        items.append({**fs.ser_farm(f), "summary": summary, "simulator": sims.get(f.id, "STOPPED"),
                      "open_alerts": db.scalar(select(func.count(Alert.id)).where(Alert.farm_id == f.id, Alert.status == "OPEN")),
                      "latest_reading": _ser_reading(latest) if latest else None})
    recent = db.scalars(select(ActivityEvent).where(ActivityEvent.user_id == user.id).order_by(ActivityEvent.created_at.desc()).limit(8)).all()
    return {"farms": items, "open_alerts": open_alerts or 0,
            "activity": [{"action": a.action, "detail": a.detail, "farm_id": a.farm_id, "created_at": a.created_at.isoformat()} for a in recent]}


def _ser_reading(r: SensorRecord) -> dict:
    return {"ts": r.ts.isoformat(), "source_type": r.source_type, "temperature_c": r.temperature_c, "humidity_pct": r.humidity_pct,
            "ph": r.ph, "ec_ms_cm": r.ec_ms_cm, "water_level_pct": r.water_level_pct}


# ---------------------------------------------------------------- farms CRUD

@router.get("/farms")
def list_farms(status: str = Query("ACTIVE", pattern="^(ACTIVE|ARCHIVED|ALL)$"), user: User = Depends(current_user),
               db: Session = Depends(get_db)):
    q = select(Farm).where(Farm.owner_id == user.id)
    if status != "ALL":
        q = q.where(Farm.status == status)
    return [fs.ser_farm(f) for f in db.scalars(q.order_by(Farm.updated_at.desc()))]


@router.post("/farms", status_code=201)
def create_farm(body: FarmIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = Farm(owner_id=user.id, **body.model_dump(exclude_none=True))
    db.add(f)
    db.flush()
    fs.log(db, user, f.id, "farm.create", f.name)
    db.commit()
    db.refresh(f)
    return fs.ser_farm(f)


@router.get("/farms/{farm_id}")
def get_farm(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return fs.ser_farm(fs.get_farm(db, farm_id, user))


@router.patch("/farms/{farm_id}")
def patch_farm(farm_id: int, body: FarmPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    data = body.model_dump(exclude_unset=True)
    if "currency" in data and data["currency"]:
        data["currency"] = data["currency"].upper()
    for k, v in data.items():
        setattr(f, k, v)
    fs.log(db, user, f.id, "farm.update", ", ".join(data))
    db.commit()
    if {"currency", "fx_rate_per_usd", "electricity_rate"} & set(data):
        for d in f.designs:
            for it in d.cost_items:
                if it.currency != f.currency:
                    if it.key:  # auto line: a price typed in another currency is meaningless now -> back to sample price
                        it.price_source = "ILLUSTRATIVE"
                    else:  # custom line: keep the number but tell the user to re-check it
                        it.notes = f"Price was entered in {it.currency}; check it in {f.currency}."[:255]
                    it.currency = f.currency
            fs.sync_bom(db, f, d)
        db.commit()
    return fs.ser_farm(f)


@router.post("/farms/{farm_id}/duplicate", status_code=201)
def duplicate_farm(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    src = fs.get_farm(db, farm_id, user)
    skip = {"id", "owner_id", "created_at", "updated_at", "name", "is_sample"}
    cols = {c.name: getattr(src, c.name) for c in Farm.__table__.columns if c.name not in skip}
    f = Farm(owner_id=user.id, name=f"{src.name} (copy)"[:120], **copy.deepcopy(cols))
    db.add(f)
    db.flush()
    if src.room:
        rc = {c.name: getattr(src.room, c.name) for c in Room.__table__.columns if c.name not in {"id", "farm_id", "created_at", "updated_at"}}
        f.room = Room(**rc)
    for o in src.obstacles:
        f.obstacles.append(Obstacle(**{c.name: getattr(o, c.name) for c in Obstacle.__table__.columns
                                       if c.name not in {"id", "farm_id", "created_at", "updated_at"}}))
    for d in src.designs:
        nd = Design(name=d.name, is_active=d.is_active, rack_config=copy.deepcopy(d.rack_config), crop_slug=d.crop_slug,
                    origin=d.origin, strategy=d.strategy)
        for r in d.racks:
            nd.racks.append(RackPlacement(label=r.label, x=r.x, y=r.y, w=r.w, d=r.d, rotation=r.rotation, access_side=r.access_side))
        for i in d.cost_items:
            nd.cost_items.append(CostItem(**{c.name: getattr(i, c.name) for c in CostItem.__table__.columns
                                             if c.name not in {"id", "design_id", "created_at", "updated_at"}}))
        f.designs.append(nd)
    fs.log(db, user, f.id, "farm.duplicate", f"from #{src.id}")
    db.commit()
    db.refresh(f)
    return fs.ser_farm(f)


@router.delete("/farms/{farm_id}", status_code=204)
def delete_farm(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    paths = [Path(get_settings().storage_dir) / i.stored_name for i in f.images]
    db.delete(f)
    fs.log(db, user, None, "farm.delete", f.name)
    db.commit()
    for p in paths:
        p.unlink(missing_ok=True)
        p.with_name(p.stem + "_edges.png").unlink(missing_ok=True)


@router.get("/farms/{farm_id}/activity")
def activity(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    fs.get_farm(db, farm_id, user)
    rows = db.scalars(select(ActivityEvent).where(ActivityEvent.farm_id == farm_id).order_by(ActivityEvent.created_at.desc()).limit(50))
    return [{"action": a.action, "detail": a.detail, "created_at": a.created_at.isoformat()} for a in rows]


# ---------------------------------------------------------------- room

@router.put("/farms/{farm_id}/room")
def put_room(farm_id: int, body: RoomIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    vals = dict(length_m=to_m(body.length, body.unit), width_m=to_m(body.width, body.unit), height_m=to_m(body.height, body.unit),
                input_unit=body.unit, grid_cell_m=to_m(body.grid_cell, body.grid_cell_unit), grid_cell_input=body.grid_cell,
                grid_cell_unit=body.grid_cell_unit, temperature_c=body.temperature_c, humidity_pct=body.humidity_pct,
                light_source=body.light_source, water_access=body.water_access, electrical_access=body.electrical_access,
                market_location=body.market_location, notes=body.notes)
    if f.room:
        for k, v in vals.items():
            setattr(f.room, k, v)
    else:
        f.room = Room(**vals)
    db.flush()
    moved = fs.clamp_obstacles(f)
    fs.log(db, user, f.id, "room.save", f"{body.length}×{body.width}×{body.height} {body.unit}" + (f"; {moved} obstacle(s) moved inside" if moved else ""))
    db.commit()
    return fs.ser_room(f.room)


@router.get("/farms/{farm_id}/room")
def get_room(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    if not f.room:
        raise HTTPException(404, "Room not set up yet")
    return fs.ser_room(f.room)


@router.get("/farms/{farm_id}/grid")
def grid(farm_id: int, cell_m: float | None = Query(None, gt=0.04), design_id: int | None = None,
         user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    room = fs.require_room(f)
    ctx = fs.context_for(f)
    d = next((x for x in f.designs if x.id == design_id), None) if design_id else next((x for x in f.designs if x.is_active), None)
    racks, walk = [], []
    if d:
        cfg = RackConfig.from_dict(d.rack_config)
        rk = fs.design_racks(d)
        racks = [r.rect for r in rk]
        walk = [Rect(**a["rect"]) for a in validate_layout(ctx, cfg, rk, check_reach=False).aisles.values()]
    try:
        out = compute_cells(ctx, cell_m or room.grid_cell_m, racks, walk)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None
    out["design_id"] = d.id if d else None
    out["cell_input"] = room.grid_cell_input
    out["cell_unit"] = room.grid_cell_unit
    return out


# ---------------------------------------------------------------- images

@router.post("/farms/{farm_id}/images", status_code=201)
async def upload_image(farm_id: int, file: UploadFile = File(...), user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    s = get_settings()
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, f"Image exceeds {s.max_upload_mb} MB")
    if not data:
        raise HTTPException(422, "Empty file")
    try:
        img = Image.open(io.BytesIO(data))
        img.verify()
        img = Image.open(io.BytesIO(data))
    except (UnidentifiedImageError, OSError):
        raise HTTPException(415, "File is not a valid JPEG, PNG or WebP image") from None
    if img.format not in ALLOWED_IMAGE:
        raise HTTPException(415, "Only JPEG, PNG or WebP images are accepted")
    if img.width * img.height > 40_000_000:
        raise HTTPException(413, "Image resolution too large")
    ctype, ext = ALLOWED_IMAGE[img.format]
    stored = f"{uuid.uuid4().hex}{ext}"  # never trust the client file name for storage
    storage = Path(s.storage_dir)
    storage.mkdir(parents=True, exist_ok=True)
    (storage / stored).write_bytes(data)
    original = Path(file.filename or "photo").name[:200]
    rec = RoomImage(farm_id=f.id, original_name=original, stored_name=stored, content_type=ctype, size_bytes=len(data),
                    width_px=img.width, height_px=img.height, analysis_status="PENDING")
    db.add(rec)
    db.flush()
    _run_analysis(rec)
    fs.log(db, user, f.id, "image.upload", original)
    db.commit()
    return ser_image(rec)


def _run_analysis(rec: RoomImage) -> None:
    s = get_settings()
    p = Path(s.storage_dir) / rec.stored_name
    try:
        rec.analysis = analyze(p, p.with_name(p.stem + "_edges.png"), s.object_detector_model_path)
        rec.analysis_status = "COMPLETE"
    except Exception as e:  # analysis failure must not lose the upload
        rec.analysis = {"error": str(e)[:200]}
        rec.analysis_status = "FAILED"


def ser_image(i: RoomImage) -> dict:
    return {"id": i.id, "original_name": i.original_name, "content_type": i.content_type, "size_bytes": i.size_bytes,
            "width_px": i.width_px, "height_px": i.height_px, "analysis_status": i.analysis_status, "analysis": i.analysis,
            "url": f"/api/images/{i.id}/file", "edges_url": f"/api/images/{i.id}/file?variant=edges",
            "created_at": i.created_at.isoformat()}


def _own_image(db: Session, image_id: int, user: User) -> RoomImage:
    i = db.get(RoomImage, image_id)
    if not i:
        raise HTTPException(404, "Image not found")
    fs.get_farm(db, i.farm_id, user)
    return i


@router.get("/farms/{farm_id}/images")
def list_images(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    return [ser_image(i) for i in sorted(f.images, key=lambda i: i.id, reverse=True)]


@router.get("/images/{image_id}/file")
def image_file(image_id: int, variant: str = Query("original", pattern="^(original|edges)$"),
               user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _own_image(db, image_id, user)
    p = Path(get_settings().storage_dir) / i.stored_name
    if variant == "edges":
        p = p.with_name(p.stem + "_edges.png")
    if not p.exists():
        raise HTTPException(404, "File missing")
    return FileResponse(p, media_type="image/png" if variant == "edges" else i.content_type,
                        headers={"Cache-Control": "private, max-age=3600", "X-Content-Type-Options": "nosniff"})


@router.post("/images/{image_id}/analyze")
def reanalyze(image_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _own_image(db, image_id, user)
    _run_analysis(i)
    db.commit()
    return ser_image(i)


@router.delete("/images/{image_id}", status_code=204)
def delete_image(image_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = _own_image(db, image_id, user)
    p = Path(get_settings().storage_dir) / i.stored_name
    db.delete(i)
    db.commit()
    p.unlink(missing_ok=True)
    p.with_name(p.stem + "_edges.png").unlink(missing_ok=True)


# ---------------------------------------------------------------- obstacles

def _check_in_room(f: Farm, x: float, y: float, w: float, d: float) -> None:
    r = fs.require_room(f)
    if x + w > r.length_m + 1e-6 or y + d > r.width_m + 1e-6:
        raise HTTPException(422, "Obstacle must lie inside the room boundary")


@router.get("/farms/{farm_id}/obstacles")
def list_obstacles(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return [fs.ser_obstacle(o) for o in fs.get_farm(db, farm_id, user).obstacles]


@router.post("/farms/{farm_id}/obstacles", status_code=201)
def add_obstacle(farm_id: int, body: ObstacleIn, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    _check_in_room(f, body.x, body.y, body.w, body.d)
    data = body.model_dump()
    if body.kind == "DOOR" and not body.clearance_m:
        data["clearance_m"] = 0.9  # default door swing / access depth, editable
    o = Obstacle(farm_id=f.id, source="USER", **data)
    db.add(o)
    fs.log(db, user, f.id, "obstacle.add", body.kind)
    db.commit()
    return fs.ser_obstacle(o)


def _own_obstacle(db, oid, user) -> tuple[Obstacle, Farm]:
    o = db.get(Obstacle, oid)
    if not o:
        raise HTTPException(404, "Obstacle not found")
    return o, fs.get_farm(db, o.farm_id, user)


@router.patch("/obstacles/{oid}")
def patch_obstacle(oid: int, body: ObstaclePatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o, f = _own_obstacle(db, oid, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    _check_in_room(f, o.x, o.y, o.w, o.d)
    db.commit()
    return fs.ser_obstacle(o)


@router.delete("/obstacles/{oid}", status_code=204)
def delete_obstacle(oid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    o, f = _own_obstacle(db, oid, user)
    db.delete(o)
    fs.log(db, user, f.id, "obstacle.delete", o.kind)
    db.commit()
