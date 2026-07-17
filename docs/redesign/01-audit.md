# Orion Redesign — Stage 1: Audit

_Basis: inspection of the live web layer on branch `web-life-cockpit` (13 routers, ~30 Jinja templates, `app/web/static/orion.css` at 3,831 lines, and the `app/domains/*` read-model layer). No code changed. This document is evidence for Stages 2–6; it does not propose visuals yet._

## 0. What Orion actually is today (so the redesign starts from fact, not the brief's assumptions)

- **Stack is server-rendered, not React/Next.** FastAPI + Jinja2 + one hand-written CSS file + vanilla JS (`orion.js`, `orion-charts.js`), delivered as an installable PWA with a service worker and an offline write-queue. The brief's "prefer React/Tailwind" is a generic template; the real decision for Stage 6 is **evolve the Jinja+token system** vs **port to a build step**. The audit assumes evolution unless Stage 6 argues otherwise — the existing separation of concerns is good enough to keep.
- **The data layer is already clean and centralised.** Every screen renders a frozen dataclass "snapshot" produced by `app/domains/personal_os.py` (readiness, today, run plan, workout tracker, mind, finance, data inventory) or a sibling service (`strength.py`, `nutrition/service.py`, `mental_health`, `stoic`, `fitness`). The web layer is forbidden from scoring or interpreting (`app/web/context.py` docstring). **The redesign's problems are almost entirely in presentation, not in data ownership.** This is the single most important audit finding.
- **The desktop app (PySide6) is a superset.** Domains `career`, `creative`, `diploma`, `football`, `learning`, `productivity`, `projects` exist but have **no web router**. The web app is a focused subset (health/training/nutrition/mind/money/tasks/data). The redesign is scoped to the web surface.

---

## 1. Screen inventory

| Route(s) | Template | Nav home | Purpose today | State |
|---|---|---|---|---|
| `/` | `today.html` | Dock: Today | "Today's Command": hero status + primary action, calendar strip, "Mission plan" (3 plan items), "Findings", "Jump into your day" (4 domain cards) | Real |
| `/training` | `training.html` | Dock: Train | Today's run rec + 3 support cards (weekly running / strength consistency / **readiness**), 7-day week plan, plan workbench, recent logs | Real |
| `/run` | `run.html` | (under Train) | Running plan detail, route suggestions | Real |
| `/routes`, `/routes/{id}` | `routes.html`, `route_detail.html` | (under Train) | Route Atlas: GPX maps, attempts, PBs | Real (map = Leaflet/Carto tiles) |
| `/strength` + `/strength/start`, `/templates`, `/workout/{id}`, `/exercises/{id}`, `/history`, `/analytics` | `strength_*.html` (11 templates) | (under Train) | Full strength cockpit: templates, active workout, set logging, exercise history, analytics/e1RM | **Real & complete** |
| `/health` (+ `/recovery` alias) | `health.html` | Dock: Health | "Body Telemetry": readiness hero, factor breakdown, primary signals, sleep debt, secondary signals, findings, changes, deep-dive drawers | Real |
| `/nutrition` + `/nutrition/scan` | `nutrition.html`, `nutrition_scan.html` | Dock: Fuel | Daily/weekly fuel, search, barcode, quick-add, templates, corrections | **Real & complete** (local-first + Open Food Facts) |
| `/mind` + `/mind/morning`, `/mind/evening`, `/stoic` | `mind.html`, `mind_flow.html`, `stoic.html` | Dock: Mind | Morning brief / evening debrief, mood scales, thought record (CBT), mindfulness, stoic practice | Real; `mind_flow` is an immersive full-screen flow |
| `/calendar` | `calendar.html` | More | "Week orbit": events, per-day load score, holidays | Real (manual + import) |
| `/tasks` | `tasks.html` | More | Open-loop list grouped by area | Real (mirrors external task source) |
| `/money` | `money.html` | More | Monthly position, accounts, transactions, FX | Real **only if** a bank import ran; connectors are mock (see §8) |
| `/data` | `data.html` | More | Data Vault: imports, exports (CSV/JSON/GPX), freshness, signal status | **Real & complete** |
| `/settings` | `settings.html` | More | Targets, location, units, theme intensity | Real |
| `/login` | `login.html` | — | Passphrase unlock (starfield screen) | Real |

