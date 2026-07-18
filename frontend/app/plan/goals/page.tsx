"use client";

import { Loaded } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Card } from "@/components/ui";
import { useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import type { PlanPayload } from "@/lib/payloads";

export default function GoalsPage() {
  const state = useApi<PlanPayload>("/plan");
  return (
    <Loaded state={state}>
      {({ goals, unavailable }) => (
        <Page title="Goals" eyebrow="Plan & record · what you're working toward">
          {goals.length ? (
            <div className="grid gap-4 sm:grid-cols-2">
              {goals.map((g) => (
                <Card key={g.id} className="p-4" style={domainStyle(g.domain)}>
                  <div className="mb-2 flex items-baseline justify-between gap-3">
                    <h2 className="text-[15px] font-semibold text-text">{g.title}</h2>
                    <span className="tnum shrink-0 text-[12px] text-muted">{g.dueLabel}</span>
                  </div>
                  <div className="mb-2 h-1.5 overflow-hidden rounded-full bg-surface-inset">
                    <div className="h-full rounded-full domain-bar" style={{ width: `${g.progress * 100}%` }} />
                  </div>
                  <p className="tnum text-[13px] text-text">
                    {g.metricLabel}: {g.current} → {g.target}
                  </p>
                  <p className="mt-1 text-[12.5px] text-muted">{g.projection}</p>
                </Card>
              ))}
            </div>
          ) : (
            <EmptyState
              title="Goals aren't tracked yet"
              body={unavailable.goals}
              compact={false}
            />
          )}
        </Page>
      )}
    </Loaded>
  );
}
