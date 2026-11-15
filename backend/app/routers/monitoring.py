import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import Float, func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Insight, SensorRecord, Threshold, User
from ..schemas import AlertPatch, SimulatorPatch, ThresholdIn
from ..security import current_user
from ..services import farm_service as fs
from ..services import insights as insight_svc
from ..services import monitoring as mon
from ..services import simulator as sim

router = APIRouter(prefix="/api", tags=["monitoring"])
RANGES = {"1h": timedelta(hours=1), "6h": timedelta(hours=6), "24h": timedelta(hours=24), "7d": timedelta(days=7)}
FIELDS = ["temperature_c", "humidity_pct", "ph", "ec_ms_cm", "tds_ppm", "water_level_pct", "light_ppfd", "pump_on", "fan_on", "energy_wh"]


def ser_state(db, farm, st) -> dict:
    crop = mon.active_crop(db, farm)
    targets, basis = sim.targets_for(crop)
    count = db.scalar(select(func.count(SensorRecord.id)).where(SensorRecord.farm_id == farm.id)) or 0
    return {"farm_id": farm.id, "status": st.status, "mode": st.mode, "interval_s": st.interval_s,
            "last_tick_at": st.last_tick_at.isoformat() if st.last_tick_at else None, "record_count": count,
            "targets": targets, "target_basis": basis, "source_type": "SIMULATED",
            "data_flow": "Simulator → backend → database → rules → dashboard",
            "future_flow": "Sensors → ESP32 → Wi-Fi/MQTT broker → backend → database → rules → dashboard (NOT IMPLEMENTED)"}


def ser_rec(r: SensorRecord) -> dict:
    return {"id": r.id, "ts": r.ts.isoformat(), "source_type": r.source_type, **{k: getattr(r, k) for k in FIELDS}}


def ser_alert(a: Alert) -> dict:
    return {"id": a.id, "metric": a.metric, "severity": a.severity, "value": a.value, "message": a.message,
            "suggestion": a.suggestion, "status": a.status, "source_type": a.source_type, "data_source": a.data_source,
            "created_at": a.created_at.isoformat(), "updated_at": a.updated_at.isoformat()}


