# Orion Redesign — Stage 2: Product Structure

_Depends on `01-audit.md`. This defines the information architecture, navigation, screen responsibilities, data-ownership, journeys, and responsive rules. **No visual/production code** — that is Stage 3+._

## Design premise

The current IA is organised by **domain** (Health, Fuel, Mind). The redesign reorganises around the **core loop** — Understand → Decide → Act → Record → Review — because that is what the brief's five questions describe:

| Brief question | Loop stage | Primary screen |
|---|---|---|
| How am I today? | Understand | **Today** |
| What has meaningfully changed? | Understand / Review | Today (top changes) → **Insights** |
| What should I do next? | Decide | **Today** (one recommendation + evidence) |
| Am I following my plans? | Act / Review | **Plan** |
| Am I improving over time? | Review | **Insights** |

Recording (Log) is the connective action available from everywhere. Domains (Health, Training, Nutrition, Mind…) become **deep destinations**, not the top-level spine.

---

## 1. Revised sitemap

```
Today  ─────────────────  operational "now" view (/)
Plan   ─────────────────  /plan
  ├─ Schedule (week)      /plan (default tab)  ← absorbs /calendar week-orbit
  ├─ Training programme   /plan/training       ← absorbs training block + week plan
  ├─ Habits & routines    /plan/habits         ← NEW
  ├─ Goals & milestones   /plan/goals          ← NEW (unifies training block goal + finance targets + new)
  └─ Planned meals        /plan/meals          ← surfaces nutrition templates on the calendar
Log    ─────────────────  /log  (quick-entry hub, centre-emphasised)
  └─ strength · run/cardio · meal · weight · mood · medication · supplement ·
     journal · symptom · habit tick · note        (each opens its fast sheet)
Insights ───────────────  /insights
  ├─ Overview (7/30/90 + compare)                 ← NEW cross-domain
  ├─ Metric detail          /insights/metric/{kind}  ← promotes metric_details.py to a page
  ├─ Reports (weekly/monthly)                        ← NEW
  ├─ Personal records                                ← absorbs strength/run PBs
  └─ Data quality                                    ← from DataInventorySnapshot
More / deeper destinations
  ├─ Health        /health      (cardiovascular + body metrics hub)
  ├─ Recovery      /recovery     (readiness, sleep, HRV, RHR, strain — split from Health)
  ├─ Training      /training     (running + strength + routes cockpit)
  ├─ Nutrition     /nutrition
  ├─ Mind          /mind         (mood, journal, mindfulness, stoic)
  ├─ Medication    /medication    ← NEW
  ├─ Money         /money
  ├─ Tasks         /tasks
  ├─ Integrations  /integrations  ← split out of Data + Settings
  ├─ Data sources  /data          (Data Vault)
  └─ Settings      /settings
Auth: /login
```

**Key IA decisions**
- **Health vs Recovery are split** (brief lists both). Recovery owns readiness/sleep/HRV/RHR/strain (the decision-driving metrics); Health owns cardiovascular + body composition + longitudinal vitals (VO₂max, blood pressure, weight, respiratory rate). Both read the same `RecoverySnapshot`/`metric_details` — the split is editorial, not a data fork.
- **Training is one area** containing running, strength, and routes (today they are peers with overlapping stats). Its *plan* lives under Plan; its *cockpit/logging* under Training/Log.
- **Three genuinely new modules** are required by the brief's product definition: **Habits**, **Goals**, **Medication/supplements**. Journal is *promoted* from a Mind sub-field to a first-class destination but shares the Mind data.

## 2. Mobile navigation (below 768px)

Five persistent bottom-nav destinations, centre Log emphasised (brief-compliant):

```
[ Today ]  [ Plan ]  [ (+) Log ]  [ Insights ]  [ More ]
```

