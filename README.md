# ORION

**A local-first personal observability platform — as a native desktop app.**

ORION is your private command centre. It aggregates life data across finance,
health, productivity, creative work, calendar, learning, football and personal
projects, then turns it into clean visual insights inside a dark, futuristic,
intelligence-dashboard UI.

It runs as a **native desktop application** (Python + PySide6/Qt). There is no
browser, no hosted backend, and **no dependency on Claude, OpenAI, or any paid
LLM API** to operate. Intelligence is produced by deterministic, statistical
rules running locally.

> Status: **Phase 1 scaffold.** Foundation, design system, local data layer,
> mock connectors, deterministic insights, and all module pages are in place.
> Real integrations are stubbed (mock data only) and ready to be implemented.

---

## ORION web — the deployed cockpit

`app/web` serves the same database as a **PWA life cockpit** (this is what runs
on Fly.io; see `docs/DEPLOY.md`). It is the primary day-to-day surface:

- **Today** — time-aware command centre: readiness, sleep debt, calendar strip,
  primary action, mission plan, domain cards (Body / Training / Mind / Fuel).
- **Train** — plan workbench, weekly running target (adaptive, ±10% guardrail,
  overridable in Settings), full strength cockpit (sets/reps/RPE, templates,
  PRs, analytics).
- **Health** — body telemetry with tap-to-drill drawers on every metric:
  7/30/90-day trends, baselines, what-it-means, how-it's-calculated, caveats.
  Transparent readiness formula and a personal-need sleep-debt model.
- **Fuel** — zero-subscription nutrition: barcode scan (native
  BarcodeDetector + manual fallback), Open Food Facts + UK generic references +
  local corrections, quick add, water, meal timeline, saved meals,
  deterministic daily/weekly insights.
- **Route Atlas** — GPS runs mapped on dark Leaflet/OSM tiles, named routes,
  attempts, PBs, pace trends, match suggestions with confidence, GPX in/out.
- **Mind** — morning brief / evening debrief with labelled scales, CBT thought
  check, Stoic practice mapped to virtues, breathing-orb meditation timer,
  mood/stress trend drilldowns.
- **Calendar** — week orbit with transparent load scores, free-evening flags,
  manual events, UK public holidays (Nager.Date).
- **Money** — monthly position, accounts, transactions, ECB currency context
  (Frankfurter).
- **Data Vault** — imports (HAE JSON / GPX / CSV with row-level reporting),
  full JSON + per-table CSV + GPX export, external-signal status board, and
  `POST /api/ingest/hae` so the Health Auto Export app can push exports
  straight to the server (`ORION_INGEST_TOKEN`).
- **Settings** — targets, location for weather, theme intensity, adapters.

External signals (Open-Meteo weather/air, Nager.Date, Frankfurter,
Open Food Facts) are **free and keyless**, cached server-side, ambient-only,
and degrade to a quiet stale/unavailable state — they never gate core features.

```bash
uv run orion-web         # http://127.0.0.1:8321 — passphrase "orion" in dev
```

---

## Screens

- **Login / unlock** — cinematic star-field with the Orion constellation subtly
  highlighted, over a dark glass card.
- **Command centre** — sidebar navigation, top bar, modular metric cards,
  charts, a constellation-style radar, and timeline panels.

(Render screenshots to `/tmp` with the dev snippet in *Development* below.)

---

## Quick start

Requirements: **Python 3.11+** and [`uv`](https://docs.astral.sh/uv/) (or any
venv + pip).

```bash
cd orion
uv venv --python 3.12
uv pip install -e ".[dev]"

# Launch the desktop app (first run auto-creates + seeds the local DB)
uv run orion
#   or:  uv run python -m app.main
```

Unlock passphrase in development: **`orion`** (see *Security*).

Reseed / reset the local demo data at any time:

```bash
uv run python -m app.db.seed --reset
```

Run the tests:

```bash
uv run pytest
```

---

## Web access (phone / browser)

The personal OS is also served as a **mobile-first webapp** over the same
local database — no hosted backend, no new data path. It renders the same
deterministic read models (`app/domains/personal_os.py`) the desktop app uses:
Today, Training, Run Plan, Recovery, Money, Mind and Data, including workout
logging, mind check-ins and mindfulness logging from the phone.

```bash
uv run orion-web                          # this Mac only: http://127.0.0.1:8321
ORION_WEB_HOST=0.0.0.0 uv run orion-web   # reachable from your phone on the LAN
```

Or double-click **`~/start-orion-web.command`**, which binds to the LAN and
prints the exact URL to open on your phone (add it to the iPhone home screen
via Share → Add to Home Screen for an app-like feel).

Access is gated by the same unlock passphrase as the desktop login
(`ORION_UNLOCK_PASSPHRASE`); sessions are signed cookies backed by a
per-install secret in the app-data directory (or `ORION_WEB_SECRET`). Do not
port-forward it raw to the public internet.

