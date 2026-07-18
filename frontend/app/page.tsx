"use client";

import { ArrowRight } from "lucide-react";
import Link from "next/link";
import { RecommendationCard } from "@/components/interactive";
import { Loaded } from "@/components/loading";
import { ChangeList, EmptyState, StatusStrip, TimelineList } from "@/components/patterns";
import { Card, DomainDot, Meta, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import type { TodayPayload } from "@/lib/payloads";

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

export default function TodayPage() {
  // One request: the backend bundles the next run and the sync list into
  // /today because rebuilding those read models separately is expensive.
  const state = useApi<TodayPayload>("/today");
  return <Loaded state={state}>{(data) => <Today data={data} />}</Loaded>;
}

function Today({ data }: { data: TodayPayload }) {
  const syncSources = data.syncSources;
  const now = new Date();
  const part = daypart(now.getHours());
  const dateLine = now.toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
  });
  const nextRun = data.nextRun;

  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      <header className="mb-4">
        <p className="text-[13px] font-medium text-muted">
          {dateLine} · {part}
          {/* freshness arrives as a full phrase, e.g. "Last source refresh 1d ago" */}
          {data.freshness && <span className="text-faint"> · {data.freshness.toLowerCase()}</span>}
        </p>
        <h1 className="text-2xl font-semibold tracking-tight text-text lg:text-[28px]">
          Good {part === "night" ? "evening" : part}
          {data.user.name ? `, ${data.user.name}` : ""}
        </h1>
      </header>

      {/* Summary band */}
      {data.statusStrip.length > 0 && (
        <div className="mb-5">
          <StatusStrip items={data.statusStrip} />
        </div>
      )}

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_var(--rail-w)] xl:items-start">
        {/* Central workspace */}
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

          {/* Next action */}
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
            {syncSources.length ? (
              <ul className="space-y-1.5">
                {syncSources.map((s) => (
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
