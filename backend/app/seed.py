"""Create a demo account with one SAMPLE farm. Run: python -m app.seed

Demo login: demo@verdant.app / verdant-demo-2026   (development only — change or delete in production)
"""
from sqlalchemy import select

from .db import SessionLocal
from .main import run_migrations, seed_crops
from .models import Farm, MarketPrice, Obstacle, Room, User
from .security import hash_password
from .services import monitoring as mon
from .services.units import to_m

EMAIL, PASSWORD = "demo@verdant.app", "verdant-demo-2026"


def main() -> None:
    run_migrations()
    seed_crops()
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.email == EMAIL))
        if u:
            print(f"Demo user already exists: {EMAIL}")
            return
        u = User(email=EMAIL, name="Demo Grower", password_hash=hash_password(PASSWORD), preferences={"display_unit": "ft"})
        db.add(u)
        db.flush()
        f = Farm(owner_id=u.id, name="Spare bedroom farm (sample)", farming_type="HYDROPONIC_NFT", budget=30000, currency="INR",
                 preferred_crop="leaf-lettuce", crop_categories=["VEGETABLE", "HERB"], is_sample=True, wizard_step=5,
                 latitude=12.9716, longitude=77.5946, location_name="Bengaluru, Karnataka, India (sample)", location_source="USER_INPUT")
        db.add(f)
        db.flush()
        f.room = Room(length_m=to_m(10, "ft"), width_m=to_m(8, "ft"), height_m=to_m(9, "ft"), input_unit="ft",
                      grid_cell_m=to_m(1, "ft"), grid_cell_input=1, grid_cell_unit="ft", temperature_c=21, humidity_pct=58,
                      light_source="GROW_LIGHTS", water_access=True, electrical_access=True, notes="Sample data for demonstration.")
        f.obstacles += [
            Obstacle(kind="DOOR", label="Door", x=1.2, y=0, w=0.8, d=0.05, clearance_m=0.8),
            Obstacle(kind="WINDOW", label="Window", x=3.0, y=0.6, w=0.048, d=1.0),
            Obstacle(kind="PILLAR", label="Column", x=2.7, y=2.05, w=0.3, d=0.3),
        ]
        db.flush()
        db.add(MarketPrice(farm_id=f.id, crop_slug="leaf-lettuce", price=180.0, currency="INR", location="Sample assumption",
                           grade="Sample — replace with your local price", source_type="USER_INPUT"))
        db.flush()
        from .routers.ai import AutoPlanIn, run_autoplan
        run_autoplan(db, f, u, AutoPlanIn(crop_slug="leaf-lettuce"))
        n = mon.backfill(db, f, 24, seed=7)
        db.commit()
        print(f"Created demo user {EMAIL} / {PASSWORD} with sample farm (#{f.id}) and {n} SIMULATED readings.")


if __name__ == "__main__":
    main()
