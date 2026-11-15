# Verdant — AI-Based Space-Adaptive Vertical Farming Planning and Management System Using IoT Simulation

Verdant helps someone with little or no farming experience answer: **“Can I build a vertical farm in my room, how should I arrange it, what should I grow, what might it cost, and how can I monitor it?”**

The workflow is **Plan → Build → Monitor → Optimize**:

1. **Plan:** room wizard (units, photo, conditions, goals), obstacle and door editor, planning grid.
2. **Build:** constraint-checked rack layouts (generated and hand-edited), a 2D plan and 3D model drawn from the same stored geometry, explainable crop scoring, and a costed bill of materials.
3. **Monitor:** a persisted, rule-alerted monitoring pipeline fed by a **simulator**. Every reading is labelled `SIMULATED`.
4. **Optimize:** what-if scenarios with before/after comparison, an insights centre, and PDF/CSV export.

---

## What's new: budget-first planning with AI

- **The budget decides everything.** The customer enters only a budget (INR by default, e.g. ₹30,000). The planner (`services/autoplan.py`):
  - tries 4 standard rack sizes, both orientations, every level count the crop allows and every rack count;
  - picks the plan with the most plant sites, or the best monthly margin when a selling price makes some option profitable;
  - **never lets the setup cost exceed the budget.** By default 5% is kept in reserve, and optional extras are added only if they still fit.

  Layouts edited by hand and scenarios are also blocked from going over budget (`OVER_BUDGET`).
- **Native INR prices.** Indian illustrative prices are used directly, with no exchange-rate guess. Rack and tray prices scale with rack size and levels. All prices stay editable and labelled.
- **AI from a photo** (needs an API key). The AI estimates room size, light, doors, windows, furniture, sockets and water from one photo and fills them in. Sizes are flagged for checking with a tape measure, and objects arrive as unconfirmed suggestions on the plan.
- **Location and season.** "Enable location" (browser) or a typed city sets the place.
  - The season (Indian Kharif/Rabi/Zaid, or hemisphere seasons elsewhere) is worked out by rule.
  - A 7-day weather outlook comes from Open-Meteo, which needs no key.
  - Each crop gets a season-fit score.
- **AI crop advisor** (needs an API key). It ranks the best crops for the location, season and budget, with demand trend, local price range per kg, selling channel and risks.
  - With web search on, it uses live web results and lists its sources.
  - Only crops the rule engine says physically fit the racks can be suggested.
  - "Use & re-plan" saves the price as `AI_ESTIMATE` and re-runs the budget planner for that crop.
- **AI providers.** Google Gemini, Anthropic Claude or OpenAI. Choose the provider in **Settings → AI assistant**, paste the key and press **Test & load models**. The key is stored server-side and never sent back to the browser. Server-wide alternative: the `AI_PROVIDER`, `AI_API_KEY` and `AI_MODEL` environment variables.

## Windows: one click