To reach it away from home, see [`docs/DEPLOY.md`](docs/DEPLOY.md): the
recommended path is Tailscale (data stays on your Mac), and the repo also
ships a production `Dockerfile` for container hosts (Fly.io / Railway /
Render) with a persistent volume. Static hosts like Netlify cannot run a
stateful Python server — the doc explains the equivalents that can.

Health Auto Export can push into the web app at `POST /api/ingest/hae`. Enable
it with `ORION_INGEST_TOKEN` on the host, or log in to Data Vault and generate
a database-backed HAE token after deployment.

---

## Architecture

```
orion/
├── app/
│   ├── main.py                 # entry point: window, bootstrap, scheduler
│   ├── services.py             # read-model layer the UI calls (no ORM in UI)
│   ├── core/                   # config, security, logging
│   ├── db/
│   │   ├── database.py         # engine/session (SQLite now, PostgreSQL-ready)
│   │   ├── models.py           # all ORM models (5 data layers)
│   │   ├── seed.py             # mock data seeder
│   │   └── migrations/         # MVP = create_all; Alembic path documented
│   ├── ui/
│   │   ├── themes/             # design system (palette, type, QSS)
│   │   ├── components/         # Sidebar, TopBar, cards, charts, constellation
│   │   ├── screens/            # login, shell, pages
│   │   └── navigation.py       # the module list
│   ├── domains/                # per-domain space (finance, health, ...)
│   ├── integrations/           # placeholder connectors (mock only)
│   ├── ingestion/              # generic Connector interface + registry
│   ├── analytics/              # deterministic insight engine (NO LLM)
│   └── jobs/                   # APScheduler background jobs
├── tests/
├── packaging/orion.spec        # PyInstaller spec (macOS .app)
├── pyproject.toml
└── .env.example
```

### The five data layers

ORION deliberately separates the stages data moves through. The schema in
[`app/db/models.py`](app/db/models.py) reflects this:

| Layer | Meaning | Tables |
|------:|---------|--------|
| 1 | Raw imported data | `RawImport` |
| 2 | Normalised records | `Transaction`, `Account` |
| 3 | Daily snapshots | `BalanceSnapshot`, `HealthMetricDaily`, `ActivityMetricDaily`, `ProjectMetricDaily` |
| 4 | Derived metrics | computed from the snapshot tables in `services.py` |
| 5 | Insights | `Insight` (deterministic) |

Foundational entities: `User`, `DataSource`, `RawImport`, `Account`,
`Transaction`, `BalanceSnapshot`, `HealthMetricDaily`, `ActivityMetricDaily`,
`Project`, `ProjectMetricDaily`, `Insight`, `ScheduledJobRun`.

### Layering & decoupling

- **UI → services → DB.** Screens never touch the ORM; they call
  [`app/services.py`](app/services.py), which returns plain dicts / dataclasses
  / DataFrames. Swapping SQLite for PostgreSQL, or moving work to a thread, is a
  one-place change.
- **Connectors are replaceable.** Every integration implements the same
  [`Connector`](app/ingestion/base.py) lifecycle (`connect → fetch_raw_data →
  store_raw_data → normalise_data → store_normalised_data → update_snapshots →
  generate_metrics`) and is discovered through
  [`app/ingestion/registry.py`](app/ingestion/registry.py).
- **Modules are isolated.** Each navigation module has its own page; adding one
  is a single entry in [`app/ui/navigation.py`](app/ui/navigation.py).

### Local-first storage

The SQLite database lives in the per-user OS app-data directory (resolved by
`platformdirs`, e.g. `~/Library/Application Support/ORION/orion.db` on macOS).
It is never committed. Set `ORION_DATABASE_URL` to a PostgreSQL URL to scale out
later without code changes.

### Deterministic intelligence (no LLM)

[`app/analytics/engine.py`](app/analytics/engine.py) produces every insight from
rules and statistics over the user's data — e.g. *"Spending is 18% higher than
last month"*, *"Average sleep is down 42 minutes this week"*, *"Deep work
increased compared to last week"*. Adding an insight = adding a small pure
function to `RULES`. A test (`tests/test_analytics.py`) guards that no hosted-LLM
client is ever imported here.

The Tasks **Command Inbox** follows the same rule: messy brain dumps are parsed
locally by [`app/domains/productivity/inbox_parser.py`](app/domains/productivity/inbox_parser.py)
using text splitting, keyword matching, date phrase detection, priority scoring,
and area/category inference. It deliberately has no OpenAI, Anthropic,
server-side LLM, paid parsing API, or external inference dependency; suggestions
must be reviewed in the UI before they are saved.

### Background jobs

