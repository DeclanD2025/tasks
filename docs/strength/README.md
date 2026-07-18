# Strength training system

Technical documentation for the strength planning, logging and analytics system
in `app/domains/strength/`.

The system's purpose is not "record exercises". It is to build a longitudinal
dataset that still supports honest analysis in five years — which means the
expensive decisions are all about what gets preserved, not what gets displayed.

---

## 1. Starting state (July 2026)

Worth knowing before reading anything else, because it shaped the design:

| Fact | Consequence |
| --- | --- |
| 83 seeded exercises, 9 templates | Extend the catalogue, don't rebuild it |
| **0** logged workouts, sets or PRs | The session/set tables carried no user data, so they could be reshaped properly |
| **142** "Traditional Strength Training" sessions in `workouts` from Apple Health (Jul 2025 → Jul 2026, ~6–7/month) | Declan already trains. What was missing was *detail*, not adherence — so the UI surfaces those sessions rather than showing an empty dashboard beside them |
| Live `sleep_minutes`, `hrv_ms`, `resting_hr`, `weight_kg` | Readiness integration is real, not aspirational |

---

## 2. Module map

| Module | Responsibility | DB? |
| --- | --- | --- |
| `calc.py` | Pure maths: volume, e1RM, units, muscle weighting, plates | No |
| `catalog.py` | Exercise library: families, variants, classification | Yes |
| `records.py` | Personal-record detection and invalidation | Yes |
| `progression.py` | Transparent rules engine (pure core + event log) | Partly |
| `sessions.py` | Session lifecycle: start, log, correct, finish, resume | Yes |
| `programmes.py` | Programmes, templates, scheduling, training home | Yes |
| `reporting.py` | Longitudinal aggregates | Yes |
| `export.py` | CSV/JSON out, import back in | Yes |
| `tracker.py` | The original quick-logging module behind the Jinja UI | Yes |

**Naming note.** `reporting.py` is the analytics module. It is not called
`analytics.py` because `tracker.analytics()` already owns that name at package
level and would shadow the submodule. Do not "fix" this.

`tracker` is re-exported from `__init__` so `from app.domains import strength`
keeps working for the legacy Jinja routes. **The dependency runs one way**:
nothing in the new modules imports from `tracker`, so the legacy UI can be
retired without unpicking the analytics.

---

## 3. Data model

### The three rules

1. **Plans are copied into sessions, not referenced by them.** A session stores
   the prescription it was performed against (`StrengthWorkoutExercise
   .prescription`). Editing a template next month cannot rewrite what last
   month's session was asked to do — otherwise adherence is unanswerable.
2. **Nothing performed is ever deleted.** Corrections set `voided_at` and keep
   the original in `edit_history`. A set that never existed and a set entered
   wrongly are different facts.
3. **Kilograms are canonical.** Display units are a preference. Storing
   whatever unit was being typed makes every longitudinal query a
   unit-archaeology exercise.

### Tables

**Extended:** `strength_exercises`, `strength_workout_templates`,
`strength_template_exercises`, `strength_workouts`,
`strength_workout_exercises`, `strength_set_entries`,
`strength_personal_records`.

**New:** `strength_programmes`, `strength_programme_blocks`,
`strength_programme_days`, `strength_programme_items`,
`strength_planned_sessions`, `strength_progression_events`.

### Migrations

`create_all()` builds new tables but **cannot widen existing ones**. Every
column added to a pre-existing strength table is listed in
`_STRENGTH_COLUMNS` in `app/db/database.py`, and every index the ORM declares
on an existing table is in `_STRENGTH_INDEXES` — `create_all` skips an existing
table entirely, so those indexes would otherwise never be built on a deployed
database.

Verified against a copy of the production database: **88 statements applied,
idempotent on re-run, all 261 workouts / 83 exercises / 165 health rows
intact.**

SQLite constraints worth knowing: `ALTER TABLE ADD COLUMN` cannot add a UNIQUE
column, so `client_key`'s uniqueness is a partial index applied afterwards.

### Four levels of grouping

```
exercise      barbell bench press        loads directly comparable
family        bench-press                variants of one movement
movement      horizontal_push            pull-ups and pulldowns meet here
muscle        Chest                      volume aggregates here
```

