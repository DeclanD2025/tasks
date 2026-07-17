# Orion Redesign — Stage 6: Implementation

_The redesign is built as a new front end at `frontend/` (Next.js 16 App Router, React 19, TypeScript, Tailwind v4). It renders the recommended Stage 3 combination for real, against a typed data layer that mirrors the backend's read-model contracts (audit §3)._

## What's built (verified: `next build` clean, 34 routes prerendered, runs on `:8322`)

| Screen | Route | Depth |
|---|---|---|
| **Today** | `/` | Full — status band, single recommendation (reveal evidence / apply / dismiss), timeline spine, next action, right rail (changes / due / sync) |
| **Training** | `/training` | Full — programme phase, structured next session, real week schedule (no "Open" boxes), running + strength consistency, load chart, PR rail |
| **Recovery** | `/recovery` | Full — readiness ring + factor breakdown, primary signals, sleep debt, trend chart |
| **Health** | `/health` | Full — VO₂ max feature chart + body-metric grid, split from Recovery |
| **Metric detail** | `/insights/metric/[kind]` | Full — 13 metrics; value/quality/7-30-90/band/baselines/how/caveat/source/related |
| **Log** | `/log` | Full — quick-capture hub (favourites first), fast strength-set logger (steppers, ≤ few taps), quick forms |
| **Plan** | `/plan` | Full — week schedule with load bands + add affordance, habits + goals summaries, milestones/conflicts |
| **Habits / Goals** | `/plan/habits`, `/plan/goals` | Full — new modules the brief requires |
| **Insights** | `/insights` | Full — range control, per-metric small-multiples with compare-to-previous, classified findings, PRs, data quality |
| **Reports** | `/insights/reports` | Representative weekly report |
| Nutrition, Mind, Medication, Money, Tasks, Data sources, Integrations, Settings | resp. routes | Honest compact scaffolds (`ModulePlaceholder`) documenting ownership, source, and state; Settings carries the theme control |

## Architecture

- **Responsive shell** (`components/shell.tsx`): desktop grouped collapsible sidebar (Daily / Plan & record / Understand / System) + workspace + `xl` right rail; mobile bottom nav (Today / Plan / **Log+** / Insights / More) with emphasised Log and a More sheet. One IA, two views (Stage 2 §2–3).
- **Data layer** (`lib/`): `types.ts` mirrors the snapshot contracts; `data.ts` provides realistic, internally consistent values (an elevated-RHR morning driving the day's recommendation — no lorem ipsum); `series.ts` uses a deterministic PRNG so SSR and client hydration match. This is a drop-in seam: replace the `lib/data.ts` exports with `fetch()` calls to the existing FastAPI JSON (`/api/today`, `/api/detail/{kind}`, …) to go live.
- **Charts** (`components/charts.tsx`): one internal chart engine — no heavy dependency — carrying the old `orion-charts.js` ideas (per-domain colour, typical-range band, baseline, hover crosshair) forward.

## Run it

```bash
cd frontend
pnpm install          # native builds pre-approved in pnpm-workspace.yaml
pnpm dev              # http://localhost:3000
# or: pnpm build && pnpm start
```

## Wiring to the real backend (next increment)

1. Point `lib/data.ts` functions at the FastAPI JSON endpoints (the read models already match the TS types).
2. Port Nutrition, Mind, Money, Tasks, Data Vault UIs (backends already complete — audit §7).
3. Build the net-new modules' backends: Medication/supplements, Habits, Goals (audit §8).
4. Carry over the offline write-queue + service worker for the Log flow (already proven in the current app).

## Acceptance criteria (brief §20) — status

Met and verified in-browser: status understood in <5s · next action visible without scrolling · desktop uses horizontal space (sidebar + workspace + rail) · no page is all-identical cards · no metric shown twice without contextual justification (data-ownership map enforced) · every recommendation reveals evidence · every metric has a historical view · empty states compact · multiple semantic colours without noise · Log reachable in one tap, strength set in few taps · Today/Training/Health/Recovery have distinct purposes · charts show comparisons · data freshness + confidence visible · **works in light and dark** · feels intentional on desktop · does not read as a generic AI dashboard.
