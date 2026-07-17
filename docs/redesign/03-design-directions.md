# Orion Redesign — Stage 3: Competing Design Directions

_Three directions that differ in **structure**, not just colour. Each is described for mobile + desktop Today and Training. A recommendation follows. Implementation stack is confirmed as **Next.js + TypeScript + Tailwind** (per Stage 2 handoff decision)._

All three share the Stage 5 foundation (neutral surface + semantic domain colours, light/dark, one type system) — so the choice is about **information structure and interaction model**, exactly as the brief requires.

---

## Direction A — Calm editorial control

**Thesis:** the interface is a quiet daily briefing. One decision forward at a time; depth is always one tap away, never on the surface. Optimises for "how am I / what should I do next."

**Today — mobile**
```
Wed 17 July · morning              ⟳ synced 8m
────────────────────────────────────────────
Recovery 72   Sleep 6h19   Move 41%   Mood 7
  teal ▲        indigo ▼      cyan       violet
────────────────────────────────────────────
RECOMMENDED
Reduce today's interval volume
Resting HR is well above your range.
Do 4 reps, not 6; reassess after warm-up.
  [ Apply ]  [ View evidence ]  [ Dismiss ]
────────────────────────────────────────────
Today
 07:00 ✓ Vitamin D + omega-3
 08:30   Zone-2 run · 40 min  (adjusted)
 13:00   Lunch
 21:30   Wind-down target
────────────────────────────────────────────
Changed   RHR +7 vs baseline · Sleep debt 1h6
```
Generous whitespace, large readable type, at most one hero (the recommendation). Status strip is a thin 4-metric row, not four cards.

**Today — desktop**: two columns. Left (2/3): recommendation → timeline → next workout. Right rail (1/3): what changed, alerts, sync. Summary band of 5 metrics sits above both. No card grid — sections separated by rules and spacing.

**Training — mobile**: "Next session" leads (structured warm-up / reps / recovery / cooldown). Below: two calm rows — running (week bar vs target) and strength (dots for planned sessions). History as a lean expandable list.

**Training — desktop**: left workspace = programme phase + week strip with real session content + next session detail; right rail = load/recovery constraint + PRs. Charts are medium line/bar, not sparklines.

**Colour/type**: warm neutral paper (light) / soft charcoal (dark); domain colour used only for the metric it belongs to + the one active recommendation. Large display type for the single number that matters; everything else calm and secondary.

**Strengths**: directly answers the brief's five questions; feels premium and trustworthy; kills density-anxiety; easiest to keep de-duplicated (only one thing is "loud" per screen).
**Weaknesses**: power users doing serious analysis may find the surface too sparse; risks under-using desktop width if not disciplined about the right rail.
**Suitability for Orion**: very high for Today/Mind/Recovery; needs Insights to carry the heavier analysis so the calm surface stays calm.

---

## Direction B — High-density analytical workspace

**Thesis:** a serious instrument. Small multiples, tables, comparison-first. Optimises for "what changed / am I improving."

**Today — mobile**
```
Today  Wed 17 Jul                    ⟳ 8m
Recovery Sleep  RHR  HRV  Load  Mood
  72 ▲   6h19  101  61   680   7
  ┌sparkline row of 6, tap → detail─────┐
RECOMMENDATION  medium confidence
 ↓ Interval volume 6→4 · RHR 101 vs 59
   evidence ▸
7-DAY  vs prev    Δ
 Sleep   6.4h  6.9h  −0.5
 RHR      64    60   +4
 HRV      58    62   −4
 Load    720   540  +180
Timeline ▸   Due: 2 habits, 1 med
```
Denser type, tabular numbers (mono), delta columns everywhere, compact sparkline rows that open full charts.

**Today — desktop**: three-region workspace — left nav, centre grid of small-multiple metric tiles with baseline bands + delta, right rail with recommendation + alerts. A comparison table (this period vs previous) is a first-class element. This is the direction that most uses horizontal space.

**Training — mobile**: metrics-first — weekly volume, load (ACWR-style), pace trend, e1RM movers — each a compact tile; the session plan is a dense list.

**Training — desktop**: analytical board — running volume weekly bars + rolling average, pace line with run-type filter, strength volume/e1RM trends, consistency heatmap, PR table. The week schedule is a compact calendar, not big boxes.

**Colour/type**: neutral slate foundation; domain colour reserved for chart series + selected state; heavy use of tabular/mono figures; tight vertical rhythm.

