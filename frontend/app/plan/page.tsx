import { ArrowRight, Flag, Plus } from "lucide-react";
import Link from "next/link";
import { Page } from "@/components/shell";
import { Card, DomainDot, SectionHeader } from "@/components/ui";
import { type DomainKey, domainStyle } from "@/lib/domains";
import { GOALS, HABITS, weekPlan } from "@/lib/data";

const loadTone = {
  clear: "bg-good/50",
  light: "bg-good",
  loaded: "bg-warn",
  heavy: "bg-crit",
} as const;

export default function PlanPage() {
  const week = weekPlan();
  return (
    <Page
      title="Plan"
      eyebrow="Act · your week ahead"
      rail={
        <>
          <Card className="p-4">
            <SectionHeader title="Milestones" />
            <ul className="space-y-2.5">
              <li className="flex items-start gap-2.5" style={domainStyle("running")}>
                <Flag className="mt-0.5 size-4 shrink-0 domain-text" />
                <div><p className="text-[13px] font-medium text-text">Autumn 10k race</p><p className="text-[12px] text-muted">21 Sep · 9 weeks out</p></div>
              </li>
              <li className="flex items-start gap-2.5" style={domainStyle("strength")}>
                <Flag className="mt-0.5 size-4 shrink-0 domain-text" />
                <div><p className="text-[13px] font-medium text-text">Deload week</p><p className="text-[12px] text-muted">Week 5 · starts 27 Jul</p></div>
              </li>
            </ul>
          </Card>
          <Card className="p-4">
            <SectionHeader title="Conflicts" />
            <div className="flex items-start gap-2 rounded-lg border border-warn/30 bg-warn/10 p-2.5">
              <span className="mt-1 size-1.5 shrink-0 rounded-full bg-warn" />
              <p className="text-[12.5px] text-text">Wed stacks intervals + push — <span className="text-warn">high load</span>. Consider moving push to Thu.</p>
            </div>
          </Card>
        </>
      }
    >
      {/* Week schedule */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="This week" sub="Training, habits and planned meals. Load bar shows each day's demand." />
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
              <button className="mt-1 flex items-center justify-center gap-0.5 rounded-md border border-dashed border-border py-1 text-[10px] font-medium text-faint hover:text-muted">
                <Plus className="size-3" /> Add
              </button>
            </div>
          ))}
        </div>
      </Card>

      {/* Habits + Goals */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4" as="section">
          <SectionHeader title="Habits" sub="This week" action={<Link href="/plan/habits" className="inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">All <ArrowRight className="size-3.5" /></Link>} />
          <ul className="space-y-2.5">
            {HABITS.slice(0, 4).map((h) => (
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
        </Card>

        <Card className="p-4" as="section">
          <SectionHeader title="Goals" action={<Link href="/plan/goals" className="inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">All <ArrowRight className="size-3.5" /></Link>} />
          <ul className="space-y-3">
            {GOALS.slice(0, 3).map((g) => (
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
        </Card>
      </div>
    </Page>
  );
}
