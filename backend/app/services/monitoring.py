"""Persisting simulated readings and evaluating alert rules. Flow: Simulator → backend → DB → rules → dashboard."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Farm, SensorRecord, SimulatorState, Threshold
from . import alerts as alert_svc
from . import simulator as sim
from .farm_service import crop_dict

DEDUP_WINDOW = timedelta(minutes=10)


def active_crop(db: Session, farm: Farm) -> dict | None:
    d = next((x for x in farm.designs if x.is_active), None)
    return crop_dict(db, (d.crop_slug if d else None) or farm.preferred_crop)


def ensure_thresholds(db: Session, farm: Farm) -> list[Threshold]:
    rows = db.scalars(select(Threshold).where(Threshold.farm_id == farm.id)).all()
    if rows:
        return list(rows)
    for t in alert_svc.default_thresholds(active_crop(db, farm)):
        db.add(Threshold(farm_id=farm.id, **t))
    db.flush()
    return list(db.scalars(select(Threshold).where(Threshold.farm_id == farm.id)))


def get_state(db: Session, farm: Farm) -> SimulatorState:
    st = db.scalar(select(SimulatorState).where(SimulatorState.farm_id == farm.id))
    if not st:
        st = SimulatorState(farm_id=farm.id, status="STOPPED", mode="NORMAL", interval_s=5, state={})
        db.add(st)
        db.flush()
    return st


def ingest(db: Session, farm: Farm, values: dict, ts: datetime, source_type: str, device_id: str | None = None) -> tuple[SensorRecord, list[Alert]]:
    """Shared ingestion path for the simulator today and a device adapter later. Missing values stay NULL."""
    cols = {k: values.get(k) for k in ("temperature_c", "humidity_pct", "ph", "ec_ms_cm", "tds_ppm", "water_level_pct",
                                         "light_ppfd", "pump_on", "fan_on", "energy_wh", "water_l")}
    rec = SensorRecord(farm_id=farm.id, ts=ts, source_type=source_type, device_id=device_id, **cols)
    db.add(rec)
    db.flush()
    created = []
    thresholds = ensure_thresholds(db, farm)
    hits = alert_svc.evaluate(cols, thresholds)
    hit_metrics = {h["metric"] for h in hits}
    for h in hits:
        recent = db.scalars(select(Alert).where(Alert.farm_id == farm.id, Alert.metric == h["metric"], Alert.status == "OPEN",
                                                Alert.severity == h["severity"]).order_by(Alert.created_at.desc())).first()
        if recent and _aware(recent.created_at) > ts - DEDUP_WINDOW:
            recent.value, recent.message, recent.record_id = h["value"], h["message"], rec.id
            continue
        a = Alert(farm_id=farm.id, record_id=rec.id, source_type="RULE", data_source=source_type, created_at=ts, updated_at=ts, **h)
        db.add(a)
        created.append(a)
    # auto-resolve open alerts whose metric is back within limits
    for a in db.scalars(select(Alert).where(Alert.farm_id == farm.id, Alert.status == "OPEN")):
        if a.metric not in hit_metrics and cols.get(a.metric) is not None:
            a.status = "RESOLVED"
            a.suggestion = (a.suggestion + " (auto-resolved: value returned within limits)")[:300]
    return rec, created


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def tick(db: Session, farm: Farm, st: SimulatorState, ts: datetime | None = None, mode: str | None = None,
         rng: random.Random | None = None) -> tuple[SensorRecord, list[Alert]]:
    ts = ts or datetime.now(timezone.utc)
    crop = active_crop(db, farm)
    targets, _ = sim.targets_for(crop)
    vals = sim.step(st.state or None, targets, mode or st.mode, ts, (crop or {}).get("photoperiod_h") or 16, rng)
    # approximate energy for this interval from the active design (lights on + pumps + fans)
    from .costs import FAN_W, LIGHT_W_PER_FIXTURE, PUMP_W, resources
    from .layout import RackConfig
    d = next((x for x in farm.designs if x.is_active), None)
    if d:
        r = resources(RackConfig.from_dict(d.rack_config), len(d.racks), None, crop)
        watts = (r["light_fixtures"] * LIGHT_W_PER_FIXTURE if vals["light_ppfd"] > 0 else 0) + \
                (r["tanks"] * PUMP_W if vals["pump_on"] else 0) + (r["fans"] * FAN_W if vals["fan_on"] else 0)
        vals["energy_wh"] = round(watts * st.interval_s / 3600, 3)
    st.state = {k: vals[k] for k in sim.GENERIC_TARGETS}
    st.last_tick_at = ts
    return ingest(db, farm, vals, ts, "SIMULATED")


def backfill(db: Session, farm: Farm, hours: int, step_min: int = 10, seed: int | None = None) -> int:
    """Generate historical SIMULATED readings so charts have context. Clearly labelled SIMULATED."""
    st = get_state(db, farm)
    rng = random.Random(seed)
    now = datetime.now(timezone.utc)
    n = int(hours * 60 / step_min)
    st.state = {}
    for i in range(n, 0, -1):
        tick(db, farm, st, now - timedelta(minutes=i * step_min), "NORMAL", rng)
    return n
