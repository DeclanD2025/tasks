"use client";

import Link from "next/link";
import { Ring, TrendChart } from "@/components/charts";
import { Loaded } from "@/components/loading";
import { EmptyState, MetricStat } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Button, Card, Meta, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import type { RecoveryPayload } from "@/lib/payloads";

const primary = ["sleep", "hrv", "resting_hr"];

export default function RecoveryPage() {
  const state = useApi<RecoveryPayload>("/recovery");
  return <Loaded state={state}>{(data) => <Recovery data={data} />}</Loaded>;
}

function Recovery({ data }: { data: RecoveryPayload }) {
  const readiness = data.metrics.readiness;
  const sleepDebt = data.metrics.sleep_debt;
  const factors = data.factors.filter((f) => f.present);

  return (
    <Page title="Recovery" eyebrow="Understand · how ready you are today">
      {/* Hero */}
      <Card className="p-5">
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center" style={domainStyle("recovery")}>
          <Ring value={data.score} domain="recovery" size={132} label="/ 100" />
          <div className="min-w-0 flex-1 text-center sm:text-left">
            <div className="text-[11px] font-semibold uppercase tracking-wide domain-text">
              Readiness · {data.label}
              {data.estimated && <span className="ml-1 text-faint">(estimated)</span>}
            </div>
            <p className="mt-1 max-w-md text-[15px] leading-relaxed text-text">{data.recommendation}</p>
            <div className="mt-3 flex flex-wrap justify-center gap-2 sm:justify-start">
              <Button href="/insights/metric/readiness" variant="ghost" size="sm">See how this is calculated</Button>
              <Meta className="self-center">data quality: {data.dataQuality}</Meta>
            </div>
          </div>
        </div>
      </Card>

      {/* Factor breakdown */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="What's driving readiness" sub="Each input scored against your own baseline. Tap a related metric for the full history." />
        {factors.length ? (
          <ul className="divide-y divide-border">
            {factors.map((f) => (
              <li key={f.label} className="flex items-center justify-between gap-4 py-2.5">
                <div className="min-w-0">
                  <p className="text-[14px] font-medium text-text">{f.label}</p>
                  <p className="text-[12px] text-muted">{f.impact}</p>
                </div>
                <span className={`tnum shrink-0 text-[15px] font-semibold ${f.delta < 0 ? "text-warn" : "text-good"}`}>{f.value}</span>
              </li>
            ))}
          </ul>
        ) : (
          <EmptyState title="No inputs available" body="Readiness needs sleep, HRV or resting heart-rate readings." cta="Import" href="/data" />
        )}
      </Card>

      {/* Primary signals */}
      <div>
        <SectionHeader title="Primary signals" sub="The inputs that matter most for recovery" />
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {primary.map((k) => {
            const m = data.metrics[k];
            return m ? <MetricStat key={k} metric={m} /> : null;
          })}
        </div>
      </div>

      {/* Sleep debt */}
      <Card className="p-4 sm:p-5" as="section">
        <SectionHeader title="Sleep debt" sub="Recent nights against your personal need (not a generic 8-hour rule)" />
        {data.sleepDebt.calibrating ? (
          <EmptyState
            title={`Calibrating — ${data.sleepDebt.nightsRecorded} nights recorded`}
            body="ORION learns your own nightly need before it reports a debt against it."
          />
        ) : sleepDebt && sleepDebt.facts.length ? (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {sleepDebt.facts.map((f) => (
              <div key={f.label} className="rounded-lg border border-border bg-surface-2 p-3">
                <div className="tnum text-lg font-semibold text-text">{f.value}</div>
                <div className="text-[11px] text-muted">{f.label}</div>
              </div>
            ))}
          </div>
        ) : (
          <p className="text-[13px] text-muted">{data.sleepDebt.label}</p>
        )}
        <p className="mt-3 text-[12.5px] text-muted">
          Need is the trimmed mean of your recent plausible nights; debt is the net shortfall against it. Under 15 minutes reads as clear.
          <Link href="/insights/metric/sleep" className="ml-1 font-medium text-text underline-offset-2 hover:underline">Sleep trend →</Link>
        </p>
      </Card>

      {/* Trend chart */}
      {readiness && readiness.series.length > 0 && (
        <Card className="p-4 sm:p-5">
          <SectionHeader title="Readiness trend" />
          <TrendChart series={readiness.series} domain="recovery" band={readiness.band} baseline={readiness.baseline30} unit="/100" decimals={0} />
        </Card>
      )}
      <p className="px-1 text-[11px] text-faint">
        Recovery is a planning guide built from your own baselines, not a medical assessment. Metrics also live in{" "}
        <Link href="/health" className="underline-offset-2 hover:underline">Health</Link>.
      </p>
    </Page>
  );
}
