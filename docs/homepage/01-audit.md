# Homepage rebuild — Phase 1 audit

Written 2026-07-18 against the live production database (`orion-decdundas`,
Fly volume `/data/orion.db`), not against seed or local data.

The headline: **most of what makes the current homepage feel wrong is not a
design problem.** It is the page faithfully rendering data that is stale,
mis-flagged, or carrying almost no signal. Redesigning the surface without
fixing that would produce a calmer page telling the same untruths.

---

## 1. What the data actually says

### Tasks

| Figure | Value |
| --- | --- |
| Open tasks | **288** |
| Overdue | **95** |
| Due today | **0** |
| Undated | **193** |
| Recurring | 3 |
| Completed ever | 84 (79 in June, 5 in July) |
| Oldest overdue | **2026-06-29** — three weeks, not years |

Four findings that reshape the design:

**a. The 95 are one project, not 95 unrelated failures.**

| Area | Overdue |
| --- | --- |
| Steelmen Dispatch Issue 4 / Production deadlines | 38 |
| Steelmen Dispatch | 37 |
| Steelmen Dispatch Issue 4 / Marketing | 15 |
| Personal | 5 |

90 of 95 belong to one publication's deadline wave. "95 tasks past due" is a
sentence that describes a person who is failing at everything. "One issue's
production schedule slipped" describes what actually happened. The homepage
should say the second thing.

**b. Priority carries almost no information.** 273 of 288 open tasks are
`medium`; 12 are `high`, 3 are `low`. Any ranking that leans on the priority
field is effectively ranking at random. Scoring must derive signal from
elsewhere — deadline proximity, project concentration, age, whether a next
action exists.

**c. Some "overdue tasks" are rotted habits.** `Morning journal`, `Evening
journal`, `Duolingo`, all dated 2026-06-29. These are daily behaviours that
were given a one-off due date and then decayed into permanent guilt. They
belong in habits (which ORION now has), not in a task backlog. The review area
should be able to say so.

**d. Nothing has been completed in 14 days**, and the last real burst was June.
Any "recent progress" section built on task completions would be empty or
misleading. Progress has to come from data that is actually being generated —
training, health, writing.

### Data sources — the registry is unreliable

| Source | Status | Last synced |
| --- | --- | --- |
| `health_auto_export` | connected | **2026-07-18 20:04** (live) |
| `tasks_sync` | connected | 2026-06-26 (**22 days stale**) |
| `open_banking` (Starling) | connected | 2026-07-03 (frozen — Keychain, known) |
| `apple_calendar` | **mock** | 2026-06-26 |
| `google_calendar` | **mock** | 2026-06-26 |
| `activitywatch`, `notion`, `coinbase`, `moneybox`, `trading212`, `football_manager`, `apple_health` | mock | various |

Two problems, in opposite directions:

- **The calendar sources are flagged `mock` but hold real data.** 81 events, 21
  from today forward, with genuine EventKit and Google identifiers, across
  Declan's real calendars (Ashurst, Motherwell fixtures, Home, Fitness). The
  flag is simply wrong.
- **`tasks_sync` claims `connected` but last synced 22 days ago** — while five
  July completions exist, so the timestamp is not trustworthy either.

**Therefore: `DataSource.status` cannot be trusted as the basis for a
data-quality layer.** Freshness must be derived from the newest *record* in
each domain, not from the connector's self-report. This is the single most
important finding for the "never present sample data as real" requirement.

### Signals that are empty

`habits` 0 · `goals` 0 · `mental_checkins` 0 · `food_logs` 0

The homepage must work with these absent. Any section depending on them needs a
real empty state, not a zero.

### Health — live and revising

`health_auto_export` synced at 20:04 today. Worth noting: **HRV for 18 July
changed from 64.1 to 58.5 between two reads hours apart.** Apple Health revises
history. Any baseline or recommendation must record the value it used at the
time rather than re-reading later — otherwise yesterday's advice silently
acquires today's numbers as its justification.

---

## 2. What exists and will be reused

| Concern | Where | Verdict |
| --- | --- | --- |
| Homepage route | `frontend/app/page.tsx` | Rebuild in place |
| Payload builder | `ui_models.today()` | Reuse; becomes one composed brief |
| Design system | `components/ui.tsx`, `patterns.tsx`, tokens in `globals.css` | Reuse — extend, never re-skin ([[design rule]]) |
| Data fetching | `lib/api.ts` `useApi` | Reuse |
| Snapshots | `personal_os.get_today_snapshot / get_recovery_snapshot` | Reuse |
| Metric baselines | `health/metric_details.py` — has plausibility gating + coverage | **Reuse and extend**, do not rewrite |
| Insight classification | `ui_models.insights()` with evidence classes | Reuse |
| Task read model | `services.get_tasks()` | Extend with review fields |
| Strength records/analytics | `domains/strength/*` | Reuse for progress section |
| Auth | session cookie, `web.context.user_id()` | Reuse unchanged |

`metric_details.py` already does most of what the brief asks of the baseline
service: 7- and 30-day baselines, plausibility gating, coverage reporting
("3 of 7 days"), quality flags and provenance. Rewriting it would lose that.

## 3. What needs to be added

1. **`DailyBrief`** — persisted snapshot per day: daypart, state summary, focus,
   next action, chosen priorities, chosen insight, confidence, data-quality
   warnings, rule version, generated-at, manual edits, and per-item user
   response.
2. **Task review fields** — `reviewed_at`, `review_status`, `defer_until`,
   `blocked`, `waiting_for`, `next_action`, `estimate_minutes`, `energy`,
   `impact`, `pinned`, `archived_reason`.
3. **`BriefEvent`** — provenance log: priority generated / accepted / replaced /
   deferred / completed, recommendation viewed / acted / dismissed.
4. **Priority scoring service** — transparent, component-wise, explainable.
5. **Data-quality service** — freshness derived from records, not from
   `DataSource.status`.
6. **Task-review service** — the categories that replace "95 overdue".

## 4. What gets deprecated

- The sync-sources card in prime homepage space (`syncSources` stays in the
  payload for Settings; it leaves the homepage).
- Raw overdue count as the emotional centre.
- `_lede()`'s current shape — it states facts but cannot reason about them, and
  it will be superseded by the brief's state summary.
- Presenting `DataSource.status` directly anywhere a user could read it as
  truth.

## 5. Data-quality limitations to design around

1. **Task data is 22 days stale.** Any count shown must carry that caveat, or
   the page asserts a backlog that may already be cleared.
2. **Priority is 95% one value** — unusable as a ranking input.
3. **No completion telemetry for 14 days** — "recent progress" cannot lean on
   tasks.
4. **Calendar sources are mis-flagged** — trust the records, not the registry.
5. **Health data is revised after the fact** — snapshot what you used.
6. **habits / goals / checkins / food are empty** — every dependent section
   needs a genuine empty state.
7. **Starling is frozen at 2026-07-03** and cannot sync from Fly (macOS
   Keychain). Money must be absent or explicitly stale, never implied current.

## 6. Assumption register

- Recurring personal admin ("Morning journal", "Duolingo") is treated as a
  *review candidate for conversion to a habit*, not as a genuine overdue task.
  This is an inference from title and cadence; the review screen proposes it
  rather than acting on it.
- "Steelmen Dispatch Issue 4" is treated as one project for grouping purposes,
  inferred from the `area` prefix. There is no project table.
- Daypart boundaries: morning < 12:00, afternoon < 17:00, evening < 22:00,
  else night. Local device time.
