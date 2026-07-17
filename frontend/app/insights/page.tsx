"use client";

import { Trophy } from "lucide-react";
import Link from "next/link";
import { useState } from "react";
import { TrendChart } from "@/components/charts";
import { InsightList } from "@/components/patterns";
import { cn } from "@/lib/cn";
import { domainStyle } from "@/lib/domains";
import { getMetric, INSIGHTS, STRENGTH, SYNC_SOURCES } from "@/lib/data";
import { mean } from "@/lib/series";

const BOARD = ["readiness", "sleep", "hrv", "resting_hr", "run_distance", "training_load", "weight", "mood"];
const RANGES = [7, 30, 90] as const;

const qualityByKind: Record<string, string> = { readiness: "Calculated", training_load: "Calculated" };

export default function InsightsPage() {
  const [days, setDays] = useState<number>(30);
  const [compare, setCompare] = useState(true);

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-[13px] font-medium text-muted">Review · are you improving?</p>
          <h1 className="text-2xl font-semibold tracking-tight text-text lg:text-[28px]">Insights</h1>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center gap-1.5 text-[12px] text-muted">
            <input type="checkbox" checked={compare} onChange={(e) => setCompare(e.target.checked)} className="accent-[var(--info)]" />
            vs previous
          </label>
          <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5">
            {RANGES.map((r) => (
              <button key={r} onClick={() => setDays(r)} aria-pressed={days === r} className={cn("rounded-md px-3 py-1 text-[12px] font-medium", days === r ? "bg-surface text-text shadow-[var(--shadow-sm)]" : "text-faint hover:text-muted")}>
                {r}d
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Small multiples */}
      <div className="mb-3 flex items-center gap-3 text-[11px] text-faint">
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-good" /> Measured</span>
        <span className="flex items-center gap-1"><span className="size-2 rounded-full bg-info" /> Calculated</span>
        <span>· all figures vs your own baseline</span>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {BOARD.map((kind) => {
          const m = getMetric(kind);
          if (!m) return null;
          const cur = m.series.slice(-days);
          const prev = m.series.slice(-2 * days, -days);
          const cm = mean(cur.map((p) => p.value));
          const pm = prev.length ? mean(prev.map((p) => p.value)) : cm;
          const diff = cm - pm;
          const good = (diff > 0) !== m.lowerBetter;
          const sig = Math.abs(diff) > (Math.abs(pm) * 0.02 || 0.1);
          return (
            <Link key={kind} href={`/insights/metric/${kind}`} style={domainStyle(m.domain)} className="rounded-xl border border-border bg-surface p-3 transition-colors hover:border-border-strong">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-muted">{m.title}</span>
                <span className={`size-2 rounded-full ${qualityByKind[kind] ? "bg-info" : "bg-good"}`} title={qualityByKind[kind] ?? "Measured"} />
              </div>
              <div className="mt-0.5 flex items-baseline gap-1">
                <span className="tnum text-lg font-semibold text-text">{cm.toFixed(m.decimals)}</span>
                {m.unit && <span className="text-[11px] text-faint">{m.unit}</span>}
                {compare && (
                  <span className={cn("tnum ml-auto text-[12px] font-medium", !sig ? "text-faint" : good ? "text-good" : "text-warn")}>
                    {diff >= 0 ? "+" : ""}{diff.toFixed(m.decimals)}
                  </span>
                )}
              </div>
              <TrendChart series={cur} domain={m.domain} baseline={compare ? pm : null} unit={m.unit} decimals={m.decimals} height={92} variant={kind === "run_distance" ? "bar" : "line"} />
            </Link>
          );
        })}
      </div>

      <div className="mt-6 grid gap-5 lg:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)]">
        {/* Classified findings */}
        <section>
          <h2 className="mb-2 text-[15px] font-semibold tracking-tight text-text">Findings</h2>
          <p className="mb-3 text-[12.5px] text-muted">Each finding is labelled by how much to trust it — a measured fact, a calculation, an association in your own data, a hypothesis, or a recommendation.</p>
          <InsightList insights={INSIGHTS} />
        </section>

        <div className="space-y-5">
          <section>
            <h2 className="mb-2 text-[15px] font-semibold tracking-tight text-text">Personal records</h2>
            <div className="space-y-1.5">
              {STRENGTH.recentPRs.map((pr, i) => (
                <div key={i} className="flex items-center gap-2.5 rounded-lg border border-border bg-surface p-2.5" style={domainStyle(pr.domain)}>
                  <Trophy className="size-4 shrink-0 domain-text" />
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">{pr.label}</span>
                  <span className="tnum text-[13px] font-semibold text-text">{pr.value}</span>
                </div>
              ))}
            </div>
          </section>

          <section>
            <h2 className="mb-2 text-[15px] font-semibold tracking-tight text-text">Data quality</h2>
            <div className="rounded-lg border border-border bg-surface p-3">
              <ul className="space-y-1.5">
                {SYNC_SOURCES.map((s) => (
                  <li key={s.name} className="flex items-center justify-between text-[12.5px]">
                    <span className="text-muted">{s.name}</span>
                    <span className={cn("font-mono text-[11px]", s.status === "ok" ? "text-good" : s.status === "stale" ? "text-warn" : "text-faint")}>{s.status === "disconnected" ? "not connected" : s.freshness}</span>
                  </li>
                ))}
              </ul>
              <Link href="/insights/reports" className="mt-3 inline-block text-[12px] font-medium text-muted hover:text-text">Weekly & monthly reports →</Link>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
}
