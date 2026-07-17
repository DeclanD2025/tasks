import Link from "next/link";
import { TrendChart } from "@/components/charts";
import { MetricStat } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Card, SectionHeader } from "@/components/ui";
import { getMetric, HEALTH_METRICS, METRICS } from "@/lib/data";

export default function HealthPage() {
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
      <Card className="p-4 sm:p-5">
        <SectionHeader title="VO₂ max — 90 days" sub={METRICS.vo2max.interpretation} action={<Link href="/insights/metric/vo2max" className="text-[12px] font-medium text-muted hover:text-text">Detail →</Link>} />
        <TrendChart series={METRICS.vo2max.series} domain="cardio" baseline={METRICS.vo2max.baseline30} unit="ml/kg/min" decimals={1} rolling={7} />
      </Card>

      {/* Metric grid */}
      <div>
        <SectionHeader title="Body metrics" sub="Each opens a full historical view with source, baseline and calculation." />
        <div className="grid grid-cols-2 gap-3 lg:grid-cols-2">
          {HEALTH_METRICS.map((k) => {
            const m = getMetric(k);
            return m ? <MetricStat key={k} metric={m} /> : null;
          })}
        </div>
      </div>

      <p className="px-1 text-[11px] text-faint">
        Readiness, sleep, HRV and sleep debt are the recovery decision — they live in{" "}
        <Link href="/recovery" className="underline-offset-2 hover:underline">Recovery</Link>, shown here only where relevant.
      </p>
    </Page>
  );
}
