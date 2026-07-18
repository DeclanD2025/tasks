"use client";

import { Plus, Trophy } from "lucide-react";
import Link from "next/link";
import { TrendChart } from "@/components/charts";
import { Loaded } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Button, Card, Chip, DomainDot, Meta, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import type { PlanPayload, TrainingPayload } from "@/lib/payloads";

export default function TrainingPage() {
  const state = useApi<TrainingPayload>("/training");
  const plan = useApi<PlanPayload>("/plan");
  return (
    <Loaded state={state}>
      {(data) => <Training data={data} week={plan.data?.week ?? []} />}
    </Loaded>
  );
}

function Training({ data, week }: { data: TrainingPayload; week: PlanPayload["week"] }) {
  const { runPlan, strength, metrics } = data;
  const runPct = runPlan.weekTargetKm
    ? Math.round((runPlan.weekDoneKm / runPlan.weekTargetKm) * 100)
    : 0;
  const load = metrics.training_load;
  const remaining = Math.max(0, runPlan.weekTargetKm - runPlan.weekDoneKm);

  return (
    <Page
      title="Training"
      eyebrow={`${runPlan.goal} · ${runPlan.phase}`}
      rail={
        <>
          <Card className="p-4">
            <SectionHeader title="Log a session" />
            <div className="space-y-2">
              <Button href="/training/strength" variant="accent" domain="strength" size="md" className="w-full">
                <Plus className="size-4" /> Start strength workout
              </Button>
              <Button href="/log?for=run" variant="ghost" size="md" className="w-full">Log run / cardio</Button>
            </div>
            <p className="mt-2 text-[11px] text-faint">Runs import automatically from Apple Health — logging is for anything not captured.</p>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Personal bests" />
            {strength.personalBests.length ? (
              <ul className="space-y-2">
                {strength.personalBests.map((pb, i) => (
                  <li key={i} className="flex items-center gap-2.5" style={domainStyle("strength")}>
                    <Trophy className="size-4 shrink-0 domain-text" />
                    <p className="min-w-0 flex-1 text-[13px] font-medium text-text">{pb}</p>
                  </li>
                ))}
              </ul>
            ) : (
              <EmptyState title="None logged" body="Log a strength session and ORION tracks your bests." cta="Log" href="/log" />
            )}
          </Card>
        </>
      }
    >
      {/* Next session */}
      <Card className="overflow-hidden">
        <div className="domain-bar h-1 w-full" style={domainStyle("running")} />
        <div className="p-4 sm:p-5" style={domainStyle("running")}>
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <span className="text-[11px] font-semibold uppercase tracking-wide domain-text">
                Next session · {runPlan.nextRun.dayLabel}
              </span>
              <h2 className="mt-1 text-lg font-semibold tracking-tight text-text">{runPlan.nextRun.title}</h2>
            </div>
            <Button href="/log?for=run" variant="accent" domain="running" size="sm">Start session</Button>
          </div>
          <div className="mt-3 flex items-center gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2">
            <span className="flex-1 text-[13px] text-text">{runPlan.nextRun.detail}</span>
            <Chip>{runPlan.nextRun.intensity}</Chip>
          </div>
          <Meta className="mt-2 block">{runPlan.nextRun.distanceKm.toFixed(1)} km</Meta>
        </div>
      </Card>

      {/* Week recorded */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="This week" sub={`Recorded activity · ${runPlan.adherence}`} action={<Link href="/plan" className="text-[12px] font-medium text-muted hover:text-text">Full plan →</Link>} />
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:grid-cols-7">
          {week.map((day) => (
            <div key={day.date} className={`rounded-lg border p-2 ${day.isToday ? "border-border-strong bg-surface-2" : "border-border bg-surface"}`}>
              <div className="mb-1.5 flex items-baseline justify-between">
                <span className={`text-[11px] font-semibold ${day.isToday ? "text-text" : "text-muted"}`}>{day.dow}</span>
                <span className="tnum text-[11px] text-faint">{day.dom}</span>
              </div>
              <div className="space-y-1">
                {day.sessions.length === 0 ? (
                  <p className="py-1 text-[11px] text-faint">Rest</p>
                ) : (
                  day.sessions.map((s) => (
                    <div key={s.id} className="rounded-md border border-border px-1.5 py-1" style={domainStyle(s.domain)}>
                      <div className="flex items-center gap-1">
                        <DomainDot domain={s.domain} />
                        <span className="truncate text-[11px] font-medium text-text">{s.title}</span>
                      </div>
                      <p className="truncate text-[10px] text-muted">{s.detail}</p>
                    </div>
                  ))
                )}
              </div>
            </div>
          ))}
        </div>
      </Card>

      {/* Running + strength */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Card className="p-4" as="section">
          <div style={domainStyle("running")}>
            <SectionHeader title="Weekly running" action={<span className="tnum text-[13px] font-semibold text-text">{runPlan.weekDoneKm.toFixed(1)}<span className="text-faint"> / {runPlan.weekTargetKm.toFixed(0)} km</span></span>} />
            <div className="h-2 overflow-hidden rounded-full bg-surface-inset">
              <div className="h-full rounded-full domain-bar" style={{ width: `${Math.min(100, runPct)}%` }} />
            </div>
            <dl className="mt-3 grid grid-cols-3 gap-2 text-center">
              <Kpi label="Avg distance" value={`${runPlan.fourWeekAvgKm.toFixed(1)} km`} />
              <Kpi label="Avg pace" value={runPlan.avgPace} />
              <Kpi label="Left" value={`${remaining.toFixed(1)} km`} />
            </dl>
            <Link href="/insights/metric/run_distance" className="mt-2 inline-block text-[12px] font-medium text-muted hover:text-text">Distance trend →</Link>
          </div>
        </Card>

        <Card className="p-4" as="section">
          <div style={domainStyle("strength")}>
            <SectionHeader title="Strength consistency" action={<span className="tnum text-[13px] font-semibold text-text">{strength.weekSessions}<span className="text-faint"> this week</span></span>} />
            <dl className="mt-1 grid grid-cols-2 gap-2 text-center">
              <Kpi label="Sessions (30d)" value={String(strength.recentSessions.length)} />
              <Kpi label="Volume" value={strength.weekVolumeKg >= 1000 ? `${(strength.weekVolumeKg / 1000).toFixed(1)}t` : `${strength.weekVolumeKg.toFixed(0)}kg`} />
            </dl>
            {strength.progressionInsight && <p className="mt-2 text-[12px] text-muted">{strength.progressionInsight}</p>}
          </div>
        </Card>
      </div>

      {/* Load */}
      {load && load.series.length > 0 && (
        <Card className="p-4 sm:p-5">
          <SectionHeader title="Training load" sub={load.interpretation} action={<Link href="/insights/metric/training_load" className="text-[12px] font-medium text-muted hover:text-text">Detail →</Link>} />
          <TrendChart series={load.series} domain="running" baseline={load.baseline30} decimals={0} rolling={7} />
        </Card>
      )}
    </Page>
  );
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="tnum text-[15px] font-semibold text-text">{value}</div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  );
}