[`app/jobs/scheduler.py`](app/jobs/scheduler.py) runs APScheduler on a background
thread inside the app: `sync_sources` (runs the mock connector pipelines) and
`refresh_insights` (re-runs the analytics engine). Each run is recorded in
`ScheduledJobRun`. The job functions are plain callables, so this can later be
swapped for Celery without touching the UI.

---

## Integrations (placeholders)

All connectors currently emit **mock data only — no live API calls.** Each is a
self-contained, replaceable package under `app/integrations/`:

| Connector | Domain | Real-data plan |
|-----------|--------|----------------|
| Starling Bank | finance | Personal Access Token from OS keychain; **never store bank logins** |
| Trading 212 | finance | REST API + key from OS keychain |
| Coinbase | finance | API key/secret or OAuth |
| Moneybox | finance | export / supported endpoint |
| Apple Health | health | parse local `export.xml` |
| ActivityWatch | productivity | query local server at `:5600` |
| Google Calendar | calendar | OAuth + Calendar API |
| Notion | creative | official API + integration token |
| Football Manager | football | parse FM export files locally |

---

## Security

ORION will eventually hold financial and health data, so the scaffold encodes
the right habits and marks the gaps:

- **Never stores bank login credentials.** Open Banking is designed for
  OAuth/consent flows.
- **No secrets in code.** Tokens come from environment variables today
  (`.env.example`); `TODO(security)` comments mark where they move to the OS
  keychain (`keyring`).
- **No raw payload logging in production.** `RawImport` payloads are not logged
  at INFO; `core.security.redact()` masks secret-like keys before logging.
- **Demo vs real data are separate.** Everything the seeder writes is mock and
  flagged `status=mock` on its `DataSource`.
- **Unlock gate.** The login screen uses `core.security.verify_unlock`. In
  development the demo passphrase is `orion`; set `ORION_UNLOCK_PASSPHRASE` to
  override. `TODO(security)`: derive a key via a real KDF (argon2id) and use it
  to encrypt the SQLite file at rest (e.g. SQLCipher) before real data lands.

Environment variables are documented in [`.env.example`](.env.example). None are
required to launch the demo.

---

## Packaging

macOS first, then Windows/Linux.

### Build the double-clickable macOS app

One command builds `dist/ORION.app` and (optionally) installs it to
`/Applications` so it appears in Finder and Launchpad:

```bash
./packaging/build_macos.sh            # -> dist/ORION.app
./packaging/build_macos.sh --install  # also copies to /Applications/ORION.app
```

Then **double-click `ORION.app`** to launch — no terminal, no Python install
required on the target machine.

> First launch on another Mac: because the app is ad-hoc signed (not notarised),
> macOS Gatekeeper may warn. Right-click the app → **Open** → **Open**, once.
> To distribute it widely, sign with a Developer ID and notarise.

Under the hood this runs **PyInstaller** with the provided spec:

```bash
uv pip install -e ".[packaging]"
uv run pyinstaller packaging/orion.spec --noconfirm
# -> dist/ORION.app
```

The bundle ships Python + Qt + the app, but **not** the database — the local
SQLite file is created at runtime in the user's app-data directory, so personal
data never ships.

**Briefcase** is a good alternative for signed native installers per OS; the
`app` package is already import-clean for it.

---

## Development

```bash
uv run ruff check app tests      # lint
uv run pytest                    # tests
```

Render screenshots headlessly (no display needed):

```bash
QT_QPA_PLATFORM=offscreen uv run python - <<'PY'
from PySide6.QtWidgets import QApplication
from app.core.logging import configure_logging
from app.db.database import init_db
from app.db.seed import seed
from app.services import get_default_user_id
from app.ui.themes.theme import build_stylesheet
from app.ui.screens.login import LoginScreen
configure_logging(); init_db()
if get_default_user_id() is None: seed()
app = QApplication([]); app.setStyleSheet(build_stylesheet())
w = LoginScreen(); w.resize(1320, 860); w.show()
app.processEvents(); app.processEvents()
w.grab().save("/tmp/orion_login.png")
PY
```

---

## Next steps (Phase 2+)

1. **Implement a first real connector** (suggest ActivityWatch — fully local) by
   filling its `fetch_raw_data` / `normalise_data` / `store_normalised_data`.
2. **Move tokens to the OS keychain** (`keyring`) and wire the Settings page to
   connect/disconnect sources.
3. **Encrypt at rest** — KDF from the unlock passphrase + SQLCipher.
4. **Adopt Alembic** when schema changes go non-additive (see
   `app/db/migrations/README.md`), and validate the PostgreSQL path.
5. **Flesh out module pages** (Creative, Calendar, Learning) with their own
   metrics and charts, mirroring Finance/Health/Productivity.
6. **Customisable dashboard** — let cards be rearranged/hidden/saved per user.
7. **Sign & notarise** the macOS build; add Windows/Linux packaging.

## License

MIT.