**Structural note:** the mobile dock already carries exactly 5 items + More — the brief's cardinality is met. But the five are **domains** (Today / Train / Health / Fuel / Mind), not **loop stages** (Today / Plan / Log / Insights / More). There is no unified **Log**, no unified **Insights**, no unified **Plan**, and no **Habits / Goals / Medication** surface at all (see §8 gaps).

## 2. Component inventory

**Shared macro library** (`app/web/templates/_macros.html`) — a real vocabulary already exists:

| Macro | Renders | Reused well? |
|---|---|---|
| `metric_card(m, detail)` | value + delta-vs-7-day + interpretation + sparkline + drilldown | **No** — Health/Today/Training hand-roll their own equivalents instead |
| `signal_board` | primary/secondary/missing partition | Partially |
| `score_ring` | SVG readiness ring | Yes |
| `insight_queue` | findings list (title/severity/body/action/confidence) | Yes (Today, Health) |
| `empty_state` | compact icon + title + body + CTA | Yes — and it is genuinely compact |
| `progress_line`, `freshness`, `source_chip`, `scale_input`, `severity_pill`, `toast` | supporting primitives | Mixed |

**JS/behaviour components:**
- `orion-charts.js` (15 KB) — chart engine with per-vital colour, typical-range band, hover crosshair. Powers the **detail drawer** charts only.
- Detail drawer: `data-detail="<kind>"` → `GET /api/detail/{kind}` (`routes/api.py`) → `metric_details.get_metric_detail()` → rendered chart + facts.
- Offline write protocol: `apply_client_mutation` + `client_mutation_id` + `X-Orion-Queue` header + `orion-sw.js` (service worker) + IndexedDB queue in `orion.js`.
- `orion-map.js` (Leaflet), `orion-scan.js` (barcode via camera).

**Chrome components (`base.html`):** starfield `.atmosphere` SVG, masthead (mono "Orion" brand + weather pill + date stamp), `pagehead` H1 + `module_code` chip, `statusline`, `nav.dock`, `more-sheet`, generic `drawer`.

## 3. Data inventory (the source-of-truth layer)

Every metric already has **one** authoritative producer. This is the backbone the redesign inherits.

| Read model (dataclass) | Producer | Feeds |
|---|---|---|
| `RecoverySnapshot` (score, factors, metrics, changes, recommendation, data_quality) | `personal_os.get_recovery_snapshot` | Health, Today, Training |
| `TodaySnapshot` (status, score, recs, plan, insights, freshness) | `personal_os.get_today_snapshot` | Today |
| `RunPlanSnapshot` (goal, weekly target/distance, pace, next_run, weekly_plan, adherence) | `personal_os.get_run_plan_snapshot` | Training, Run |
| `WorkoutTrackerSnapshot` (recent sessions, weekly volume/sessions, PBs, progression) | `personal_os.get_workout_tracker_snapshot` | Training |
| Strength `dashboard/analytics/workout_detail/...` | `domains/strength.py` | Strength cockpit |
| Nutrition `day_snapshot/week_snapshot/search/...` | `domains/nutrition/service.py` | Nutrition, Today |
| `MindSnapshot` (mood, stress, streaks, calendar, reflections, protocol) | `personal_os.get_mind_snapshot` | Mind, Today |
| `FinanceOperatingSnapshot` | `personal_os.get_finance_operating_snapshot` | Money, Today |
| `DataInventorySnapshot` | `personal_os.get_data_inventory` | Data Vault |
| **Metric detail** (latest, series, rolling7, baseline7/30, typical band, source, freshness, `how`/calc, caveat, related, facts, missing_action) | `domains/health/metric_details.py` (`MetricSpec` registry) | Every `data-detail` drawer |

**`metric_details.py` already implements the brief's "every metric must show" checklist** (current value, baseline, normal range/band, direction, period controls via `days`, source, freshness, calculation transparency, related metrics, honest caveat, missing-data action). It is the redesign's biggest reusable asset.

