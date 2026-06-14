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
| Open Banking / GoCardless | finance | OAuth + consent; **never store bank logins** |
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

**PyInstaller** (spec provided):

```bash
uv pip install -e ".[packaging]"
uv run pyinstaller packaging/orion.spec
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
