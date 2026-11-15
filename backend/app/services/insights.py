"""Insights centre: explainable suggestions gathered from rules over the saved design and stored data.

Every insight declares source_type. All current insights are deterministic RULE outputs or reflect USER_INPUT;
none is labelled MODEL because no trained model is deployed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Alert, Farm, Insight, SensorRecord
from . import farm_service as fs
from .layout import RackConfig


def build(db: Session, farm: Farm) -> list[dict]:
    out: list[dict] = []

    def add(category, priority, title, explanation, action, evidence=None, source="RULE"):
        out.append({"category": category, "priority": priority, "title": title, "explanation": explanation,
                    "action": action, "evidence": evidence or {}, "source_type": source})

    room = farm.room
    if not room:
        add("DATA_QUALITY", "HIGH", "Room dimensions missing", "Layouts, capacity and costs need the room size.",
            "Complete the room setup wizard.")
        return out
    missing = [n for n, v in (("temperature", room.temperature_c), ("humidity", room.humidity_pct)) if v is None]
    if missing:
        add("DATA_QUALITY", "MEDIUM", f"Missing room {' and '.join(missing)}",
            "Crop environment scores use a neutral value when these are unknown, which makes recommendations less specific.",
            "Measure with a basic thermometer/hygrometer and add the values in room setup.", {"missing": missing}, "USER_INPUT")
    if not any(o.kind == "DOOR" for o in farm.obstacles):
        add("LAYOUT", "HIGH", "No door marked on the plan",
            "Without a door the engine cannot verify that every rack can be reached on foot.",
            "Mark the door and its swing zone in the obstacle editor.")
    unconfirmed = [o for o in farm.obstacles if not o.confirmed]
    if unconfirmed:
        add("DATA_QUALITY", "MEDIUM", f"{len(unconfirmed)} obstacle(s) not confirmed",
            "Unconfirmed obstacles are treated as blocked, which may waste space.", "Review and confirm or delete them.")

    d = next((x for x in farm.designs if x.is_active), None)
    if not d:
        add("LAYOUT", "HIGH", "No saved layout", "Capacity, cost and monitoring depend on an active design.",
            "Generate and save a layout in the layout builder.")
    else:
        ev = fs.ser_design(db, farm, d)
        m, cap = ev["metrics"], ev["capacity"]
        for w in ev["validation"]["warnings"]:
            add("LAYOUT", "LOW", "Layout warning", w["message"], "Review the rack position in the layout builder.", {"code": w["code"]})
        if m["utilization_pct"] < 15 and m["rack_count"] > 0:
            add("LAYOUT", "MEDIUM", "Low floor utilisation",
                f"Racks cover {m['utilization_pct']}% of the floor (rack footprint ÷ room area).",
                "Try a scenario with shorter racks, a different orientation or a narrower (still safe) walkway.",
                {"utilization_pct": m["utilization_pct"]})
        for w in cap.get("warnings", []):
            add("CROP", "HIGH", "Capacity warning", w, "Adjust levels or crop choice.")
        if ev["over_budget"]:
            add("COST", "HIGH", "Setup cost exceeds budget",
                f"Estimated setup {ev['cost_totals']['setup_total']:.0f} {farm.currency} vs budget {farm.budget:.0f} {farm.currency}.",
                "Run a what-if scenario with fewer racks or levels, or replace illustrative prices with real quotes.",
                {"setup": ev["cost_totals"]["setup_total"], "budget": farm.budget})
        if ev["cost_totals"]["illustrative_lines"]:
            add("COST", "LOW", f"{ev['cost_totals']['illustrative_lines']} cost lines use illustrative prices",
                "Illustrative prices are placeholders, not quotes.", "Edit unit prices with supplier quotes.")
        if ev["crop_suitability"] and not ev["crop_suitability"]["suitable"]:
            add("CROP", "HIGH", f"{ev['crop']['name']} does not fit this design", "; ".join(ev["crop_suitability"]["blockers"]),
                "Open crop recommendations for suitable alternatives.")
        if not d.crop_slug:
            recs = fs.recommendations_for(db, farm)
            if recs["top"]:
                t = recs["top"]
                add("CROP", "MEDIUM", f"Consider {t['name']} (score {t['score']:.0f}/100)", " ".join(t["reasons"][:3]),
                    "Assign a crop to the design to unlock capacity and revenue estimates.", {"score": t["score"]})
        r = ev["resources"]
        cfg = RackConfig.from_dict(d.rack_config)
        if r["energy_breakdown"]["lighting"] > 0.7 * r["energy_kwh_month"] and r["energy_kwh_month"] > 0:
            add("RESOURCE", "LOW", "Lighting dominates energy use",
                f"Lighting is ≈{r['energy_breakdown']['lighting']:.0f} of {r['energy_kwh_month']:.0f} kWh/month "
                f"({r['light_fixtures']} fixtures × {r['photoperiod_h']} h/day).",
                "Match photoperiod to the crop and consider off-peak tariffs.", {"levels": cfg.levels})
        if not ev["profitability"].get("available"):
            add("COST", "LOW", "Revenue not estimated", "Missing: " + ", ".join(ev["profitability"].get("missing", [])),
                "Add a market price assumption on the cost page.", source="USER_INPUT")

    since = datetime.now(timezone.utc) - timedelta(hours=24)
    n_open = db.scalar(select(func.count(Alert.id)).where(Alert.farm_id == farm.id, Alert.status == "OPEN")) or 0
    if n_open:
        latest = db.scalars(select(Alert).where(Alert.farm_id == farm.id, Alert.status == "OPEN").order_by(Alert.created_at.desc())).first()
        add("MONITORING", "HIGH" if latest.severity == "CRITICAL" else "MEDIUM", f"{n_open} open monitoring alert(s)",
            f"Latest: {latest.message} (data source: {latest.data_source}).", latest.suggestion, {"metric": latest.metric})
    n_rec = db.scalar(select(func.count(SensorRecord.id)).where(SensorRecord.farm_id == farm.id, SensorRecord.ts >= since)) or 0
    if n_rec:
        add("DATA_QUALITY", "LOW", "Monitoring data is simulated",
            f"{n_rec} readings in the last 24 h were generated by the simulator, not physical sensors.",
            "Treat charts as a demonstration of the monitoring workflow.", {"records_24h": n_rec})
    return out


def refresh(db: Session, farm: Farm) -> list[Insight]:
    dismissed = {i.title for i in db.scalars(select(Insight).where(Insight.farm_id == farm.id, Insight.dismissed.is_(True)))}
    for i in db.scalars(select(Insight).where(Insight.farm_id == farm.id, Insight.dismissed.is_(False))):
        db.delete(i)
    db.flush()
    rows = []
    for x in build(db, farm):
        if x["title"] in dismissed:
            continue
        row = Insight(farm_id=farm.id, **x)
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