**Strengths**: best for the "am I improving" job; makes desktop genuinely valuable; satisfies "charts communicate comparisons, not decoration"; scales to a lot of data.
**Weaknesses**: risks feeling intimidating/"dashboard" if applied to Today; higher cognitive load; harder to keep calm on mobile.
**Suitability for Orion**: ideal for **Insights**, **Health**, **Training analytics**; wrong tone for Today/Mind.

---

## Direction C — Timeline-led adaptive planner

**Thesis:** the day/week timeline is the spine of the product; state and actions hang off time. Optimises for "am I following my plans / what's next."

**Today — mobile**
```
Wed 17 July                          ⟳ 8m
State: Recovery 72 · steady          ▸ detail
── now 09:12 ───────────────────────────────
 ● 08:30  Zone-2 run · 40m   ADJUSTED ▸why
   ↳ RHR high — 4 reps not 6   [Apply][×]
 ○ 13:00  Lunch            log ▸
 ○ 18:00  Push session (planned)
 ○ 21:30  Wind-down target
────────────────────────────────────────────
 Due now   2 habits · Vitamin D
 [ + Log ]  quick: run · meal · mood · set
```
The whole screen is a vertical timeline with a "now" line; recommendations attach to the relevant event; logging happens inline against the timeline.

**Today — desktop**: left nav; centre = the day timeline with inline events, adjustments, and logging; right rail = state summary + what changed + next-24h. A mini week-strip sits atop the timeline.

**Training — mobile**: the **week** is the primary object — a horizontal day strip; tapping a day expands its sessions with real structure; completed vs planned shown inline; "next session" is just the next node on the timeline.

**Training — desktop**: full week planner (real session cards on a grid), programme phase as a band across the top, drag-to-plan; load/recovery as a lane; history as a continuation of the same timeline.

**Colour/type**: domain colour encodes the *type* of each timeline node (run=cyan, strength=orange, meal=green, med=amber, mind=violet); time labels in mono; calm neutral background so nodes read clearly.

**Strengths**: uniquely answers "am I following my plans" and "what's next"; makes Plan and Today feel like one coherent product; logging-in-context is fast; naturally avoids duplicate metric cards (metrics live at the top, events fill the body).
**Weaknesses**: pure timeline can bury longitudinal analysis (needs Insights to compensate); empty early-morning timelines need careful handling; less conventional, slightly higher learning curve.
**Suitability for Orion**: excellent for **Today + Plan + Log** as a unit; less natural for Health/Recovery analysis.

---

## Recommendation — a justified combination, A-led

No single direction serves all of the brief's five questions. The right answer is a **combination with a dominant grammar**, assigned per screen by the job that screen owns (Stage 2 §4):

- **Foundation & tone: Direction A (Calm editorial control).** It is the product's default voice — premium, calm, trustworthy — and it is the safest guarantee against the current app's density/repetition problems. Today, Recovery, Mind, and every "decide" moment use A.
- **Today's body: A with a C spine.** Lead with A's status strip + single recommendation + evidence, but render the day as **C's timeline** (with inline adjust/log). This is the strongest possible answer to "how am I / what's next / am I following my plans" in one view, and it makes logging fast.
- **Plan: Direction C.** The weekly timeline/planner is C's home turf and fixes the "seven Open boxes" defect directly.
- **Insights, Health analytics, Training analytics: Direction B.** The heavy comparison/small-multiple work lives here and only here — which keeps A calm elsewhere and satisfies "charts communicate comparisons."
- **Log: C's inline-capture model** surfaced as A-clean sheets.

**Why this combination and not one pure direction:** the brief explicitly warns against both "a generic AI dashboard" (the risk of pure B everywhere) and "a mobile layout stretched across desktop / motivational chatbot" (the risk of pure A being too thin). Assigning grammar by job — calm by default, timeline where planning/time matters, density only where analysis matters — is what makes the product feel *intentional* rather than uniform. It also maps cleanly onto the data-ownership rule: metrics are calm references on operational screens (A/C) and full instruments only on their authoritative analytical screen (B).

**Concrete build implication:** the Stage 5 design system must express all three grammars from one token set — the same colours/type/spacing, arranged as (A) generous sections, (C) timeline nodes, or (B) dense tiles/tables. The component library is built once; each screen composes it in its assigned grammar.

_Proceeding to Stage 5 (design system) and Stage 4/6 (build the recommended combination for real)._