Judgement calls: incline pressing is a **separate family** from flat (the angle
changes the movement); pull-ups and lat pulldowns are **separate families**
(bodyweight vs external load) that meet at the movement level; leg press is
**not** in the squat family.

---

## 4. Calculations

### Volume

`load × reps`, working sets only. Warm-ups and technique sets are excluded from
every volume, hard-set and intensity figure. Duration- and distance-based sets
return **0 tonnage** — a 60-second plank has no meaningful volume and inventing
one pollutes every total it lands in.

Four load types genuinely differ:

| Type | Effective load |
| --- | --- |
| `external` | the weight on the bar |
| `bodyweight` | `bodyweight × factor` (default 0.65) |
| `weighted_bodyweight` | `bodyweight + added` |
| `assisted` | `bodyweight − assistance`, floored at 0 |

Assistance is subtracted so that **needing less help reads as progress**, not as
falling volume.

Unilateral sets logged per side sum both limbs: 8 reps per arm at 20 kg is
320 kg, not 160.

### Hard sets

A working set at **RPE ≥ 7**, **RIR ≤ 3**, or taken to failure.

An unrated working set is **not** assumed hard. Counting unrated sets would make
the metric track rating diligence rather than training, and it would silently
inflate the moment the operator stopped entering RPE.

### Estimated 1RM

Epley (default), Brzycki, Lombardi. Stored with the formula that produced it —
two estimates from different formulas are not comparable.

Two guards:

- **Reps > 12 → refused.** The formulas were fitted on low-rep sets. A 25-rep
  set says a great deal about endurance and almost nothing about a 1RM. The
  previous implementation capped reps at 30 and estimated anyway.
- **Reps == 1 → measured, not estimated.** Every formula should collapse to the
  lifted weight at one rep. Epley does not (it returns 1.033×), and reporting a
  measured single as 3% heavier than it was is how a fake PR is created.

`estimate_1rm` returns an `E1RM` object with a `valid` flag and a reason, not a
bare float, so a caller has to actively ignore an invalid estimate to misuse it.

### Muscle attribution

Primary 1.0 set, secondary 0.5. **This is a convention for comparability, not a
physiological measurement**, it is configurable, and the UI says so wherever
indirect volume appears. Direct and indirect are reported separately rather than
summed. A muscle listed as both primary and secondary counts once.

---

## 5. Personal records

**Records are rebuilt from history, never incrementally patched.**

Incremental detection is the obvious design and it is wrong. Once a set can be
corrected or voided, incremental records go stale invisibly: the mistyped 200 kg
bench stays as an all-time PR forever, or it is deleted and the record it
displaced never returns. `rebuild_records_for_exercise` replays the full set
history and is correct by construction whatever order edits arrived in.

Tracked types: `heaviest_weight`, `most_reps_at_weight`, `best_e1rm`,
`best_set_volume`, `best_session_volume`, `best_at_rep_target` (1/3/5/8/10),
`longest_duration`.

**First-ever performances are recorded but not announced.** Every exercise's
first session sets eight simultaneous "records"; celebrating that teaches the
operator to ignore the feature. `previous_value != null` is the announceable
test.

Records are kept rather than overwritten, so the progression of a lift is itself
a readable series. `is_active` marks the standing one. `invalidated_at` is
different and deliberate — it disowns a record whose set was a typo, and those
must never resurface as something later work "beat".

---

## 6. Progression rules engine

**A rules engine, not intelligence.** Every proposal states its rule, inputs and
reason in plain words. Nothing is ever applied automatically.

Implemented: `fixed_load`, `double_progression`, `rep_range`, `percentage`,
`rpe_target`, `rir_target`, `top_set_backoff`, `amrap_triggered`, `manual`,
`deload`.

Worked example — double progression at 3×6–8:

- All three working sets reach 8 reps at or below target RPE → **+increment**,
  restart at 6.
- Reps met but RPE blown → **hold**. 8 reps at RPE 10 is not the same event as 8
  at RPE 8, and treating them alike is how a lifter ends up grinding.
