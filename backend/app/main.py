"""FastAPI entry point: error schema, CORS, health, crop seeding, simulator loop."""
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import select, text

from .config import get_settings
from .db import SessionLocal, engine
from .models import Crop, Farm, SimulatorState
from .routers import ai, auth, crops, designs, farms, monitoring, reports

logging.basicConfig(level=logging.INFO, format='{"t":"%(asctime)s","lvl":"%(levelname)s","log":"%(name)s","msg":"%(message)s"}')
log = logging.getLogger("verdant")


def run_migrations() -> None:
    from pathlib import Path

    from alembic import command
    from alembic.config import Config
    base = Path(__file__).resolve().parent.parent
    cfg = Config(str(base / "alembic.ini"))
    cfg.set_main_option("script_location", str(base / "alembic"))
    cfg.set_main_option("sqlalchemy.url", get_settings().database_url)
    command.upgrade(cfg, "head")


def seed_crops() -> None:
    from .services.crops import load_catalogue
    cat = load_catalogue()
    with SessionLocal() as db:
        for c in cat["crops"]:
            data = {k: v for k, v in c.items() if k not in ("slug", "name", "category")}
            row = db.get(Crop, c["slug"])
            if row:
                row.name, row.category, row.data = c["name"], c["category"], data
                row.provenance, row.last_reviewed = cat["provenance"], cat["last_reviewed"]
            else:
                db.add(Crop(slug=c["slug"], name=c["name"], category=c["category"], data=data,
                            provenance=cat["provenance"], last_reviewed=cat["last_reviewed"]))
        db.commit()


def simulator_pass() -> int:
    """Advance every RUNNING simulator whose interval has elapsed. Returns records written."""
    from .services import monitoring as mon
    n = 0
    now = datetime.now(timezone.utc)
    with SessionLocal() as db:
        for st in db.scalars(select(SimulatorState).where(SimulatorState.status == "RUNNING")).all():
            last = st.last_tick_at
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if last is None or now - last >= timedelta(seconds=st.interval_s):
                farm = db.get(Farm, st.farm_id)
                if farm and farm.room:
                    mon.tick(db, farm, st, now)
                    n += 1
        db.commit()
    return n


async def simulator_loop() -> None:
    while True:
        try:
            await asyncio.to_thread(simulator_pass)
        except Exception:  # keep loop alive; log without leaking to clients
            log.exception("simulator pass failed")
        await asyncio.sleep(1)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.auto_migrate:
        run_migrations()
    seed_crops()
    task = asyncio.create_task(simulator_loop()) if s.simulator_enabled else None
    log.info("Verdant API started (env=%s)", s.environment)
    yield
    if task:
        task.cancel()


settings = get_settings()
app = FastAPI(title="Verdant API", version="1.0.0", lifespan=lifespan,
              description="Space-adaptive vertical farming planning & management with IoT simulation. "
                          "Lengths are metres; coordinates originate at the room's top-left corner.")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origin_list, allow_credentials=True,
                   allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"], allow_headers=["Content-Type", "Authorization", "X-Requested-With"])


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/assets/") and resp.status_code == 200:
        resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"  # file names are content-hashed
    return resp


def _err(status: int, code: str, message: str, details=None) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "details": details}})


@app.exception_handler(HTTPException)
async def http_exc(_, exc: HTTPException):
    codes = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 409: "CONFLICT", 413: "TOO_LARGE",
             415: "UNSUPPORTED_MEDIA", 422: "VALIDATION_ERROR", 429: "RATE_LIMITED"}
    return _err(exc.status_code, codes.get(exc.status_code, "ERROR"), str(exc.detail))


@app.exception_handler(RequestValidationError)
async def validation_exc(_, exc: RequestValidationError):
    details = [{"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"].replace("Value error, ", "")}
               for e in exc.errors()]
    msg = details[0]["message"] if details else "Invalid input"
    return _err(422, "VALIDATION_ERROR", msg, details)


@app.exception_handler(ValueError)
async def value_exc(_, exc: ValueError):
    return _err(422, "VALIDATION_ERROR", str(exc))


@app.exception_handler(Exception)
async def unhandled(_, exc: Exception):
    log.exception("unhandled error")
    return _err(500, "INTERNAL_ERROR", "Something went wrong on the server. The error has been logged.")


@app.get("/api/health", tags=["health"])
def health():
    try:
        with engine.connect() as c:
            c.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "database": "ok" if db_ok else "unreachable", "version": app.version,
            "simulator_loop": settings.simulator_enabled, "object_detection": "NOT_ENABLED" if not settings.object_detector_model_path else "CONFIGURED",
            "market_provider": "NONE"}


for r in (ai.router, auth.router, farms.router, designs.router, crops.router, monitoring.router, reports.router):
    app.include_router(r)


# Single-server mode: if the frontend has been built (frontend/dist), serve it from the API so only Python is needed.
def _mount_frontend() -> None:
    from pathlib import Path

    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles
    dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    if not (dist / "index.html").exists():
        return
    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")
        f = (dist / path).resolve()
        if path and f.is_file() and dist in f.parents:
            return FileResponse(f)
        return FileResponse(dist / "index.html")


_mount_frontend()