Install [Python 3.11+](https://www.python.org/downloads/) (tick *Add python.exe to PATH*), then double-click **`start-verdant.bat`**. Node.js is not needed: the zip includes the built frontend (`frontend/dist`), which the API serves itself. The launcher installs Python packages on first run, creates the demo data, starts the server and opens http://localhost:8000 in Chrome.

## Quick start (local, SQLite demo mode)

Prerequisites: **Python 3.11+** (tested on 3.13) and **Node 20+** (tested on 22).

```bash
# 1. Backend  (http://127.0.0.1:8000, API docs at /docs)
cd backend
python -m venv .venv && source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
cp .env.example .env                                      # edit SECRET_KEY for anything non-local
python -m app.seed                                        # optional: demo user + sample farm
uvicorn app.main:app --reload --port 8000

# 2. Frontend (http://localhost:5173) — in a second terminal
cd frontend
npm install
npm run dev
```

Migrations run automatically on API start (`AUTO_MIGRATE=true`). To run them by hand: `cd backend && alembic upgrade head`.

**Demo login** (created only by `python -m app.seed`, development only): `demo@verdant.app` / `verdant-demo-2026`.
The sample farm is labelled *Sample* everywhere and comes with 24 h of simulated history.

## Docker Compose (PostgreSQL)

```bash
SECRET_KEY=$(python -c "import secrets;print(secrets.token_urlsafe(48))") docker compose up --build
# open http://localhost:8080
docker compose exec api python -m app.seed               # optional demo data
```

Compose runs Postgres 16, the API (Uvicorn) and the built frontend behind nginx, which proxies `/api`. Uploaded photos live in the `uploads` volume.

## Tests

| Suite | Command | Result at hand-off |
|---|---|---|
| Backend: unit + API (pytest) | `cd backend && pytest -q` | **117 passed** on SQLite and on PostgreSQL 16 (`TEST_DATABASE_URL=postgresql+psycopg2://…`) |
| Migration drift | `cd backend && alembic check` | No new upgrade operations detected |
| Frontend: unit/component (Vitest) | `cd frontend && npm test` | **15 passed** |
| Type check / lint / build | `npm run typecheck && npm run lint && npm run build` | Pass (lint: warnings only) |
| End-to-end (Playwright) | `cd frontend && npm run e2e` | **4 passed** (incl. budget plan never over budget; tiny budget refused) |

The E2E suite starts its own isolated API (port 8001, throwaway DB) and Vite (port 5174). It covers:

- Main journey: sign up → 10 ft × 8 ft × 9 ft room with a 1 ft grid → photo upload → door and pillar → verify 10 × 8 = 80 cells → generate and save a layout → independent no-overlap check → reload and reopen → 2D and 3D → crop recommendation → edit a cost and verify the total → run and save a scenario → start the simulator and verify timestamped `SIMULATED` records → test alert → PDF export.
- An infeasible design, which must be explained rather than relaxed.
- Invalid input, which must be rejected.

If Playwright can't download its browser, point it at an installed Chrome: `PLAYWRIGHT_CHROME_PATH=/usr/bin/google-chrome npm run e2e`.

## Environment variables

See `backend/.env.example`. You must set `SECRET_KEY` (and `COOKIE_SECURE=true` behind HTTPS) for any real deployment. **No API keys are required.** These optional settings have fallbacks:

| Variable | Purpose | Without it |
|---|---|---|
| `MARKET_API_URL`, `MARKET_API_KEY` | Live market prices | Users enter price assumptions, labelled `USER_INPUT`. No provider adapter is implemented yet. |
| `OBJECT_DETECTOR_MODEL_PATH` | Local object-detection model | Not used; AI photo reading uses your AI key instead. |
| `AI_PROVIDER`, `AI_API_KEY`, `AI_MODEL` | Server-wide AI key (optional) | Each user adds their own key in Settings → AI assistant; without any key, AI features show how to enable them and everything else works. |

---

## Architecture

```
frontend/  React 19 + TypeScript + Vite, Tailwind v4, TanStack Query, React Router,
           react-hook-form + zod, SVG 2D plan, three.js via React Three Fiber (lazy-loaded), Recharts
backend/   FastAPI + Pydantic v2, SQLAlchemy 2, Alembic, OpenCV, ReportLab
  app/services/   units · geometry · spatial · grid · layout · capacity · crops · costs ·
                  simulator · alerts · monitoring · insights · image_analysis · farm_service
  app/routers/    auth · farms (room, images, obstacles, grid, dashboard) · designs (layout, geometry, costs) ·
                  crops (recommendations, market, scenarios) · monitoring · reports
```

The app is a modular monolith. All business logic lives on the server, and the browser only renders it. For example, live layout validation in the editor calls `POST /api/designs/{id}/validate`.

### Spatial model

- **Units:** everything is stored in metres and converted only for display (m, cm, ft, in; set in Settings).
- **Origin:** the room's top-left corner. +x runs along the room length, +y along the width, +z up. Racks and obstacles are rectangles `(x, y, w, d)`.
- **Grid:** `columns = floor(L/G)`, `rows = floor(W/G)`, `full_cells = rows × columns` (with an ε guard for floating point). Partial edge strips are reported but not counted.
  - Cell states: `FREE, OBSTACLE, DOOR_CLEARANCE, WALKWAY, RACK, RESTRICTED, UNCERTAIN`.
  - A cell is marked conservatively if a zone touches any part of it.
- **Layout engine** (`services/layout.py`):
  - Generates wall-aligned row patterns in both orientations (back-to-back or single-sided, aisle-first or rack-first, wall-aligned or centred).
  - Places racks greedily along each row, skipping positions that hit obstacles.
  - Re-checks every candidate with an **independent validator**, prunes offending racks, de-duplicates the results and ranks them.
- **Hard constraints** (never traded against score):
  - Inside the room, with wall clearance.
  - Rack height plus ceiling clearance fits under the ceiling.
  - No obstacle overlap, and obstacle clearance kept.
  - No door access zone used.
  - No rack overlap, and the minimum rack gap kept.
  - A clear walkway along at least one long side.
  - That walkway is **reachable from the door** through a passage of the minimum width. This uses raster erosion plus connected components.
  - If no layout fits, the response explains why and suggests concrete changes.
- **Utilisation** = total rack footprint ÷ room floor area.
- **Capacity** = `plants_per_level × levels_per_rack × rack_count`. Plants per level comes from crop spacing minus tray edge margins, or a user override. The page warns when the crop is taller than the level gap.

### Data provenance labels

| Label | Meaning |
|---|---|
| `USER_INPUT` | Something the user entered |
| `RULE` | A deterministic, documented rule; never presented as AI |
| `ILLUSTRATIVE` | A sample price, not a quote |
| `SIMULATED` | Generated by the sensor simulator |
| `ESTIMATE` | Calculated from listed assumptions |

The crop catalogue (`backend/app/data/crops.json`) carries a provenance note and a review date. Unknown values stay `null`.

---

## Feature checklist

| Area | Status | Notes |
|---|---|---|
| Sign-up/in/out, bcrypt, httpOnly JWT cookie, CSRF header, ownership checks, rate limit on auth | **Complete** | Rate limiter is in-process (per instance) |
| Projects: create, rename, duplicate, archive, delete (confirmed) | **Complete** | Designs can be duplicated, activated and deleted |
| Room wizard: units, validation, review, save progress, assumptions | **Complete** | |
| Photo upload: type/size/content checks, random stored names, preview, camera capture | **Complete** | |
| Photo analysis | **Complete with API key** | AI reads room size, light and objects (estimates, user confirms). OpenCV quality checks always run. Live provider calls are verified only by mocked-response tests here. |
| Budget-first auto planner (never over budget) | **Complete** | Heuristic search over 4 rack sizes, levels and counts; not a global optimiser |
| Location, season, weather | **Complete** | Season by rule; weather from Open-Meteo when reachable |
| AI crop advisor (trends, prices, sources) | **Complete with API key** | Output labelled MODEL; prices are estimates to verify locally |
| Obstacle / door / window / restricted-zone editor (drag, numeric edit, confirm, delete) | **Complete** | Rectangles only (no free-form polygons) |
| Grid generation and cell states, configurable cell size | **Complete** | |
| Layout generation, ranking, infeasibility diagnosis | **Complete** | Heuristic row patterns, not a global optimiser |
| Interactive rack editor: drag, rotate, add, remove, nudge, undo/redo, live server validation, save blocked when invalid | **Complete** | |
| 2D plan: zoom, pan, select, layers, legend, dimensions | **Complete** | |
| 3D planning model: racks, levels, plants, lights, obstacles, walkways, labels, orbit, toggles | **Complete** | Planning model, not a digital twin |
| Crop recommendations: filters, weighted scores, reasons, missing inputs, compare, assign | **Complete** | Rule-based. **No ML model is trained or deployed** (no validated dataset). |
| BOM: editable qty/price, include/exclude, custom lines, one-time vs monthly, CSV | **Complete** | Prices are illustrative until edited |
| Market prices | **Partial** | User-entered assumptions only; live provider adapter not implemented |
| Profitability (revenue, margin, payback) | **Complete** | Only shown when price and yield exist; many crops have unknown yield |
| What-if scenarios: preview, save, compare, re-evaluate, apply as new design | **Complete** | Base design is never overwritten |
| Simulator: start, pause, stop, modes (normal/warning/abnormal), interval, backfill, persisted records | **Complete** | |
| Charts (from stored records), time ranges, table view, CSV export | **Complete** | |
| Configurable thresholds, rule alerts (deduplicated, auto-resolve), acknowledge/resolve | **Complete** | |
| Insights centre with category, priority, evidence, action, source type, dismiss | **Complete** | |
| Reports: on-screen, PDF, BOM CSV, sensor CSV, print | **Complete** | |
| Settings: display units, profile, password change (revokes other sessions) | **Complete** | |
| Help / feature status / health | **Complete** | |
| ESP32 / MQTT hardware, actuators | **Not implemented** | The shared `ingest()` path and sensor schema are ready for an adapter |
| Disease detection, yield forecasting, anomaly ML | **Not implemented** | Requires validated datasets |
| Cloud hosting | **Not implemented** | Dockerfiles and Compose provided |

## Performance notes

- Layout validation uses a spatial hash for rack and walkway checks (about O(n) instead of O(n²)). A 60×40 ft hall plans in about 0.5 s, down from 9 s.
- The budget planner binary-searches the largest affordable rack count. Setup cost never decreases as racks are added.
- Sensor history is averaged in SQL (SQLite and PostgreSQL). Seven days of readings at 5-second intervals (about 120k rows) chart in about 0.1 s.
- Weather is cached for 1 hour (failed lookups for 5 minutes). The alert bell uses a lightweight count endpoint.
- Every page is lazy-loaded. Single-server mode gzips responses and caches hashed assets for a year, so first load is about 145 KB instead of 625 KB.
- `start-verdant.bat` reinstalls Python packages only when `requirements.txt` changes.

## Known limitations

- Rooms, racks and obstacles are axis-aligned rectangles; rotation is 0° or 90°.
- The layout heuristic finds good, valid layouts but does not guarantee the global maximum rack count.
- The simulator runs inside the API process (an asyncio loop) and suits a single API instance. Use a separate worker for horizontal scaling.
- Simulated light follows the crop photoperiod in UTC hours.
- Crop ranges are indicative catalogue values, not cultivar-specific agronomy. Review them before buying anything.
- Tokens use an httpOnly cookie and a required `X-Requested-With` header for writes. Bearer tokens are also accepted for API clients.

## Backup and restore

- **SQLite:** stop the API, then copy `backend/verdant.db` and `backend/storage/`.
- **PostgreSQL:**
  - Back up with `docker compose exec db pg_dump -U verdant verdant > backup.sql`.
  - Restore with `psql -U verdant verdant < backup.sql`.
  - Also back up the `uploads` volume.

## Troubleshooting

- **“Cannot reach the Verdant server”:** the API isn't running on port 8000. Set `VITE_API_PROXY` if it runs elsewhere.
- **Photo analysis FAILED:** the upload is kept anyway; use *Re-run analysis* on the obstacles page.
- **3D view blank:** WebGL is disabled in your browser. The 2D plan shows the same geometry.
- **Schema errors after pulling changes:** run `alembic upgrade head`.