- Target RPE set but no RPE recorded → **hold**, saying the cap could not be
  checked. Reps alone do not justify an increase against an RPE cap.
- Minimum reps missed twice consecutively → **reduce to 90%**.
- One miss → **hold**. One bad session is a bad session, not a trend.

`Proposal.conclusive` distinguishes "I have nothing to go on" from "hold", which
is a real decision.

**Rejections are stored, not just acceptances.** A rule the operator overrides
every week is a rule that does not fit them, and that is only visible if the
misses are kept.

---

## 7. Readiness integration

`readiness_snapshot` is copied onto the session **at start time**, not joined at
read time. Apple Health revises sleep and HRV for a day afterwards, so a live
join would quietly rewrite the conditions a session was performed under — and
any correlation drawn from them. The snapshot records the reading *and its age*,
because a 3-day-old HRV is a weaker claim than this morning's.

Bodyweight is likewise copied per set. A lifter who gains 5 kg over a year must
not have last year's push-up volume silently restated upward.

### Associations, not causes

`readiness_associations` requires **8 paired observations** minimum. Below that
it returns an explicit refusal with the count, not a coefficient. Every reported
row carries its sample size, date range, missing-data rate, and the sentence:

> An association in your own log, not evidence that one causes the other.
> Training, sleep and stress all move together.

A personal training log will not produce causal evidence. Presenting a
coefficient over six sessions as insight would be the most dishonest thing in
the system.

### Plateau detection

Requires **4 comparable exposures**. Two unchanged sessions is a fortnight, not
a plateau, and calling it one trains the operator to ignore the signal.
`confident: false` is returned with the reason when there is too little history.

---

## 8. Planned vs completed

Kept strictly apart. `StrengthPlannedSession` is the intention;
`StrengthWorkout` is what was started.

| Status | Meaning |
| --- | --- |
| `completed` | every prescribed exercise saw work |
| `partial` | some exercises were never trained |
| `abandoned` | started, no sets logged |
| `skipped` | planned, never started |
| `rescheduled` | moved; `rescheduled_from` retains the original date |

Unplanned sessions are counted but **excluded from the completion rate** —
training that was never scheduled cannot be adherence to a schedule. When
nothing was scheduled, `rateAvailable: false` and a sentence explaining why,
rather than a flattering made-up percentage.

Reschedules keep their original date: repeatedly pushing Friday to Saturday is a
pattern worth seeing, and it vanishes if a reschedule looks identical to having
planned Saturday all along.

---

## 9. Classification snapshots

`StrengthWorkoutExercise.classification_snapshot` freezes the exercise's muscle
and movement tagging as it stood that day.

Reclassifying an exercise later (deciding RDLs are hinge-primary rather than
hamstring-primary) would otherwise silently restate years of muscle-group
volume. **Both readings stay available**:
`reporting._load_sets(use_snapshot_classification=True)` gives "what I believed
at the time"; `False` re-reads today's classification. Silently picking one
would be the mistake, which is why it is a parameter.

---

## 10. Offline and failure handling

The gym-floor failure mode that matters is not "the request was slow" — it is
"the set I logged is gone and I have moved on".

- **Server-side session state.** Refresh, crash, accidental navigation and
  killed tabs all recover through `GET /session/active`.
- **Idempotent set creation.** Every write carries a device-minted `clientKey`
  with a partial unique index behind it. A retry returns the original set.
- **localStorage outbox.** Sets are queued before sending, applied to the screen
  immediately, and drained on mount, on `online`, and on a 15s backstop timer.
  Failures stay queued with a rising attempt count — nothing is dropped.
- **Honest sync state.** Unacknowledged sets render with a spinner. Optimistic
  UI that cannot admit it hasn't saved is how silent data loss happens.
- **Flush before finish.** The outbox is drained before completing a session, or
  the summary would be computed without sets the user already logged.

---

## 11. Export and import

`GET /api/v2/strength/export.json` — full backup.
`GET /api/v2/strength/export.csv?table=sets|sessions|exercises|records|programmes`

The set CSV carries the **raw inputs and the derived figures**. Raw so any
future analysis can start from scratch; derived so a spreadsheet user does not
have to reimplement bodyweight-load resolution to total a column.

