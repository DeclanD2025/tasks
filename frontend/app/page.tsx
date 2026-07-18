"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { RecommendationCard } from "@/components/interactive";
import { Loaded } from "@/components/loading";
import { ChangeList, EmptyState, TimelineList } from "@/components/patterns";
import { Card, DomainDot, Meta, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/cn";
import { domainStyle } from "@/lib/domains";
import type { TodayPayload } from "@/lib/payloads";
import type { StatusMetric } from "@/lib/types";

const syncTone = {
  ok: "text-good",
  stale: "text-warn",
  error: "text-warn",
  disconnected: "text-faint",
  mock: "text-info",
} as const;

function daypart(hour: number): string {
  if (hour < 5) return "night";
  if (hour < 12) return "morning";
  if (hour < 17) return "afternoon";
  if (hour < 22) return "evening";
  return "night";
}

/** What the commitments block is called depends on how much day is left.
 *  In the morning it frames the day ahead; by evening it is what is still
 *  outstanding, which is a different question. */
function demandsHeading(part: string): { title: string; sub: string } {
  if (part === "morning") return { title: "On you today", sub: "What the day is asking for" };
  if (part === "afternoon") return { title: "Still on you", sub: "What is left of the day" };
  return { title: "Left undone", sub: "What did not get closed today" };
}

export default function TodayPage() {
  // One request: the backend bundles the next run and the sync list into
  // /today because rebuilding those read models separately is expensive.
  const state = useApi<TodayPayload>("/today");
  return <Loaded state={state}>{(data) => <Today data={data} />}</Loaded>;
}

function Today({ data }: { data: TodayPayload }) {
  const now = new Date();
  const part = daypart(now.getHours());
  const dateLine = now.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const { nextRun, lede, tasks } = data;
  const heading = demandsHeading(part);

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      {/* ---------------------------------------------------------- Lede.
          The page's one bold move: today's read, stated rather than
          assembled by the reader from four numbers. Everything below it is
          deliberately quieter. */}
      <header className="mb-6 max-w-[62ch]">
        <p className="font-mono text-[11px] uppercase tracking-[0.08em] text-faint">
          {dateLine} · {part}
          {data.freshness && <> · {data.freshness.toLowerCase()}</>}
        </p>
        <p className="mt-2.5 text-balance text-[21px] font-semibold leading-[1.35] tracking-tight text-text lg:text-[26px]">
          {lede.state || `Good ${part === "night" ? "evening" : part}${data.user.name ? `, ${data.user.name}` : ""}.`}
          {lede.demand && <span className="text-muted"> {lede.demand}</span>}
        </p>
        {lede.nudge && (
          <p className="mt-1.5 text-[13.5px] text-muted">{lede.nudge}</p>
        )}
      </header>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_var(--rail-w)] xl:items-start">
        <div className="min-w-0 space-y-5">
          {data.recommendation ? (
            <RecommendationCard rec={data.recommendation} />
          ) : (
            <Card className="p-4 sm:p-5">
              <EmptyState
                title="No call for today"
                body="ORION makes one recommendation when recovery and training data give it enough to go on."
                cta="Import data"
                href="/data"
              />
            </Card>
          )}

          {/* Demoted from four hero tiles to one compact band: the numbers are
              context for the lede, not the headline. */}
          {data.statusStrip.length > 0 && <MetricBand items={data.statusStrip} />}

          {/* What is actually owed. The backlog count was the single largest
              fact about the day and appeared nowhere on this page. */}
          {(tasks.overdue > 0 || tasks.dueToday > 0) && (
            <Card className="p-4 sm:p-5">
              <SectionHeader
                title={heading.title}
                sub={heading.sub}
                action={
                  <Link href="/tasks" className="text-[12px] font-medium text-muted hover:text-text">
                    All tasks →
                  </Link>
                }
              />
              <div className="mb-3 flex flex-wrap items-baseline gap-x-5 gap-y-1">
                {tasks.dueToday > 0 && (
                  <Count value={tasks.dueToday} label="due today" tone="text-text" />
                )}
                {tasks.overdue > 0 && (
                  <Count value={tasks.overdue} label="past due" tone="text-warn" />
                )}
                <Count value={tasks.open} label="open" tone="text-faint" />
              </div>
              <ul className="space-y-1.5 border-t border-border pt-3">
                {tasks.soonest.map((t) => (
                  <li key={t.id} className="flex items-baseline justify-between gap-3 text-[13.5px]">
                    <span className="min-w-0 truncate text-text">{t.title}</span>
                    <Meta className={cn("shrink-0", t.overdue && "text-warn")}>{t.dueLabel}</Meta>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card className="p-4 sm:p-5">
            <SectionHeader
              title="Today"
              sub="Scheduled and completed, in order"
              action={<Link href="/plan" className="text-[12px] font-medium text-muted hover:text-text">Week →</Link>}
            />
            {data.timeline.length ? (
              <TimelineList entries={data.timeline} />
            ) : (
              <EmptyState title="Nothing scheduled" body="Connect a calendar, or plan the week from the Plan tab." cta="Plan" href="/plan" />
            )}
          </Card>

          {nextRun && (
            <Card className="p-4 sm:p-5">
              <div className="flex items-start justify-between gap-4" style={domainStyle("running")}>
                <div className="min-w-0">
                  <div className="mb-1 flex items-center gap-1.5">
                    <DomainDot domain="running" />
                    <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">
                      Next run · {nextRun.dayLabel}
                    </span>
                  </div>
                  <h3 className="text-[15px] font-semibold text-text">{nextRun.title}</h3>
                  <p className="mt-0.5 text-[13px] text-muted">{nextRun.detail}</p>
                  <Meta className="mt-1 block">
                    {nextRun.distanceKm.toFixed(1)} km · {nextRun.phase}
                  </Meta>
                </div>
                <Link href="/training" className="shrink-0 rounded-lg px-3 py-2 text-[13px] font-medium text-white" style={{ background: "var(--running)" }}>
                  Open
                </Link>
              </div>
            </Card>
          )}
        </div>

        {/* Right rail */}
        <aside className="space-y-4">
          <Card className="p-4">
            <SectionHeader title="What changed" sub="Against your 7-day baseline" />
            {data.changes.length ? (
              <ChangeList changes={data.changes} />
            ) : (
              <EmptyState title="No drift" body="Nothing has moved off its baseline." />
            )}
            <Link href="/insights" className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">
              All insights <ArrowRight className="size-3.5" />
            </Link>
          </Card>

          {data.sleepDebtLabel && (
            <Card className="p-4">
              <SectionHeader title="Sleep debt" />
              <p className="text-[15px] font-semibold text-text">{data.sleepDebtLabel}</p>
              <Link href="/insights/metric/sleep_debt" className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">
                How this is worked out <ArrowRight className="size-3.5" />
              </Link>
            </Card>
          )}

          <Card className="p-4">
            <SectionHeader title="Data sync" action={<Link href="/data" className="text-[12px] font-medium text-muted hover:text-text">Manage</Link>} />
            {data.syncSources.length ? (
              <ul className="space-y-1.5">
                {data.syncSources.map((s) => (
                  <li key={s.name} className="flex items-center justify-between gap-2 text-[12.5px]">
                    <span className="flex min-w-0 items-center gap-1.5 text-muted">
                      <span aria-hidden className={`size-1.5 shrink-0 rounded-full bg-current ${syncTone[s.status]}`} />
                      <span className="truncate">{s.name}</span>
                    </span>
                    <Meta>{s.status === "disconnected" ? "connect" : s.status === "mock" ? "sample" : s.freshness}</Meta>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="No sources" body="Nothing is connected yet." cta="Connect" href="/data" />
            )}
          </Card>
        </aside>
      </div>
    </div>
  );
}

/* ----------------------------------------------------------------- Count */
function Count({ value, label, tone }: { value: number; label: string; tone: string }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className={cn("tnum text-xl font-semibold", tone)}>{value}</span>
      <span className="text-[12.5px] text-muted">{label}</span>
    </span>
  );
}

/* ------------------------------------------------------------ MetricBand */
/** The four metrics as one quiet band rather than four competing tiles.
 *
 *  A stale reading is shown with its age and muted instead of being presented
 *  as current state — mood stopped arriving weeks ago and was still sitting in
 *  the hero row as if it were today's check-in.
 */
function MetricBand({ items }: { items: StatusMetric[] }) {
  return (
    <Card className="divide-y divide-border p-0 sm:grid sm:grid-cols-2 sm:divide-y-0 lg:grid-cols-4">
      {items.map((m, i) => (
        <Link
          key={m.kind}
          href={`/insights/metric/${m.kind}`}
          style={domainStyle(m.domain)}
          className={cn(
            "group flex items-center justify-between gap-3 p-3.5 transition-colors hover:bg-surface-2 sm:block",
            i > 0 && "sm:border-l sm:border-border",
          )}
        >
          <span className="flex items-center gap-1.5">
            <DomainDot domain={m.domain} />
            <span className="text-[12px] font-medium text-muted">{m.label}</span>
          </span>
          <span className="flex items-baseline gap-1 sm:mt-1.5">
            <span
              className={cn(
                "tnum text-[19px] font-semibold",
                m.stale ? "text-faint" : "text-text",
              )}
            >
              {m.value}
            </span>
            {m.unit && <span className="text-[12px] text-faint">{m.unit}</span>}
          </span>
          <Meta className="hidden sm:mt-0.5 sm:block">
            {m.stale ? `last read ${m.ageLabel}` : m.deltaText}
          </Meta>
        </Link>
      ))}
    </Card>
  );
}
