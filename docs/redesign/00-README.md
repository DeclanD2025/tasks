# Orion redesign

A staged rebuild of the Orion web app, from audit to running implementation.

| Stage | Doc | Output |
|---|---|---|
| 1 — Audit | [`01-audit.md`](01-audit.md) | Screen/component/data inventory, duplication map, UX + responsive problems, retain/remove |
| 2 — Product structure | [`02-product-structure.md`](02-product-structure.md) | Loop-oriented sitemap, mobile/desktop nav, screen responsibilities, data-ownership map, journeys, responsive rules |
| 3 — Design directions | [`03-design-directions.md`](03-design-directions.md) | Three directions + recommended combination (A-led, C spine, B analytics) |
| 5 — Design system | [`05-design-system.md`](05-design-system.md) | Tokens (neutral + semantic domains, light/dark) + reusable primitives |
| 6 — Implementation | [`06-implementation.md`](06-implementation.md) | What's built, architecture, how to run, backend-wiring plan, acceptance status |

**Decisions taken** (Declan, 2026-07-17): implementation stack = **Next.js + TypeScript + Tailwind**; proceed through all stages.

**The build lives in [`../../frontend/`](../../frontend/).** `cd frontend && pnpm install && pnpm dev`.

Core finding: Orion's data layer is already clean (one producer per metric). The redesign is a presentation + IA rebuild, not a data re-architecture — which is why it's built as a new front end consuming the existing read-model contracts.
