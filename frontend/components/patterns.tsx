import { ChevronRight } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { type DomainKey, DOMAIN_LABEL, domainStyle } from "@/lib/domains";
import type { Change, Insight, MetricDetail, StatusMetric, TimelineEntry } from "@/lib/types";
import { Sparkline } from "./charts";
import { DeltaBadge, DomainDot, Meta } from "./ui";

/* ------------------------------------------------------------ EmptyState */
export function EmptyState({
  title,
  body,
  cta,
  href,
  compact = true,
}: {
  title: string;
  body?: string;
  cta?: string;
  href?: string;
  compact?: boolean;
}) {
  return (
    <div className={cn("flex items-center gap-3 rounded-lg border border-dashed border-border bg-surface-2/50", compact ? "px-3 py-2.5" : "flex-col px-4 py-6 text-center")}>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] font-medium text-text">{title}</p>
        {body && <p className="mt-0.5 text-[12px] text-muted">{body}</p>}
      </div>
      {cta && href && (
        <Link href={href} className="shrink-0 rounded-md border border-border bg-surface px-2.5 py-1 text-[12px] font-medium text-text hover:bg-surface-2">
          {cta}
        </Link>
      )}
    </div>
  );
}

/* ------------------------------------------------------------ StatusStrip */
export function StatusStrip({ items }: { items: StatusMetric[] }) {
  return (
    <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
      {items.map((m) => (
        <Link
          key={m.kind}
          href={`/insights/metric/${m.kind}`}
          style={domainStyle(m.domain)}
          className="group rounded-lg border border-border bg-surface p-3 transition-colors hover:border-border-strong"
        >
          <div className="flex items-center gap-1.5">
            <DomainDot domain={m.domain} />
            <span className="text-[12px] font-medium text-muted">{m.label}</span>
          </div>
          <div className="mt-1 flex items-baseline gap-0.5">
            <span className="tnum text-2xl font-semibold text-text">{m.value}</span>
            {m.unit && <span className="text-[13px] text-faint">{m.unit}</span>}
          </div>
          <DeltaBadge tone={m.tone} trend={m.trend}>
            {m.deltaText}
          </DeltaBadge>
        </Link>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------- MetricStat */
export function MetricStat({ metric, showSpark = true }: { metric: MetricDetail; showSpark?: boolean }) {
  const tone = metric.trend === "flat" ? "flat" : (metric.trend === "up") === metric.lowerBetter ? "watch" : "good";
  const delta =
    metric.baseline7 != null && metric.latest != null
      ? `${metric.latest - metric.baseline7 >= 0 ? "+" : ""}${(metric.latest - metric.baseline7).toFixed(metric.decimals)} vs 7-day`
      : "baseline pending";
  return (
    <Link
      href={`/insights/metric/${metric.kind}`}
      style={domainStyle(metric.domain)}
      className="group flex flex-col rounded-lg border border-border bg-surface p-3 transition-colors hover:border-border-strong"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-1.5">
          <DomainDot domain={metric.domain} />
          <span className="text-[12px] font-medium text-muted">{metric.title}</span>
        </div>
        <ChevronRight className="size-3.5 text-faint transition-transform group-hover:translate-x-0.5" />
      </div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className="tnum text-xl font-semibold text-text">{metric.displayValue}</span>
        {metric.unit && <span className="text-[12px] text-faint">{metric.unit}</span>}
      </div>
      <DeltaBadge tone={tone as "good" | "watch" | "flat"} trend={metric.trend}>
        {delta}
      </DeltaBadge>
      {showSpark && metric.series.length > 1 && <Sparkline series={metric.series} domain={metric.domain} className="mt-2 h-6" />}
    </Link>
  );
}

/* ------------------------------------------------------------- Timeline */
const statusMeta: Record<TimelineEntry["status"], { ring: string; label?: string }> = {
  done: { ring: "bg-good" },
  now: { ring: "bg-info" },
  upcoming: { ring: "bg-surface border-2 border-border-strong" },
  target: { ring: "bg-surface border-2 border-dashed border-border-strong" },
};

export function TimelineList({ entries, nowTime }: { entries: TimelineEntry[]; nowTime?: string }) {
  return (
    <ol className="relative ml-1">
      <span aria-hidden className="absolute left-[5px] top-1 bottom-1 w-px bg-border" />
      {entries.map((e) => {
        const past = e.status === "done";
        return (
          <li key={e.id} className="relative flex gap-3 pb-4 last:pb-0" style={domainStyle(e.domain)}>
            <span className={cn("relative z-10 mt-1 size-[11px] shrink-0 rounded-full", statusMeta[e.status].ring)} style={e.status === "done" ? { background: `var(--${e.domain})` } : undefined} />
            <div className="-mt-0.5 min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <Meta>{e.time}</Meta>
                {e.adjusted && (
                  <span className="rounded-full bg-warn/15 px-1.5 py-px text-[10px] font-semibold text-warn">Adjusted</span>
                )}
                {e.status === "target" && <span className="text-[10px] font-medium text-faint">target</span>}
              </div>
              <p className={cn("text-[14px] font-medium", past ? "text-muted" : "text-text")}>{e.title}</p>
              {e.detail && <p className="text-[12px] text-muted">{e.detail}</p>}
            </div>
            {e.loggable && (
              <Link href={`/log?for=${e.id}`} className="mt-0.5 shrink-0 self-start rounded-md border border-border px-2 py-0.5 text-[11px] font-medium text-muted hover:text-text hover:bg-surface-2">
                Log
              </Link>
            )}
          </li>
        );
      })}
    </ol>
  );
}

/* --------------------------------------------------------- ChangeList */
export function ChangeList({ changes }: { changes: Change[] }) {
  return (
    <ul className="space-y-2">
      {changes.map((c, i) => (
        <li key={i} className="flex items-start gap-2.5" style={domainStyle(c.domain)}>
          <DomainDot domain={c.domain} className="mt-1.5" />
          <p className="text-[13px] text-text">
            <span className="font-medium">{c.metric}</span>{" "}
            <span className={cn(c.tone === "good" ? "text-good" : c.tone === "watch" ? "text-warn" : "text-muted")}>{c.text}</span>
          </p>
        </li>
      ))}
    </ul>
  );
}

/* --------------------------------------------------------- InsightList */
const klassLabel = {
  measured: "Measured fact",
  calculated: "Calculated",
  association: "Association",
  hypothesis: "Hypothesis",
  recommendation: "Recommendation",
} as const;
const klassTone = {
  measured: "text-good border-good/30 bg-good/10",
  calculated: "text-info border-info/30 bg-info/10",
  association: "text-warn border-warn/30 bg-warn/10",
  hypothesis: "text-mind border-mind/30 bg-mind/10",
  recommendation: "text-text border-border bg-surface-2",
} as const;

export function InsightList({ insights }: { insights: Insight[] }) {
  return (
    <div className="space-y-2.5">
      {insights.map((ins) => (
        <div key={ins.id} className="rounded-lg border border-border bg-surface p-3" style={domainStyle(ins.domain)}>
          <div className="mb-1.5 flex items-center gap-2">
            <span className={cn("rounded-full border px-2 py-0.5 text-[10px] font-semibold", klassTone[ins.klass])}>{klassLabel[ins.klass]}</span>
            <span className="text-[11px] text-faint">{DOMAIN_LABEL[ins.domain]} · {ins.confidence} confidence</span>
          </div>
          <p className="text-[14px] font-medium text-text">{ins.title}</p>
          <p className="mt-0.5 text-[13px] text-muted">{ins.body}</p>
        </div>
      ))}
    </div>
  );
}

/* ------------------------------------------------------- domain heading */
export function DomainHeading({ domain, children }: { domain: DomainKey; children: ReactNode }) {
  return (
    <div className="flex items-center gap-2" style={domainStyle(domain)}>
      <DomainDot domain={domain} />
      <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">{children}</span>
    </div>
  );
}
