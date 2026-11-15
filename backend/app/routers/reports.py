import csv
import io
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Alert, Scenario, SensorRecord, User
from ..security import current_user
from ..services import farm_service as fs
from ..services.grid import grid_dimensions

router = APIRouter(prefix="/api", tags=["reports"])


def build_report(db: Session, farm, user) -> dict:
    room = farm.room
    d = next((x for x in farm.designs if x.is_active), None)
    design = fs.ser_design(db, farm, d) if (d and room) else None
    recs = fs.recommendations_for(db, farm) if room else None
    stats = db.execute(select(func.count(SensorRecord.id), func.min(SensorRecord.ts), func.max(SensorRecord.ts),
                              func.avg(SensorRecord.temperature_c), func.avg(SensorRecord.humidity_pct), func.avg(SensorRecord.ph),
                              func.avg(SensorRecord.ec_ms_cm)).where(SensorRecord.farm_id == farm.id)).one()
    alerts_n = db.scalar(select(func.count(Alert.id)).where(Alert.farm_id == farm.id)) or 0
    open_n = db.scalar(select(func.count(Alert.id)).where(Alert.farm_id == farm.id, Alert.status == "OPEN")) or 0
    scen = db.scalars(select(Scenario).where(Scenario.farm_id == farm.id).order_by(Scenario.created_at.desc()).limit(10)).all()
    assumptions = []
    if design:
        assumptions += design["capacity"].get("assumptions", []) + design["resources"]["assumptions"]
        if design["profitability"].get("assumptions"):
            assumptions += design["profitability"]["assumptions"]
    assumptions += ["All lengths stored in metres; converted for display.",
                    "Illustrative prices are planning placeholders converted at the user's exchange-rate assumption.",
                    "Crop requirements are indicative catalogue ranges, not cultivar-specific agronomy advice.",
                    "Monitoring data in this prototype is SIMULATED, not from physical sensors."]
    warnings = []
    if design:
        warnings += [v["message"] for v in design["validation"]["violations"]] + [w["message"] for w in design["validation"]["warnings"]]
        warnings += design["capacity"].get("warnings", [])
        if design["over_budget"]:
            warnings.append("Estimated setup cost exceeds the budget.")
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(), "prepared_for": user.name,
        "farm": {"name": farm.name, "farming_type": farm.farming_type, "currency": farm.currency, "budget": farm.budget,
                 "is_sample": farm.is_sample},
        "room": fs.ser_room(room) if room else None,
        "grid": grid_dimensions(room.length_m, room.width_m, room.grid_cell_m) if room else None,
        "obstacles": [fs.ser_obstacle(o) for o in farm.obstacles],
        "design": None if not design else {
            "name": design["name"], "strategy": design["strategy"], "rack_config": design["rack_config"],
            "racks": design["racks"], "metrics": design["metrics"], "capacity": design["capacity"],
            "validation": design["validation"], "crop": design["crop"], "cost_totals": design["cost_totals"],
            "resources": design["resources"], "profitability": design["profitability"],
            "cost_items": [fs.ser_cost(i) for i in d.cost_items]},
        "crop_recommendations": None if not recs else [
            {"name": r["name"], "score": r["score"], "suitable": r["suitable"], "reasons": r["reasons"][:4], "blockers": r["blockers"]}
            for r in recs["results"][:6]],
        "recommendation_method": recs["method"] if recs else None,
        "scenarios": [{"name": s.name, "changes": s.changes, "feasible": s.result.get("feasible"),
                       "before": s.result.get("before"), "after": s.result.get("after")} for s in scen],
        "monitoring": {"source_type": "SIMULATED", "records": stats[0], "from": stats[1].isoformat() if stats[1] else None,
                       "to": stats[2].isoformat() if stats[2] else None,
                       "avg": {"temperature_c": _r(stats[3]), "humidity_pct": _r(stats[4]), "ph": _r(stats[5]), "ec_ms_cm": _r(stats[6])},
                       "alerts_total": alerts_n, "alerts_open": open_n},
        "assumptions": assumptions, "warnings": warnings,
    }


def _r(v):
    return round(v, 2) if v is not None else None


