import { Page } from "@/components/shell";
import { Card, DomainDot } from "@/components/ui";
import { DOMAIN_LABEL, domainStyle } from "@/lib/domains";
import { GOALS } from "@/lib/data";

export default function GoalsPage() {
  return (
    <Page title="Goals" eyebrow="Plan & record · outcomes and projections">
      <div className="grid gap-4 lg:grid-cols-2">
        {GOALS.map((g) => (
          <Card key={g.id} className="p-4" as="article">
            <div style={domainStyle(g.domain)}>
              <div className="mb-2 flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <DomainDot domain={g.domain} />
                  <h2 className="text-[15px] font-semibold text-text">{g.title}</h2>
                </div>
                <span className="text-[11px] text-faint">{g.dueLabel}</span>
              </div>
              <div className="mb-1 flex items-baseline justify-between">
                <span className="text-[12px] text-muted">{g.metricLabel}</span>
                <span className="tnum text-[13px] font-semibold text-text">{g.current} <span className="text-faint">→ {g.target}</span></span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-surface-inset">
                <div className="h-full rounded-full domain-bar" style={{ width: `${g.progress * 100}%` }} />
              </div>
              <p className="mt-2.5 rounded-lg bg-surface-2 p-2.5 text-[12.5px] text-muted">
                <span className="font-medium text-text">Projection. </span>{g.projection}
              </p>
              <p className="mt-1.5 text-[11px] text-faint">{DOMAIN_LABEL[g.domain]} · {Math.round(g.progress * 100)}% to target</p>
            </div>
          </Card>
        ))}
      </div>
    </Page>
  );
}
