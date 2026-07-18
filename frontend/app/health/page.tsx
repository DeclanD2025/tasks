"use client";

import Link from "next/link";
import { TrendChart } from "@/components/charts";
import { Loaded } from "@/components/loading";
import { EmptyState, MetricStat } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Card, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { HealthPayload } from "@/lib/payloads";
import { HEALTH_METRICS } from "@/lib/metrics";

export default function HealthPage() {
  const state = useApi<HealthPayload>("/health?days=180");
  return <Loaded state={state}>{(data) => <Health metrics={data.metrics} />}</Loaded>;
}

function Health({ metrics }: { metrics: HealthPayload["metrics"] }) {
  const vo2 = metrics.vo2max;
  const shown = HEALTH_METRICS.map((k) => metrics[k]).filter(Boolean);

  return (
    <Page
      title="Health"
      eyebrow="Understand · cardiovascular and body metrics"
      rail={
        <>
          <Card className="p-4">
            <SectionHeader title="Longitudinal" sub="Slow-moving vitals" />
            <p className="text-[13px] text-muted">
              These change over months. The 90-day direction is the signal — day-to-day noise is expected.
            </p>
          </Card>
          <Card className="p-4">
            <SectionHeader title="Related" />
            <ul className="space-y-1.5 text-[13px]">
              <li><Link href="/recovery" className="text-muted hover:text-text">Recovery & readiness →</Link></li>
              <li><Link href="/insights/metric/respiratory_rate" className="text-muted hover:text-text">Respiratory rate →</Link></li>
              <li><Link href="/data" className="text-muted hover:text-text">Data sources →</Link></li>
            </ul>
          </Card>
        </>
      }
    >
      {/* Featured */}
      {vo2 && vo2.series.length > 0 && (
        <Card className="p-4 sm:p-5">
          <SectionHeader
            title="VO₂ max"
            sub={vo2.interpretation}
            action={<Link href="/insights/metric/vo2max" className="text-[12px] font-medium text-muted hover:text-text">Detail →</Link>}
          />
          <TrendChart series={vo2.series} domain="cardio" baseline={vo2.baseline30} unit={vo2.unit} decimals={vo2.decimals} rolling={7} />
        </Card>
      )}

      {/* Metric grid */}
      <div>
        <SectionHeader title="Body metrics" sub="Each opens a full historical view with source, baseline and calculation." />
        {shown.length ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-2">
            {shown.map((m) => <MetricStat key={m.kind} metric={m} />)}
          </div>
        ) : (
          <EmptyState
            title="No health readings yet"
            body="Import a Health Auto Export file and these fill in."
            cta="Import"
            href="/data"
            compact={false}
          />
        )}
      </div>

      <p className="px-1 text-[11px] text-faint">
        Readiness, sleep, HRV and sleep debt are the recovery decision — they live in{" "}
        <Link href="/recovery" className="underline-offset-2 hover:underline">Recovery</Link>, shown here only where relevant.
      </p>
    </Page>
  );
}
