# Homepage — implementation

Companion to `01-audit.md`, which explains *why* the design is shaped this way.
Read that first: most decisions here follow from three facts about the real
data rather than from taste.

---

## Data flow

```
GET /api/v2/brief
  └─ briefing.brief.generate(uid)
       ├─ briefing.quality.assess(uid)        freshness from records
       ├─ personal_os.get_recovery_snapshot   health state
       ├─ services.get_tasks(uid)             the backlog
       ├─ briefing.priorities.select()        top 3, explained
       ├─ briefing.review.review_buckets()    triage categories
       ├─ _state_summary / _focus / _next_action
       ├─ _select_insight                     at most one
       └─ _persist + _log_generated           archive + provenance
```

One composed response. The homepage does no reconciliation — deciding which
insight to show, whether task counts can be trusted, and what the next action
is *is* the judgement, and it belongs where it can be tested.

**The brief is generated once per day-part and reused.** Regenerating per load
would change the next action under the operator mid-glance, and would destroy
the record of what was actually suggested.

---

## Ranking logic

`briefing/priorities.py`, rule version **1**.

Designed around the awkward fact that **the priority field is useless** — 273
of 288 open tasks are `medium`. Signal is derived from everywhere else.

| Component | Points | Notes |
| --- | --- | --- |
| `pinned` | 1000 | Bypasses scoring entirely. Manual always wins. |
| `due_today` | +40 | |
| `overdue` | +12 … +30 | `12 + √days × 4`, **capped at 21 days** |
| `due_soon` | +22 … 0 | Decays over 7 days |
| `undated` | +2 | Two thirds of the backlog; must not be invisible |
| `priority_high` | +12 | Only 12 tasks; meaningful *when present* |
| `priority_low` | −6 | |
| `has_next_action` | +8 | A task without a first step is a wish |
| `blocked` | −30 | |
| `impact` | ±10 / −4 | |
| `project_load` | +6 | ≥10 open items in the same project |
| `fits` / `too_long` | +6 / −8 | Against the daypart's usable minutes |
| `energy_fit` / mismatch | +4 / −6 | Against recovery score |
| `age` | 0 … **+8** | Hard cap |
| `deferred_before` | −5 per defer, max −20 | |

**Why the caps.** Uncapped overdue and age both mean the oldest task wins
forever — and a task is usually old because it deserves to be, not because it
is urgent.

**Selection spreads across projects.** Three items from one deadline wave is
one priority wearing three hats. If diversity leaves slots empty (a backlog
dominated by one project will), they are filled on score alone rather than
showing fewer than asked for.

**Exclusions** are returned with a reason rather than silently dropped:
archived, deferred-until-future, or flagged `stale` / `convert_to_habit`.

---

## Baseline logic

Reused from `health/metric_details.py` rather than rebuilt. It already
provides 7- and 30-day baselines, plausibility gating (unworn-device days do
not poison a baseline), coverage reporting ("3 of 7 days"), quality flags and
provenance. See `docs/redesign/` for its history.

The brief adds only the decision layer: **if health data is not `live`, no
claim about recovery is made at all.** A summary that describes a state from
numbers three days old is worse than a summary that says nothing.

---

## Data quality

`briefing/quality.py`. The single most important rule:

> **Freshness is derived from the newest record in each domain, never from
> `DataSource.status`.**

In production that field flags both calendar connectors `mock` while they hold
81 real events with genuine EventKit identifiers, and reports `tasks_sync` as
`connected` with a last-sync 22 days old. A source is fresh if it recently
produced data — the only definition that cannot be wrong.

| Domain | Limit | Derived from |
| --- | --- | --- |
| health | 2 days | `max(health_metrics_daily.day)` |
| tasks | 3 days | `max(tasks.synced_at)` |
| calendar | 14 days | `max(calendar_events.synced_at)` |
| training | 10 days | `max(workouts.started_at, strength_workouts.started_at)` |

`trust` is `live` / `stale` / `empty`. Empty and stale are kept apart: no data
and old data are different problems with different fixes.

Warnings render **only when something is wrong**. A permanent row of green
ticks is plumbing, and plumbing does not belong on the first screen.

---

## Planned vs completed, and the review reframing

`briefing/review.py` sorts the open backlog into buckets the operator can act
on, and produces the headline that replaces the overdue counter:

> "38 of 63 items past their date belong to Steelmen Dispatch Issue 4 — one
> project's schedule slipped, rather than everything at once."

Buckets: `overdue`, `needs_date`, `habit_candidates`, `stale`, `blocked`.

**`habit_candidates` is an inference, and only ever a suggestion.** Titles
matching a conservative pattern (journal, Duolingo, stretch, read…) that carry
a one-off due date are surfaced as *possible* habits. Nothing is converted
automatically — a wrong guess acting alone would delete a real task.

---

## Persistence and analytics

`daily_briefs` — one row per day, kept permanently, with `rule_version` so the
archive stays comparable across changes to the scoring logic.

`brief_events` — what was suggested and what happened: `priority_generated`,
`priority_accepted`, `priority_deferred`, `priority_pinned`, `task_completed`,
`insight_viewed`, `evidence_opened`, `brief_edited`.

Together they make these answerable over time: which suggestions get accepted,
which get replaced, what is deferred repeatedly, which dayparts produce
completions, how often ORION is overridden.

`brief.effectiveness()` reports **counts, not rates**, below 30 generated
priorities — one user over a short window cannot support a percentage.

---

## Accessibility

- Semantic landmarks: `header`, `section` with `aria-labelledby`, `footer`.
- Every disclosure control carries `aria-expanded`.
- Decorative icons are `aria-hidden`; nothing is conveyed by colour alone —
  every state has a word beside it.
- Score components use `+`/`−` signs as well as weight, so the sign is not
  carried by colour.
- Buttons use verbs: "Done", "Not today", "Pin", "Why this?".

---

## Performance

- One request for the homepage.
- `quality.assess` is four aggregate queries — no row loading, no N+1.
- The brief is persisted; a same-daypart reload reads one row.
- Priority scoring is O(open tasks) over an already-loaded list.
- No historical recomputation on the request path.

---

## Known limitations

1. **`_select_insight` draws only from recovery changes.** Richer sources
   (training, nutrition) exist but are not yet wired in; the slot is
   deliberately single so adding more means *choosing* between them.
2. **Estimated durations are unvalidated** — nothing yet compares
   `estimate_minutes` against actual completion time, so "how accurate are
   estimates?" is not answerable until estimates are being entered.
3. **`priority_accepted` is inferred from `task_completed`,** not recorded
   separately. Distinguishing "did it because ORION said so" from "did it
   anyway" needs an explicit accept action.
4. **No project table.** Projects are inferred from the `area` prefix, so
   renaming an area silently re-groups history.
5. **Timeline has no travel time** — the calendar carries locations but no
   routing, and inventing durations would make the day look planned when it is
   not.
6. **Task writes are local-only.** `complete_task` sets `dirty=1` for the
   Supabase pusher rather than writing upstream directly; until that sync runs,
   the companion app will not agree.

---

## Adding a new insight type

1. Compute it in a domain service that can refuse — return nothing when the
   data cannot support it.
2. Append a candidate in `brief._select_insight` with `body`, `confidence` and
   an `evidence` dict whose keys are values, not prose.
3. Decide its rank against existing candidates. The homepage shows **one**;
   adding a type means choosing when it beats what is already there.
4. Bump `RULE_VERSION` in `briefing/priorities.py` if selection behaviour
   changes, so the archive stays interpretable.
