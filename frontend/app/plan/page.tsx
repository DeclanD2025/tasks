"use client";

import { ArrowRight, Flag, ShieldAlert } from "lucide-react";
import Link from "next/link";
import { Loaded } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Card, DomainDot, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { type DomainKey, domainStyle } from "@/lib/domains";
import type { PlanPayload, TrainingPayload } from "@/lib/payloads";

const loadTone = {
  clear: "bg-good/50",
  light: "bg-good",
  loaded: "bg-warn",
  heavy: "bg-crit",
} as const;

export default function PlanPage() {
  const state = useApi<PlanPayload>("/plan");
  const training = useApi<TrainingPayload>("/training");
  return <Loaded state={state}>{(data) => <Plan data={data} runPlan={training.data?.runPlan} />}</Loaded>;
}

function Plan({ data, runPlan }: { data: PlanPayload; runPlan?: TrainingPayload["runPlan"] }) {
  const { week, planned, habits, goals, unavailable } = data;

  return (
    <Page
      title="Plan"
      eyebrow="Act · your week ahead"
      rail={
        <>
          <Card className="p-4">
            <SectionHeader title="Objective" />
            {runPlan ? (
              <ul className="space-y-2.5">
                <li className="flex items-start gap-2.5" style={domainStyle("running")}>
                  <Flag className="mt-0.5 size-4 shrink-0 domain-text" />
                  <div>
                    <p className="text-[13px] font-medium text-text">{runPlan.goal}</p>
                    <p className="text-[12px] text-muted">{runPlan.phase} · {runPlan.adherence}</p>
                  </div>
                </li>
              </ul>
            ) : (
              <EmptyState title="No plan loaded" body="ORION sets a run objective once it has enough activity history." />
            )}
          </Card>
          {runPlan?.guardrail && (
            <Card className="p-4">
              <SectionHeader title="Guardrail" />
              <div className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 p-2.5">
                <ShieldAlert className="mt-0.5 size-4 shrink-0 text-warn" />
                <p className="text-[12.5px] text-text">{runPlan.guardrail}</p>
              </div>
            </Card>
          )}
        </>
      }
    >
      {/* Planned sessions — under the planner's own relative labels */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="Planned sessions" sub="ORION schedules these relative to now, not to fixed weekdays." />
        {planned.length ? (
          <ul className="space-y-2">
            {planned.map((s) => (
              <li key={s.id} className="flex items-center gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2.5" style={domainStyle("running")}>
                <span className="w-20 shrink-0 text-[12px] font-semibold uppercase tracking-wide domain-text">{s.when}</span>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[13px] font-medium text-text">{s.title}</p>
                  <p className="truncate text-[12px] text-muted">{s.detail}</p>
                </div>
                <span className="tnum shrink-0 text-[12px] text-muted">{s.distanceKm.toFixed(1)} km</span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No sessions planned" body="ORION builds a run plan once it has enough activity history." />
        )}
      </Card>

      {/* Week recorded */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="This week" sub="What was actually recorded. The bar shows each day's training load." />
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-7">
          {week.map((day) => (
            <div key={day.date} className={`flex flex-col rounded-lg border p-2 ${day.isToday ? "border-border-strong bg-surface-2" : "border-border bg-surface"}`}>
              <div className="mb-1 flex items-baseline justify-between">
                <span className={`text-[12px] font-semibold ${day.isToday ? "text-text" : "text-muted"}`}>{day.dow}</span>
                <span className="tnum text-[11px] text-faint">{day.dom}</span>
              </div>
              {day.loadBand && <div className={`mb-1.5 h-1 rounded-full ${loadTone[day.loadBand]}`} title={`Load: ${day.loadBand}`} />}
              <div className="flex-1 space-y-1">
                {day.sessions.map((s) => (
                  <div key={s.id} className="rounded-md border border-border px-1.5 py-1" style={domainStyle(s.domain as DomainKey)}>
                    <div className="flex items-center gap-1">
                      <DomainDot domain={s.domain} />
                      <span className="truncate text-[11px] font-medium text-text">{s.title}</span>
                    </div>
                    <p className="truncate text-[10px] text-muted">{s.detail}</p>
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Habits + Goals */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4" as="section">
          <SectionHeader title="Habits" sub="This week" action={<Link href="/plan/habits" className="inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">All <ArrowRight className="size-3.5" /></Link>} />
          {habits.length ? (
            <ul className="space-y-2.5">
              {habits.slice(0, 4).map((h) => (
                <li key={h.id} className="flex items-center gap-3" style={domainStyle(h.domain)}>
                  <DomainDot domain={h.domain} />
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-text">{h.name}</span>
                  <div className="flex gap-0.5">
                    {h.weekTicks.map((t, i) => (
                      <span key={i} className={`size-2 rounded-[2px] ${t ? "domain-bar" : "bg-surface-inset"}`} />
                    ))}
                  </div>
                  <span className="tnum w-10 text-right text-[12px] font-medium text-muted">{h.streak}d</span>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Not tracked yet" body={unavailable.habits} />
          )}
        </Card>

        <Card className="p-4" as="section">
          <SectionHeader title="Goals" action={<Link href="/plan/goals" className="inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">All <ArrowRight className="size-3.5" /></Link>} />
          {goals.length ? (
            <ul className="space-y-3">
              {goals.slice(0, 3).map((g) => (
                <li key={g.id} style={domainStyle(g.domain)}>
                  <div className="mb-1 flex items-baseline justify-between">
                    <span className="text-[13px] font-medium text-text">{g.title}</span>
                    <span className="tnum text-[12px] text-muted">{g.current} → {g.target}</span>
                  </div>
                  <div className="h-1.5 overflow-hidden rounded-full bg-surface-inset">
                    <div className="h-full rounded-full domain-bar" style={{ width: `${g.progress * 100}%` }} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <EmptyState title="Not tracked yet" body={unavailable.goals} />
          )}
        </Card>
      </div>
    </Page>
  );
}