- **Today** `/` · **Plan** `/plan` · **Log** `/log` (raised FAB-style centre) · **Insights** `/insights` · **More** (sheet).
- **More sheet** exposes: Health, Recovery, Training, Nutrition, Mind, Medication, Money, Tasks, Integrations, Data sources, Settings, Lock.
- Never more than 5 persistent items (replaces today's Today/Train/Health/Fuel/Mind).
- The existing `more-sheet` component is reused; the dock's icon set is re-mapped to the 5 loop stages.

## 3. Desktop navigation (≥1200px)

Persistent **collapsible sidebar** (220–240px), grouped exactly as the brief specifies — replacing today's "rotated dock":

```
DAILY
  Today            /
  Schedule         /plan
  Check-in         /log?flow=checkin  (or /mind flow)
PLAN & RECORD
  Training         /training
  Nutrition        /nutrition
  Habits           /plan/habits
  Journal          /mind#journal
  Goals            /plan/goals
UNDERSTAND
  Health           /health
  Recovery         /recovery
  Insights         /insights
  Reports          /insights/reports
SYSTEM
  Integrations     /integrations
  Data sources     /data
  Settings         /settings
```

Mobile (5 stages) and desktop (grouped destinations) are **two views of one IA**: every desktop link is reachable on mobile via a tab or the More sheet; nothing exists on one and not the other.

## 4. Screen responsibilities (one job each)

| Screen | Single responsibility | Must NOT do |
|---|---|---|
| **Today** | Operational now: current state (compact status strip), **one** prioritised recommendation + its evidence, today's timeline, next action, 2–3 meaningful changes, sync status | Be a general analytics dashboard; re-show readiness in multiple large cards |
| **Plan** | Forward view: weekly schedule with real session content, training programme + phase, habits, goals/milestones, planned meals, conflicts | Show seven "Open" boxes; duplicate Today's recommendation |
| **Log** | Fastest possible capture of any record type; recent/favourite actions first; ≤1 tap to start on mobile; a strength set in very few interactions | Analyse or interpret; make the user navigate to a domain page first |
| **Insights** | Cross-domain review: 7/30/90 + custom + compare-to-previous; metric relationships; reports; PRs; goal projections; data quality — clearly labelling measured vs calculated vs association vs hypothesis vs recommendation | Imply causation from weak correlation; repeat Today's operational copy |
| **Health** | Body/cardiovascular hub: VO₂max, BP, weight, resp rate, longitudinal vitals; each with a full historical detail view | Own the readiness decision (that's Recovery/Today) |
| **Recovery** | Readiness authority: score + component breakdown, sleep, sleep debt, HRV, RHR, strain; the "why today looks like this" | Duplicate the same three metrics as separate hero cards |
| **Training** | The cockpit: run programme + strength + routes; log a session, see load/consistency/PBs | Re-render Health's readiness as its own card (reference it, link out) |
| **Nutrition** | Fuel: daily/weekly intake, search/barcode/quick-add, templates, corrections | — |
| **Mind** | Mood, journal, mindfulness, stoic; morning/evening check-in flows | — |
| **Medication** | Meds & supplements schedule, adherence, reminders (NEW) | — |
| **Integrations / Data sources / Settings** | Connections, imports/exports/freshness, preferences | Hide common daily actions |

## 5. Data-ownership map (each metric has ONE authoritative screen)

Because the data layer already has a single producer per metric (audit §3), ownership here means the **one screen that shows it in full**; everywhere else it may appear **only** as a contextual reference that links back.

| Metric / signal | Source module | **Authoritative screen** | May also appear (contextual only) |
|---|---|---|---|
| Readiness score + factors | `personal_os.get_recovery_snapshot` | **Recovery** | Today (single strip value → links to Recovery); Training (one chip) |
| Sleep + sleep debt | `metric_details` (`sleep`,`sleep_debt`) | **Recovery** | Today (strip) |
| HRV | `metric_details.hrv` | **Recovery** | Today (strip) |
| Resting HR | `metric_details.resting_hr` | **Recovery** | Today (strip) |
| VO₂max, Blood pressure, Respiratory rate, Weight | `metric_details` | **Health** | Insights (trend) |
| Running distance / pace / load / PBs | `get_run_plan_snapshot`, `strength`/route PBs | **Training** | Today (next action); Insights (trend, PRs) |
| Strength volume / sessions / e1RM | `domains/strength.py` | **Training** | Today (next action); Insights (PRs) |
| Calories / protein / fibre / water | `nutrition/service.py` | **Nutrition** | Today (one strip value) |
| Mood / stress / check-in streak | `get_mind_snapshot` | **Mind** | Today (mental check-in tile) |
| Mindfulness minutes / streak | `get_mind_snapshot` | **Mind** | Today |
| Medication/supplement adherence | NEW module | **Medication** | Today (timeline entries) |
| Habit adherence / streaks | NEW module | **Habits (Plan)** | Today (tasks/habits due) |
| Goals / milestones / projections | NEW + block/finance targets | **Goals (Plan)** | Today (progress); Insights (projection) |
| Money position / safe-to-spend | `get_finance_operating_snapshot` | **Money** | Today (only if a warning) |
| Findings / insights | `Insight` rows + analytics | **Insights** | Today (top 2–3 changes only) |
| Data freshness / source status | `get_data_inventory` | **Data sources** | Today (sync status); every metric detail (freshness line) |

**Rule for Stage 4:** a metric may render on a non-authoritative screen **only** as (a) a single status value, (b) a next-action driver, or (c) a labelled contextual reference that links to its authoritative screen. No second full breakdown.

## 6. Core user journeys

1. **Morning orientation (Understand→Decide→Act).** Open **Today** → status strip (Recovery/Sleep/Activity/Check-in) → **one** recommendation ("Reduce interval volume — RHR 101 vs 59 baseline") → tap **View evidence** (drawer: RHR/HRV/sleep series + confidence) → **Apply adjustment** or **Dismiss** → timeline shows the adjusted session.
2. **Record a strength set (Act→Record).** **Log** → Strength → active workout → tap set → weight/reps/RPE prefilled from last time → done. Target: a normal set in ≤ a few taps (existing `apply_last_workout` + offline queue make this achievable).
3. **Quick capture anything.** **Log** (centre tab) → recent/favourite action tiles → the matching sheet (meal / weight / mood / medication / journal / note) → saved offline-safe, toast confirms.
4. **Plan the week (Act).** **Plan** → Schedule → add session / habit / planned meal on a real day cell (no "Open" placeholders); conflicts flagged; programme phase visible.
5. **Review a metric historically (Review).** Any surface → metric → **detail view** (`/insights/metric/{kind}` or drawer) → 7/30/90 toggle → value vs baseline vs typical band, source, freshness, calculation, caveat, related metrics.
6. **Weekly review (Review→Improve).** **Insights** → 7/30 + compare-to-previous → adherence, PRs, trends, one report → labelled measured/calculated/association/hypothesis.
7. **Trust/repair data (System).** **Today** sync chip → **Data sources** → see freshness, re-import, confirm what's stale.

## 7. Responsive layout rules

Explicit behaviour at the brief's breakpoints (replaces "rotated dock").

**Mobile < 768px**
- Bottom nav (5 stages), centre **Log** raised.
- Single column, 16px gutters.
- Sticky quick-log affordance within thumb reach.
- Charts simplified but still real (not decorative sparklines); detail opens as full-screen sheets/pages.
- Deep content = pages or sheets, not side rails.

**Tablet 768–1199px**
- Collapsible left nav (icon-rail ↔ labelled).
- 1–2 column workspace depending on content.
- Right rail collapses into a drawer.
- Larger charts where space allows.

**Desktop ≥ 1200px**
- Persistent grouped sidebar (220–240px) + flexible central **workspace** + contextual **right rail** (300–340px): recommendation, alerts, recent changes, sync.
- Multi-column composition using sections/dividers/tables/timelines/charts — **not** a uniform 3-column card grid.
- Hover states, visible focus, keyboard nav, comparison views, analytical tables, detail **drawers** (not full-page nav) for context.
- Today example: top summary band (Recovery / Sleep / Training load / Mood / adherence) → central timeline + schedule + next workout + goals → right rail (one recommendation + alerts + changes + sync).

**Cross-cutting (all sizes)**
- Two themes: neutral light **and** dark foundation; semantic domain colours (sleep indigo, recovery teal, running cyan/blue, strength orange, cardio coral, mind violet, nutrition green, meds amber, neutral slate) used consistently for category/series/selection/primary-action — muted for tints/icons/secondary.
- WCAG AA contrast; non-colour status indicators; colour-blind-safe chart palette (ties into the existing `dataviz` conventions).
- Every important component specified for populated / partial / empty / loading / error / stale / disconnected / low-confidence / offline states; empty states stay compact (reuse `empty_state`).

---

## Stage 2 → Stage 3 handoff

The three competing directions in Stage 3 must differ in **structure**, not colour, and each must show Today + Training on mobile and desktop:
- **Calm editorial control** — generous type, few surfaces, one recommendation forward, restraint.
- **High-density analytical workspace** — tables/small-multiples, comparison-first, desktop-led.
- **Timeline-led adaptive planner** — the day/week timeline is the spine; state and actions hang off it.

Open decisions to confirm before Stage 3 (see the summary): (a) evolve Jinja + tokens vs port to React/Tailwind; (b) build order for the three new modules (Habits, Goals, Medication); (c) confirm the Health/Recovery split.
