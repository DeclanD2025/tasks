"use client";

import { ChevronRight, Info } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { DOMAIN_LABEL, domainStyle } from "@/lib/domains";
import type { MetricDetail, Recommendation } from "@/lib/types";
import { TrendChart } from "./charts";
import { Button, ConfidenceBadge, Meta, QualityBadge } from "./ui";

/* ------------------------------------------------------ Recommendation */
/**
 * Today's single call.
 *
 * Apply / Dismiss are deliberately absent: acting on a recommendation has to
 * persist somewhere, and ORION has no write endpoint for it yet. A button that
 * only changes local state would report an adjustment that never happened.
 */
export function RecommendationCard({ rec }: { rec: Recommendation }) {
  const [showEvidence, setShowEvidence] = useState(false);

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-surface shadow-[var(--shadow-sm)]" style={domainStyle(rec.domain)}>
      <div className="domain-bar h-1 w-full" />
      <div className="p-4 sm:p-5">
        <div className="flex items-center gap-2">
          <span className="text-[11px] font-semibold uppercase tracking-wide domain-text">Recommended</span>
          <span className="text-faint">·</span>
          <ConfidenceBadge confidence={rec.confidence} />
        </div>
        <h3 className="mt-1.5 text-lg font-semibold tracking-tight text-text">{rec.title}</h3>
        <p className="mt-1 text-[14px] leading-relaxed text-muted">{rec.body}</p>

        {rec.evidence.length > 0 && (
          <div className="mt-3.5 flex flex-wrap items-center gap-2">
            <Button variant="ghost" size="sm" onClick={() => setShowEvidence((v) => !v)} aria-expanded={showEvidence}>
              <Info className="size-4" /> {showEvidence ? "Hide evidence" : "View evidence"}
            </Button>
          </div>
        )}

        {showEvidence && (
          <div className="mt-4 rounded-lg border border-border bg-surface-2 p-3 rise">
            <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">Supporting evidence</p>
            <dl className="grid grid-cols-2 gap-x-4 gap-y-2 sm:grid-cols-3">
              {rec.evidence.map((e) => (
                <div key={e.label} className="flex flex-col">
                  <dt className="text-[11px] text-faint">{e.label}</dt>
                  <dd className={cn("tnum text-[13px] font-medium", e.tone === "good" ? "text-good" : e.tone === "watch" ? "text-warn" : "text-text")}>{e.value}</dd>
                </div>
              ))}
            </dl>
            <Link href="/recovery" className="mt-2.5 inline-flex items-center gap-1 text-[12px] font-medium domain-text">
              How readiness is scored <ChevronRight className="size-3.5" />
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}

/* --------------------------------------------------- MetricDetailView */
const RANGES = [
  { key: 7, label: "7d" },
  { key: 30, label: "30d" },
  { key: 90, label: "90d" },
] as const;

export function MetricDetailView({ metric, compact = false }: { metric: MetricDetail; compact?: boolean }) {
  const [days, setDays] = useState<number>(30);
  const [compare, setCompare] = useState(false);
  const series = metric.series.slice(-days);
  const empty = series.length === 0;

  return (
    <div style={domainStyle(metric.domain)}>
      {/* header */}
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-semibold uppercase tracking-wide domain-text">{DOMAIN_LABEL[metric.domain]}</span>
            <QualityBadge quality={metric.quality} />
          </div>
          <div className="mt-1 flex items-baseline gap-1.5">
            <span className="tnum text-3xl font-semibold text-text">{metric.displayValue}</span>
            {metric.unit && <span className="text-[15px] text-faint">{metric.unit}</span>}
          </div>
          <p className="mt-1 max-w-md text-[13px] text-muted">{metric.interpretation}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
            {RANGES.map((r) => (
              <button
                key={r.key}
                onClick={() => setDays(r.key)}
                aria-pressed={days === r.key}
                className={cn("rounded-md px-2.5 py-1 text-[12px] font-medium transition-colors", days === r.key ? "bg-surface text-text shadow-[var(--shadow-sm)]" : "text-faint hover:text-muted")}
              >
                {r.label}
              </button>
            ))}
          </div>
          <label className="flex items-center gap-1.5 text-[11px] text-muted">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="accent-[var(--c)]" />
            Compare previous
          </label>
        </div>
      </div>

      {/* chart */}
      <div className="mt-3">
        {empty ? (
          <div className="grid h-40 place-items-center rounded-lg border border-dashed border-border bg-surface-2/50 text-center">
            <div>
              <p className="text-[13px] font-medium text-text">No history yet</p>
              <p className="mt-0.5 text-[12px] text-muted">Import a Health Auto Export file and this lights up.</p>
            </div>
          </div>
        ) : (
          <TrendChart
            series={series}
            domain={metric.domain}
            variant={metric.kind === "run_distance" || metric.kind === "steps" ? "bar" : "line"}
            band={metric.band}
            baseline={metric.baseline30}
            rolling={days >= 30 ? 7 : undefined}
            unit={metric.unit}
            decimals={metric.decimals}
            lowerBetter={metric.lowerBetter}
            height={compact ? 160 : 200}
          />
        )}
      </div>

      {/* baselines / band */}
      <div className="mt-3 grid grid-cols-3 gap-2">
        <Stat label="7-day baseline" value={metric.baseline7 != null ? `${metric.baseline7}${metric.unit ? " " + metric.unit : ""}` : "—"} />
        <Stat label="30-day baseline" value={metric.baseline30 != null ? `${metric.baseline30}${metric.unit ? " " + metric.unit : ""}` : "—"} />
        <Stat label="Typical range" value={metric.band ? `${metric.band[0]}–${metric.band[1]}` : "—"} />
      </div>

      {/* facts */}
      {metric.facts.length > 0 && (
        <dl className="mt-3 space-y-1.5 rounded-lg border border-border bg-surface-2 p-3">
          {metric.facts.map((f) => (
            <div key={f.label} className="flex items-baseline justify-between gap-3">
              <dt className="text-[12px] text-muted">{f.label}</dt>
              <dd className="text-right">
                <span className="tnum text-[13px] font-medium text-text">{f.value}</span>
                {f.detail && <span className="block text-[11px] text-faint">{f.detail}</span>}
              </dd>
            </div>
          ))}
        </dl>
      )}

      {/* transparency */}
      <div className="mt-3 space-y-2 text-[12.5px] leading-relaxed">
        <Line label="What it means">{metric.meaning}</Line>
        <Line label="How it's calculated">{metric.how}</Line>
        {metric.caveat && <Line label="Caveat" tone="warn">{metric.caveat}</Line>}
      </div>

      {/* footer: source + related */}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-border pt-3">
        <Meta>Source: {metric.source} · {metric.freshness}</Meta>
        {metric.related.length > 0 && !compact && (
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-[11px] text-faint">Related:</span>
            {metric.related.map((rel) => (
              <Link key={rel.kind} href={`/insights/metric/${rel.kind}`} className="rounded-full border border-border bg-surface px-2 py-0.5 text-[11px] font-medium text-muted hover:text-text">
                {rel.title}
              </Link>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface p-2.5">
      <div className="text-[11px] text-faint">{label}</div>
      <div className="tnum mt-0.5 text-[14px] font-semibold text-text">{value}</div>
    </div>
  );
}

function Line({ label, children, tone }: { label: string; children: React.ReactNode; tone?: "warn" }) {
  return (
    <p className={cn(tone === "warn" ? "text-warn" : "text-muted")}>
      <span className="font-medium text-text">{label}. </span>
      {children}
    </p>
  );
}
