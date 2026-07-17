import { ArrowRight, Dumbbell } from "lucide-react";
import Link from "next/link";
import { RecommendationCard } from "@/components/interactive";
import { ChangeList, StatusStrip, TimelineList } from "@/components/patterns";
import { Card, DomainDot, Meta, SectionHeader } from "@/components/ui";
import { domainStyle } from "@/lib/domains";
import { CHANGES, RUN_PLAN, STATUS_STRIP, SYNC_SOURCES, TIMELINE, TODAY_RECOMMENDATION, USER } from "@/lib/data";

const syncTone = {
  ok: "text-good",
  stale: "text-warn",
  disconnected: "text-faint",
  mock: "text-info",
} as const;

export default function TodayPage() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      <header className="mb-4">
        <p className="text-[13px] font-medium text-muted">Friday 17 July · morning</p>
        <h1 className="text-2xl font-semibold tracking-tight text-text lg:text-[28px]">Good morning, {USER.name}</h1>
      </header>

      {/* Summary band */}
      <div className="mb-5">
        <StatusStrip items={STATUS_STRIP} />
      </div>

      <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_var(--rail-w)] xl:items-start">
        {/* Central workspace */}
        <div className="min-w-0 space-y-5">
          <RecommendationCard rec={TODAY_RECOMMENDATION} />

          <Card className="p-4 sm:p-5">
            <SectionHeader title="Today" sub="Scheduled and completed, in order" action={<Link href="/plan" className="text-[12px] font-medium text-muted hover:text-text">Week →</Link>} />
            <TimelineList entries={TIMELINE} />
          </Card>

          {/* Next action */}
          <Card className="p-4 sm:p-5">
            <div className="flex items-start justify-between gap-4" style={domainStyle("running")}>
              <div className="min-w-0">
                <div className="mb-1 flex items-center gap-1.5">
                  <DomainDot domain="running" />
                  <span className="text-[11px] font-semibold uppercase tracking-wide text-muted">Next action · 12:30</span>
                </div>
                <h3 className="text-[15px] font-semibold text-text">{RUN_PLAN.nextRun.title}</h3>
                <p className="mt-0.5 text-[13px] text-muted">
                  {RUN_PLAN.nextRun.structure.map((s) => s.detail).join(" · ")}
                </p>
                <Meta className="mt-1 block">~{RUN_PLAN.nextRun.estMin} min · {RUN_PLAN.phase}</Meta>
              </div>
              <Link href="/training" className="shrink-0 rounded-lg px-3 py-2 text-[13px] font-medium text-white" style={{ background: "var(--running)" }}>
                Open
              </Link>
            </div>
          </Card>
        </div>

        {/* Right rail */}
        <aside className="space-y-4">
          <Card className="p-4">
            <SectionHeader title="What changed" sub="Since yesterday" />
            <ChangeList changes={CHANGES} />
            <Link href="/insights" className="mt-3 inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">
              All insights <ArrowRight className="size-3.5" />
            </Link>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Due now" />
            <ul className="space-y-2 text-[13px]">
              <li className="flex items-center gap-2" style={domainStyle("recovery")}>
                <DomainDot domain="recovery" /> 10-min mobility <span className="ml-auto text-faint">habit</span>
              </li>
              <li className="flex items-center gap-2" style={domainStyle("strength")}>
                <Dumbbell className="size-3.5 text-strength" /> Push session <span className="ml-auto text-faint">18:00</span>
              </li>
            </ul>
          </Card>

          <Card className="p-4">
            <SectionHeader title="Data sync" action={<Link href="/data" className="text-[12px] font-medium text-muted hover:text-text">Manage</Link>} />
            <ul className="space-y-1.5">
              {SYNC_SOURCES.map((s) => (
                <li key={s.name} className="flex items-center justify-between text-[12.5px]">
                  <span className="flex items-center gap-1.5 text-muted">
                    <span aria-hidden className={`size-1.5 rounded-full bg-current ${syncTone[s.status]}`} />
                    {s.name}
                  </span>
                  <Meta>{s.status === "disconnected" ? "connect" : s.freshness}</Meta>
                </li>
              ))}
            </ul>
          </Card>
        </aside>
      </div>
    </div>
  );
}