The JSON backup includes a `conventions` block — units, what counts as a working
set, the hard-set definition, e1RM formula and rep limit, muscle weighting. A
volume figure is meaningless without knowing warm-ups were excluded.

Empty exports still emit headers: a file with columns and no rows is
unambiguous, an empty file could be a failure.

Import is duplicate-safe on `import_id`. Re-running an import creates nothing —
the standard way fitness-app migrations silently double every historical total.
Unknown exercises are **skipped and reported**, never invented to make the
numbers land.

---

## 12. Privacy

Every endpoint is behind the session cookie, including reads
(`test_reads_require_a_session` covers all 11). Writes are refused **before**
validation, so an anonymous caller cannot learn body shapes from error
messages. Ownership is re-checked in the service layer on every call rather than
trusted from the route. Export is always an explicit user action — nothing runs
on a schedule or pushes anywhere.

---

## 13. Testing

| File | Tests | Covers |
| --- | --- | --- |
| `test_strength_calc.py` | 43 | volume, e1RM, units, weighting, plates, edge cases |
| `test_strength_sessions.py` | 33 | lifecycle, idempotency, corrections, records |
| `test_strength_progression.py` | 26 | every rule, plus inconclusive paths |
| `test_strength_reporting.py` | 21 | aggregates, plateaus, adherence, associations |
| `test_api_v2_strength.py` | 50 | full workflow, auth boundary, export |

Edge cases covered: zero-weight, assisted, bodyweight, unilateral, very high
reps, missing RPE, partial workouts, duplicate imports, changed units, voided
and corrected sets, offline recovery, and timezone-naive/aware comparison.

---

## 14. Known limitations and compromises

Recorded honestly rather than hidden:

1. **Template exercises are unique per template.** The pre-existing
   `uq_strength_template_exercise` constraint means an exercise appears at most
   once per template, ruling out squatting at the start and again as a back-off.
   Dropping it needs a SQLite table rebuild. Programme days have no such limit
   and are the richer planning surface.

2. **Template versioning is nominal.** `version` increments but old versions are
   not retained. This is safe because history-safety comes from the prescription
   snapshot on the session, not from freezing the template — but "show me
   template v2" is not answerable.

3. **The programme builder is API-complete, UI-partial.** Programmes,
   blocks, days and items are fully modelled and exposed over HTTP; the
   *drag-and-drop builder screen* is not built. Programmes can be created and
   read from the UI, not visually composed.

4. **Six exercises classify as `other`** (lateral raises, face pull, shrug,
   cleans). The brief's movement vocabulary has no abduction or shrug category.
   They are excluded from push/pull balance rather than forced into a bucket.

5. **Bodyweight factors are published estimates, not measurements.** 0.64 for a
   push-up is a literature figure, not something ORION observed. Labelled as
   such everywhere it surfaces.

6. **Indirect-set weighting (0.5) is a convention.** It is configurable and
   never presented as physiological fact.

7. **No exercise-level 1RM testing protocol.** `percentage` progression needs an
   `oneRmKg` in config; nothing yet computes a maintained training max.

8. **Apple Health strength sessions are surfaced, not merged.** The 142 imported
   sessions are reported with a note explaining they carry no exercise detail.
   `StrengthWorkout.workout_id` exists to link a logged session to its Apple
   Health record, but auto-matching by time window is not implemented.

9. **Session RPE is the only internal-load measure.** Foster sRPE × duration.
   Nothing yet reconciles it with the Edwards TRIMP used for running.

---

## 15. Extending

**A new measurement type** (e.g. speed-based): add to `MEASUREMENT_KINDS`, give
`SetInput` its field, decide its contribution in `set_volume_kg` (return 0.0
unless it genuinely produces tonnage), add a column to `strength_set_entries`
*and* to `_STRENGTH_COLUMNS`.

**A new progression rule**: write a pure function in `progression.py` returning a
`Proposal`, register it in `propose()`, add it to `PROGRESSION_RULES`. Test it
against literal sets — including the case where it cannot conclude.

**A new analytic**: it goes in `reporting.py`, not in a React component. If it
cannot be computed honestly on thin data, return the reason rather than a
number.