@router.get("/farms/{farm_id}/report")
def report(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    return build_report(db, fs.get_farm(db, farm_id, user), user)


@router.get("/farms/{farm_id}/report.pdf")
def report_pdf(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = fs.get_farm(db, farm_id, user)
    rep = build_report(db, farm, user)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=16 * mm, rightMargin=16 * mm, topMargin=16 * mm, bottomMargin=16 * mm,
                            title=f"{farm.name} — Vertical farm plan")
    ss = getSampleStyleSheet()
    green = colors.HexColor("#1f4d3a")
    h1 = ParagraphStyle("h1", parent=ss["Title"], textColor=green, alignment=0, fontSize=20)
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=green, spaceBefore=10)
    body = ParagraphStyle("b", parent=ss["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.HexColor("#555555"))

    def table(rows, widths=None):
        t = Table(rows, colWidths=widths, repeatRows=1)
        t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8efe9")), ("TEXTCOLOR", (0, 0), (-1, 0), green),
                               ("FONTSIZE", (0, 0), (-1, -1), 8), ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#cfd8d1")),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"), ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9f7")])]))
        return t

    el = [Paragraph(f"{farm.name}", h1),
          Paragraph(f"Vertical farm plan · generated {rep['generated_at'][:16].replace('T', ' ')} UTC · prepared for {rep['prepared_for']}", small)]
    if farm.is_sample:
        el.append(Paragraph("SAMPLE / DEMO DATA", small))
    r = rep["room"]
    if r:
        u = r["input_unit"]
        el += [Paragraph("Room", h2), table([["Length", "Width", "Height", "Floor area", "Grid"],
                                             [f"{r['length']:g} {u} ({r['length_m']:.2f} m)", f"{r['width']:g} {u} ({r['width_m']:.2f} m)",
                                              f"{r['height']:g} {u} ({r['height_m']:.2f} m)", f"{r['floor_area_m2']:.2f} m²",
                                              f"{rep['grid']['columns']} × {rep['grid']['rows']} = {rep['grid']['full_cells']} cells of {r['grid_cell_m']:.3f} m"]])]
    if rep["obstacles"]:
        el += [Paragraph("Obstacles & restricted zones", h2),
               table([["Type", "Label", "x (m)", "y (m)", "w (m)", "d (m)", "Access depth"]] +
                     [[o["kind"], o["label"] or "", f"{o['x']:.2f}", f"{o['y']:.2f}", f"{o['w']:.2f}", f"{o['d']:.2f}",
                       f"{o['clearance_m']:.2f}" if o["kind"] == "DOOR" else "—"] for o in rep["obstacles"]])]
    d = rep["design"]
    if d:
        m, cap, cfg = d["metrics"], d["capacity"], d["rack_config"]
        el += [Paragraph(f"Layout — {d['name']}", h2),
               Paragraph(f"Strategy: {d['strategy'] or 'manual edit'} · Valid: {'yes' if d['validation']['valid'] else 'NO'}", body),
               table([["Racks", "Rack size (L×D×H)", "Levels", "Walkway", "Utilisation", "Capacity"],
                      [str(m["rack_count"]), f"{cfg['rack_length_m']:.2f}×{cfg['rack_depth_m']:.2f}×{cfg['rack_height_m']:.2f} m",
                       str(cfg["levels"]), f"{cfg['walkway_m']:.2f} m", f"{m['utilization_pct']}%",
                       str(cap.get("total")) if cap.get("total") is not None else "needs crop/spacing"]]),
               Paragraph(f"Utilisation = {m['utilization_definition']}. Capacity basis: {cap['basis']}.", small),
               Spacer(1, 4),
               table([["Rack", "x (m)", "y (m)", "Footprint (m)", "Rotation", "Access side"]] +
                     [[k["label"], f"{k['x']:.2f}", f"{k['y']:.2f}", f"{k['w']:.2f}×{k['d']:.2f}", f"{k['rotation']}°", k["access_side"] or "—"]
                      for k in d["racks"]])]
        el += [Paragraph("Bill of materials", h2),
               table([["Item", "Qty", "Unit price", "Subtotal", "Type", "Source"]] +
                     [[Paragraph(i["name"], body), f"{i['quantity']:g} {i['unit']}", f"{i['unit_price']:.2f}", f"{i['subtotal']:.2f}",
                       i["cost_type"].replace("_", " ").lower() + ("" if i["included"] else " (excluded)"), i["price_source"]]
                      for i in d["cost_items"]], widths=[70 * mm, 22 * mm, 20 * mm, 20 * mm, 25 * mm, 25 * mm]),
               Paragraph(f"Setup total: <b>{d['cost_totals']['setup_total']:.2f} {farm.currency}</b> · Monthly: "
                         f"<b>{d['cost_totals']['monthly_total']:.2f} {farm.currency}</b>. {d['cost_totals']['definition']}", body)]
        p = d["profitability"]
        el.append(Paragraph("Profitability estimate", h2))
        if p.get("available"):
            el.append(Paragraph(f"{p['period']}: revenue ≈ {p['estimated_gross_revenue']:.2f}, included costs {p['included_costs']:.2f}, "
                                f"margin ≈ {p['estimated_margin']:.2f} {farm.currency}. Not a guarantee.", body))
        else:
            el.append(Paragraph("Not estimated — missing: " + ", ".join(p.get("missing", [])), body))
    if rep["crop_recommendations"]:
        el += [Paragraph("Crop recommendations (rule-based)", h2),
               table([["Crop", "Score", "Suitable", "Why"]] +
                     [[c["name"], f"{c['score']:.0f}", "yes" if c["suitable"] else "no",
                       Paragraph(" ".join((c["blockers"] or c["reasons"])[:2]), body)] for c in rep["crop_recommendations"]],
                     widths=[35 * mm, 15 * mm, 17 * mm, 115 * mm])]
    if rep["scenarios"]:
        el += [Paragraph("What-if scenarios", h2),
               table([["Scenario", "Feasible", "Racks", "Capacity", "Setup cost"]] +
                     [[s["name"], "yes" if s["feasible"] else "no",
                       f"{(s['before'] or {}).get('rack_count', '—')} → {(s['after'] or {}).get('rack_count', '—')}",
                       f"{(s['before'] or {}).get('plant_capacity', '—')} → {(s['after'] or {}).get('plant_capacity', '—')}",
                       f"{(s['before'] or {}).get('setup_cost', '—')} → {(s['after'] or {}).get('setup_cost', '—')}"] for s in rep["scenarios"]])]
    mo = rep["monitoring"]
    el += [Paragraph("Monitoring summary — source: SIMULATED", h2),
           Paragraph(f"{mo['records']} simulated readings; {mo['alerts_total']} alerts ({mo['alerts_open']} open). "
                     f"Averages: temperature {mo['avg']['temperature_c']} °C, humidity {mo['avg']['humidity_pct']} %, "
                     f"pH {mo['avg']['ph']}, EC {mo['avg']['ec_ms_cm']} mS/cm.", body)]
    if rep["warnings"]:
        el += [Paragraph("Warnings", h2)] + [Paragraph("• " + w, body) for w in rep["warnings"]]
    el += [Paragraph("Assumptions & limitations", h2)] + [Paragraph("• " + a, body) for a in rep["assumptions"]]
    doc.build(el)
    buf.seek(0)
    name = "".join(c if c.isalnum() else "_" for c in farm.name)[:40]
    return StreamingResponse(buf, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{name}_plan.pdf"'})


@router.get("/farms/{farm_id}/bom.csv")
def bom_csv(farm_id: int, user: User = Depends(current_user), db: Session = Depends(get_db)):
    farm = fs.get_farm(db, farm_id, user)
    d = next((x for x in farm.designs if x.is_active), None)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["name", "category", "quantity", "unit", "unit_price", "subtotal", "currency", "cost_type", "status", "included",
                "price_source", "source_date", "notes"])
    for i in (d.cost_items if d else []):
        w.writerow([i.name, i.category, i.quantity, i.unit, i.unit_price, round(i.quantity * i.unit_price, 2), i.currency, i.cost_type,
                    i.status, i.included, i.price_source, i.source_date or "", i.notes or ""])
    name = "".join(c if c.isalnum() else "_" for c in farm.name)[:40]
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}_bill_of_materials.csv"'})
