# Orion Redesign — Stage 5: Design system

_Implemented in `frontend/` (Next.js + TypeScript + Tailwind v4). This documents the tokens and reusable primitives; the source is the authority._

## Tokens (`app/globals.css`)

One neutral foundation + restrained semantic domain colours, theme-aware via `[data-theme]` with an OS-preference fallback. Tailwind v4 `@theme inline` maps each CSS variable to a utility (`bg-surface`, `text-muted`, `text-recovery`, …).

**Neutral foundation** (light / dark): `--bg`, `--bg-sunken`, `--surface`, `--surface-2`, `--surface-inset`, `--border`, `--border-strong`, `--text`, `--text-2` (muted), `--text-3` (faint), `--overlay`, `--ring`.

**Status**: `--good`, `--warn`, `--crit`, `--info`.

**Semantic domains** (brief §11): `--sleep` indigo · `--recovery` teal · `--running` cyan/blue · `--strength` orange · `--cardio` coral · `--mind` violet · `--nutrition` green · `--meds` amber · `--neutral` slate. Each has a light and dark value tuned for AA contrast on its surface. Tints/borders derive at runtime via `color-mix(in oklab, var(--c) N%, …)`, so a single hue drives fill, tint, and border consistently.

**Colour discipline** (matches the brief): strong colour only for selected states, important changes, chart series, category recognition, and primary actions; muted colour for background tints, icons, secondary labels, chart areas. No arbitrary gradients; no per-card colour.

**Type**: Geist Sans (interface) + Geist Mono (reserved for values, timestamps, source lines, IDs). Scale via Tailwind; `.tnum` for tabular figures on all data.

**Elevation / shape**: `--shadow-sm/md/lg`, `--radius` (0.75rem base). Restrained radii and borders — no thick outlines, no oversized padding.

**Theme switching**: `components/theme.tsx` — a no-flash inline script resolves `data-theme` before first paint; the `ThemeToggle` (light / dark / system) persists to `localStorage`.

## Reusable primitives

| Component | File | Role |
|---|---|---|
| `Card`, `SectionHeader`, `Button`, `Chip`, `Meta` | `components/ui.tsx` | Surfaces, headings, actions (clear interactive hierarchy), metadata |
| `DomainDot`, `DeltaBadge`, `TrendGlyph`, `QualityBadge`, `ConfidenceBadge` | `components/ui.tsx` | Category + change + data-quality/confidence indicators (non-colour-only) |
| `TrendChart` | `components/charts.tsx` | The one chart — line/bar, typical-range band, baseline, rolling avg, hover readout |
| `Sparkline`, `Ring`, `CalendarHeatmap` | `components/charts.tsx` | Inline trend, score ring, consistency heatmap |
| `StatusStrip`, `MetricStat` | `components/patterns.tsx` | Compact status band; metric tile → detail |
| `TimelineList`, `ChangeList`, `InsightList` | `components/patterns.tsx` | Day timeline; meaningful changes; classified findings |
| `EmptyState` | `components/patterns.tsx` | Compact, instructional (never dominates) |
| `RecommendationCard` | `components/interactive.tsx` | Single recommendation → reveal evidence / apply / dismiss |
| `MetricDetailView` | `components/interactive.tsx` | Full metric authority — value, quality, 7/30/90, band, baselines, how/caveat, source, related |
| `AppShell`, `Page`, sidebar/bottom-nav/rail | `components/shell.tsx` | Responsive shell + page/rail layout |
| `ModulePlaceholder` | `components/module-placeholder.tsx` | Honest compact scaffold for specced-not-built destinations |

**Data quality & confidence are first-class**: `QualityBadge` (measured/calculated/estimated/missing) and `ConfidenceBadge` appear on recommendations, insights (classified measured/calculated/association/hypothesis/recommendation), and metric details — satisfying the brief's "distinguish facts from associations" requirement.

## Accessibility

WCAG-AA-tuned domain values on both themes; visible `:focus-visible` ring; `prefers-reduced-motion` disables animation; status shown by icon + text, not colour alone; charts carry `role="img"` + labels and hover readouts; targets ≥ 32px.
