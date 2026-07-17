import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { Card, DomainDot, SectionHeader } from "@/components/ui";
import { type DomainKey, domainStyle } from "@/lib/domains";

const WEEKLY = [
  { domain: "running" as DomainKey, label: "Running", value: "24.6 km", delta: "+3.2 vs last week", tone: "good" },
  { domain: "strength" as DomainKey, label: "Strength", value: "2 sessions", delta: "−1 vs target", tone: "watch" },
  { domain: "sleep" as DomainKey, label: "Avg sleep", value: "6h 41m", delta: "−19m vs need", tone: "watch" },
  { domain: "recovery" as DomainKey, label: "Avg readiness", value: "74 / 100", delta: "−2 vs last week", tone: "watch" },
  { domain: "nutrition" as DomainKey, label: "Avg protein", value: "148 g", delta: "on target", tone: "good" },
  { domain: "mind" as DomainKey, label: "Avg mood", value: "7.0 / 10", delta: "steady", tone: "flat" },
];

export default function ReportsPage() {
  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-5 lg:px-6 lg:py-6">
      <Link href="/insights" className="mb-4 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text">
        <ChevronLeft className="size-4" /> Insights
      </Link>
      <div className="mb-4 flex items-end justify-between">
        <div>
          <p className="text-[13px] font-medium text-muted">Review · week of 13–19 July</p>
          <h1 className="text-2xl font-semibold tracking-tight text-text">Weekly report</h1>
        </div>
        <div className="inline-flex rounded-lg border border-border bg-surface-2 p-0.5 text-[12px]">
          <span className="rounded-md bg-surface px-3 py-1 font-medium text-text shadow-[var(--shadow-sm)]">Weekly</span>
          <span className="px-3 py-1 text-faint">Monthly</span>
        </div>
      </div>

      <Card className="mb-4 p-4 sm:p-5">
        <SectionHeader title="Summary" />
        <p className="text-[14px] leading-relaxed text-text">
          A solid aerobic week — mileage up 15% with a new VO₂ max high — offset by a short strength week and a
          resting-HR spike on Friday. Sleep drifted under need and debt grew. Hold intensity capped until resting HR
          normalises, and protect bedtime to clear the shortfall.
        </p>
      </Card>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {WEEKLY.map((r) => (
          <Card key={r.label} className="p-3.5" style={domainStyle(r.domain)}>
            <div className="flex items-center gap-1.5">
              <DomainDot domain={r.domain} />
              <span className="text-[12px] font-medium text-muted">{r.label}</span>
            </div>
            <div className="tnum mt-1 text-lg font-semibold text-text">{r.value}</div>
            <div className={`text-[12px] font-medium ${r.tone === "good" ? "text-good" : r.tone === "watch" ? "text-warn" : "text-faint"}`}>{r.delta}</div>
          </Card>
        ))}
      </div>
    </div>
  );
}