Underlying tables (`app/db/models.py`): `HealthMetricDaily`, `ActivityMetricDaily`, `MentalCheckIn`, `MindfulnessSession`, `Workout`/`WorkoutSessionLog`, `FoodLog`/`NutritionFood`/`MealTemplate`, `FitnessRoute`/`RouteAttempt`, `CalendarEvent`, `Task`, `Account`/`Transaction`, `StoicEntry`, `Insight`, `ClientMutation`, `ExternalSignalCache`, `RawImport`, `DataSource`.

## 4. Duplication map (the core UX defect — presentation, not data)

Because three screens each read `RecoverySnapshot`, the same numbers are rendered in three visual forms:

| Metric | Appears on | Verdict |
|---|---|---|
| **Readiness score** | Today (status-strip button **and** hero number) · Health (hero **and** factor breakdown) · Training (support card with meter) | Rendered **4 times** across 3 screens. Should have **one** authoritative home (Recovery/Health) + at most one contextual reference elsewhere. |
| **Sleep debt** | Today status-strip · Health full section · detail drawer | 3 places |
| **HRV / Resting HR** | Health primary signals · Health factor list · Today "Body telemetry" card · deep-dive drawers | 4 surfaces |
| **Weekly running (km / target)** | Today domain card · Training support card · Training statusline · Run page | 4 places |
| **Strength sessions this week** | Today domain card · Training support card · Training statusline | 3 places |
| **Findings / insights** | Today "Findings" · Health "Findings" (same `insight_queue`, filtered) | Scattered; no single Insights home |

Root cause: no rule assigning each metric a **single authoritative screen**. Stage 2 §5 fixes this with a data-ownership map.

## 5. UX problems (against the brief's acceptance criteria)

1. **Repetition of numbers** — see §4. Violates "no metric repeatedly displayed without contextual justification."
2. **Coaching prose the brief explicitly bans** — daypart lines "Mid-flight. Adjust, don't restart.", "Wind down. Tomorrow is built tonight."; section names "Today's Command", "Mission plan"; body copy "a simple full-body session opens the account", "Quiet is a valid state." (`today.html:21,74`, `routes/today.py` `_DAYPART_LINES`). These are almost verbatim on the brief's removal list.
3. **Spaceship-terminal identity** — starfield atmosphere, mono letter-spaced "ORION", module codes `TDY-00`/`BIO-02`/`TRN-01` (`context.py` `MODULE_CODES`), drawer loader "Reading telemetry…". The brief bans "spaceship terminal / cyberpunk / monochrome."
4. **Low information density** — pages are tall stacks of full-width panels; single numbers occupy large vertical space (Health hero ≈ full viewport before any signal appears).
5. **Repetitive card design** — Today's "Jump into your day" is four near-identical `domain-card` rounded rectangles; Training's support row is three near-identical `fitness-card`s.
6. **Oversized empty placeholders** — Training's week plan renders **7 day columns each labelled "Open"** (`training.html:124`), the brief's exact complaint. (Note: the `empty_state` macro itself is compact and good — the problem is bespoke empties like this and `empty-fitness`.)
7. **Weak analysis on the surface** — real trend charts live only inside the drawer; the page body relies on tiny 100×28 sparklines. Brief: "tiny meaningless sparklines should not substitute for proper analysis."
8. **Unclear interactive hierarchy** — passive `domain-card`, tappable `metric`, and real buttons share border/radius/padding; a link and an action look alike.
9. **No cross-domain synthesis** — "how am I / what changed / am I improving" is answered per-silo, never in one Insights view.

## 6. Responsive problems