@router.get("/farms/{farm_id}/simulator")
def get_sim(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    st = mon.get_state(db, f)
    db.commit()
    return ser_state(db, f, st)


@router.patch("/farms/{farm_id}/simulator")
def patch_sim(farm_id: int, body: SimulatorPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    st = mon.get_state(db, f)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(st, k, v)
    db.commit()
    return ser_state(db, f, st)


@router.post("/farms/{farm_id}/simulator/tick")
def manual_tick(farm_id: int, count: int = Query(1, ge=1, le=500), user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Generate `count` readings now (one interval apart) regardless of run state — for testing and demos."""
    f = fs.get_farm(db, farm_id, user)
    st = mon.get_state(db, f)
    now = datetime.now(timezone.utc)
    recs, alerts = [], []
    for i in range(count):
        r, a = mon.tick(db, f, st, now - timedelta(seconds=(count - 1 - i) * st.interval_s))
        recs.append(r)
        alerts += a
    db.commit()
    return {"records": [ser_rec(r) for r in recs], "alerts_created": [ser_alert(a) for a in alerts]}


@router.post("/farms/{farm_id}/simulator/backfill")
def backfill(farm_id: int, hours: int = Query(24, ge=1, le=168), user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    n = mon.backfill(db, f, hours)
    db.commit()
    return {"generated": n, "source_type": "SIMULATED"}


@router.delete("/farms/{farm_id}/sensors", status_code=204)
def clear_sensors(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    for a in db.scalars(select(Alert).where(Alert.farm_id == f.id)):
        db.delete(a)
    for r in db.scalars(select(SensorRecord).where(SensorRecord.farm_id == f.id)):
        db.delete(r)
    fs.log(db, user, f.id, "sensors.clear")
    db.commit()


@router.get("/farms/{farm_id}/sensors")
def sensors(farm_id: int, limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0),
            since: datetime | None = None, until: datetime | None = None,
            user: User = Depends(current_user), db: Session = Depends(get_db)):
    fs.get_farm(db, farm_id, user)
    q = select(SensorRecord).where(SensorRecord.farm_id == farm_id)
    if since:
        q = q.where(SensorRecord.ts >= since)
    if until:
        q = q.where(SensorRecord.ts <= until)
    total = db.scalar(select(func.count()).select_from(q.subquery()))
    rows = db.scalars(q.order_by(SensorRecord.ts.desc()).limit(limit).offset(offset))
    return {"total": total, "limit": limit, "offset": offset, "items": [ser_rec(r) for r in rows]}


@router.get("/farms/{farm_id}/sensors/latest")
def latest(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    fs.get_farm(db, farm_id, user)
    r = db.scalars(select(SensorRecord).where(SensorRecord.farm_id == farm_id).order_by(SensorRecord.ts.desc())).first()
    return ser_rec(r) if r else None


@router.get("/farms/{farm_id}/sensors/series")
def series(farm_id: int, range: str = Query("24h", pattern="^(1h|6h|24h|7d)$"), buckets: int = Query(120, ge=10, le=500),
           user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Bucket-averaged history computed in the database (null buckets stay null)."""
    fs.get_farm(db, farm_id, user)
    end = datetime.now(timezone.utc)
    start = end - RANGES[range]
    width_s = RANGES[range].total_seconds() / buckets
    metrics = FIELDS[:7]
    if db.bind.dialect.name == "sqlite":
        epoch = func.cast(func.strftime("%s", SensorRecord.ts), Float)
    else:
        epoch = func.extract("epoch", SensorRecord.ts)
    bucket = func.floor((epoch - start.timestamp()) / width_s).label("b")
    q = (select(bucket, func.count(SensorRecord.id), *[func.avg(getattr(SensorRecord, k)) for k in metrics])
         .where(SensorRecord.farm_id == farm_id, SensorRecord.ts >= start).group_by(bucket).order_by(bucket))
    points, count = [], 0
    for row in db.execute(q):
        b = min(buckets - 1, max(0, int(row[0])))
        count += row[1]
        p = {"ts": (start + timedelta(seconds=width_s * (b + 0.5))).isoformat()}
        for k, v in zip(metrics, row[2:], strict=True):
            p[k] = round(float(v), 3) if v is not None else None
        points.append(p)
    return {"range": range, "start": start.isoformat(), "end": end.isoformat(), "count": count, "points": points,
            "source_type": "SIMULATED" if count else None}


@router.get("/farms/{farm_id}/sensors/export.csv")
def export_csv(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["timestamp_utc", "source_type", *FIELDS])
    for r in db.scalars(select(SensorRecord).where(SensorRecord.farm_id == farm_id).order_by(SensorRecord.ts).limit(50000)):
        w.writerow([r.ts.isoformat(), r.source_type, *["" if getattr(r, k) is None else getattr(r, k) for k in FIELDS]])
    name = "".join(c if c.isalnum() else "_" for c in f.name)[:40]
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}_sensor_history_SIMULATED.csv"'})


# ---------------------------------------------------------------- thresholds & alerts

def ser_t(t: Threshold) -> dict:
    return {k: getattr(t, k) for k in ("metric", "warn_min", "warn_max", "crit_min", "crit_max", "basis", "enabled")}


@router.get("/farms/{farm_id}/thresholds")
def thresholds(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    rows = mon.ensure_thresholds(db, f)
    db.commit()
    return [ser_t(t) for t in rows]


@router.put("/farms/{farm_id}/thresholds")
def put_thresholds(farm_id: int, body: list[ThresholdIn], user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    rows = {t.metric: t for t in mon.ensure_thresholds(db, f)}
    for t in body:
        row = rows[t.metric]
        for k, v in t.model_dump().items():
            setattr(row, k, v)
        row.basis = "User-configured"
    db.commit()
    return [ser_t(t) for t in rows.values()]


@router.post("/farms/{farm_id}/thresholds/reset")
def reset_thresholds(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    for t in db.scalars(select(Threshold).where(Threshold.farm_id == f.id)):
        db.delete(t)
    db.flush()
    rows = mon.ensure_thresholds(db, f)
    db.commit()
    return [ser_t(t) for t in rows]


@router.get("/alerts/summary")
def alert_summary(user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Cheap count for the notification bell (no design evaluation)."""
    from ..models import Farm
    rows = db.execute(select(Alert.severity, func.count(Alert.id)).join(Farm, Farm.id == Alert.farm_id)
                      .where(Farm.owner_id == user.id, Farm.status == "ACTIVE", Alert.status == "OPEN").group_by(Alert.severity)).all()
    counts = {s: n for s, n in rows}
    return {"open": sum(counts.values()), "critical": counts.get("CRITICAL", 0), "warning": counts.get("WARNING", 0)}


@router.get("/farms/{farm_id}/alerts")
def list_alerts(farm_id: int, status: str = Query("ALL", pattern="^(ALL|OPEN|ACKNOWLEDGED|RESOLVED)$"),
                limit: int = Query(100, ge=1, le=500), user: User = Depends(current_user), db: Session = Depends(get_db)):
    fs.get_farm(db, farm_id, user)
    q = select(Alert).where(Alert.farm_id == farm_id)
    if status != "ALL":
        q = q.where(Alert.status == status)
    return [ser_alert(a) for a in db.scalars(q.order_by(Alert.created_at.desc()).limit(limit))]


@router.patch("/alerts/{alert_id}")
def patch_alert(alert_id: int, body: AlertPatch, user: User = Depends(current_user), db: Session = Depends(get_db)):
    a = db.get(Alert, alert_id)
    if not a:
        raise HTTPException(404, "Alert not found")
    fs.get_farm(db, a.farm_id, user)
    a.status = body.status
    db.commit()
    return ser_alert(a)


@router.post("/farms/{farm_id}/alerts/test")
def test_alert(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    """Inject one ABNORMAL simulated reading to exercise the alert rules end-to-end."""
    f = fs.get_farm(db, farm_id, user)
    st = mon.get_state(db, f)
    st.state = {}
    targets, _ = sim.targets_for(mon.active_crop(db, f))
    vals = {**targets, "ph": targets["ph"] + 2.0, "water_level_pct": 10.0, "light_ppfd": 0.0, "pump_on": False, "fan_on": True}
    vals["tds_ppm"] = vals["ec_ms_cm"] * 500
    rec, created = mon.ingest(db, f, vals, datetime.now(timezone.utc), "SIMULATED")
    fs.log(db, user, f.id, "alert.test")
    db.commit()
    return {"record": ser_rec(rec), "alerts_created": [ser_alert(a) for a in created],
            "note": "Test reading injected by the simulator (source_type = SIMULATED)."}


# ---------------------------------------------------------------- insights

def ser_i(i: Insight) -> dict:
    return {"id": i.id, "category": i.category, "priority": i.priority, "title": i.title, "explanation": i.explanation,
            "evidence": i.evidence, "action": i.action, "source_type": i.source_type, "dismissed": i.dismissed,
            "created_at": i.created_at.isoformat()}


@router.get("/farms/{farm_id}/insights")
def insights(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    rows = db.scalars(select(Insight).where(Insight.farm_id == f.id, Insight.dismissed.is_(False))).all()
    if not rows:
        rows = insight_svc.refresh(db, f)
        db.commit()
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted([ser_i(i) for i in rows], key=lambda x: (order.get(x["priority"], 3), x["category"]))


@router.post("/farms/{farm_id}/insights/refresh")
def refresh_insights(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    f = fs.get_farm(db, farm_id, user)
    rows = insight_svc.refresh(db, f)
    db.commit()
    order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
    return sorted([ser_i(i) for i in rows], key=lambda x: (order.get(x["priority"], 3), x["category"]))


@router.patch("/insights/{iid}")
def dismiss_insight(iid: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    i = db.get(Insight, iid)
    if not i:
        raise HTTPException(404, "Insight not found")
    fs.get_farm(db, i.farm_id, user)
    i.dismissed = True
    db.commit()
    return ser_i(i)


# registered last so /simulator/tick and /simulator/backfill match first
@router.post("/farms/{farm_id}/simulator/{action}")
def control(farm_id: int, action: str, user: User = Depends(current_user), db: Session = Depends(get_db)):
    if action not in ("start", "pause", "stop"):
        raise HTTPException(404, "Unknown action")
    f = fs.get_farm(db, farm_id, user)
    st = mon.get_state(db, f)
    st.status = {"start": "RUNNING", "pause": "PAUSED", "stop": "STOPPED"}[action]
    if action == "stop":
        st.state = {}
    if action == "start":
        mon.ensure_thresholds(db, f)
        mon.tick(db, f, st)  # immediate first reading
    fs.log(db, user, f.id, f"simulator.{action}")
    db.commit()
    return ser_state(db, f, st)