1. **Desktop is the mobile dock rotated.** `orion.css` sets `--dock-w: 218px` and turns `nav.dock` into a left rail; `.wrap` becomes `width: calc(100vw - dock-w)` single column. There is **no** multi-column workspace, **no** contextual right rail, **no** comparison layout. This is precisely "a mobile layout stretched across a desktop monitor."
2. **No desktop navigation grouping.** The brief wants Daily / Plan-and-record / Understand / System groups; desktop just lists dock items + `NAV_MORE` under a divider.
3. **Only one theme (dark).** `:root` defines a single dark palette (`--void: #030304`); the only `[data-theme=...]` variants are `observatory`/`subtle` (both dark intensities). The brief **requires** working light **and** dark themes.
4. **Nearly monochrome.** One cyan accent (`--accent: #8ae6ff`) + good/warn/crit. The brief's semantic domain colours (sleep=indigo, recovery=teal, running=cyan/blue, strength=orange, cardio=coral, mind=violet, nutrition=green, meds=amber) are largely absent, so colour can't do category/hierarchy work.
5. **Charts don't adapt.** No documented mobile-simplified vs desktop-interactive chart tiers; the sparkline/drawer split is the only responsiveness.

## 7. Features that work (retain the capability)

- **Metric-detail engine** (`metric_details.py`) — retain as the *single metric authority*; promote it from drawer-only to a first-class detail surface.
- **Chart engine** (`orion-charts.js`) — retain; extend to page-level charts, comparison periods, light/dark.
- **Detail-drawer pattern** (`data-detail` → `/api/detail`) — retain as the universal "reveal evidence / view history" mechanism.
- **Offline write protocol** (idempotent `client_mutation_id`, queue, SW) — retain; it is exactly what a fast Log flow needs.
- **Strength cockpit** — retain wholesale; only re-home its entry point under a redesigned Training/Log.
- **Nutrition** (local-first, barcode, corrections-win) — retain wholesale.
- **Data Vault** (full export, freshness, source status) — retain; it satisfies the brief's data-quality/trust requirements.
- **Domain read-model architecture** (web renders, never scores) — retain; it is why de-duplication is a template problem, not a data problem.
- **Security posture** (CSP, session gate, no inline JS) — retain.

## 8. Features that are only visual placeholders / gaps

- **Integration connectors are mock scaffolds** (README §Integrations): Starling, Trading 212, Coinbase, Moneybox, Notion, Google Calendar, ActivityWatch, Football Manager emit mock data. (Project memory notes the *live instance* now ingests real Health Auto Export + Starling data, so health/nutrition/training are real; **Money is real only where a real import has run**, otherwise placeholder.)
- **Reporting/analytics are partial** — `insight_queue` shows stored `Insight` rows, but there is no weekly/monthly **Report** generator on the web surface, and no cross-domain **Insights** screen.
- **Missing modules the brief's product definition requires:**
  - **Medication & supplements** — no module at all.
  - **Habits & routines** — none (Tasks ≈ open loops, not recurring habits with streaks).
  - **Goals & planning** — no unified Goals; only a training *block* and finance *targets*.
  - **Journalling** — exists only as the Mind evening note + thought record; not a first-class Journal.
  - **Schedule / Check-in** — no dedicated destinations (calendar ≈ schedule; check-in ≈ mind flow).

## 9. Components to retain vs remove

**Retain (structure/behaviour):** `metric_details` registry · `orion-charts.js` · detail-drawer API · offline write protocol · `_macros.html` primitives (`metric_card`, `insight_queue`, `empty_state`, `progress_line`, `source_chip`, `freshness`, `scale_input`) · strength/nutrition/data-vault templates as functional modules · domain read-model layer · auth/CSP.

**Remove or replace (identity/layout):**
- Starfield `.atmosphere`, `--void` background, `cinematic/observatory/subtle` "theme intensity" model → replace with neutral light/dark foundation + semantic domain colours.
- `MODULE_CODES` chips (`TDY-00` …), mono letter-spaced "ORION" masthead brand, "Reading telemetry…" copy.
- Daypart coaching lines + "Today's Command" / "Mission plan" naming (`routes/today.py`, `today.html`).
- Today "Jump into your day" `domain-card` grid → replace with prioritised recommendation + evidence + timeline.
- Training's three duplicated `fitness-card` support cards (they re-show Health's readiness/sleep).
- The 7 "Open" day columns as the week plan's empty state.
- **The desktop = rotated-dock layout** → replace with real sidebar + workspace + right rail.
- Hand-rolled `health-signal` / bespoke metric markup in `health.html`, `today.html`, `training.html` → consolidate onto one metric component.

---

_Continued in `02-product-structure.md` (Stage 2)._
