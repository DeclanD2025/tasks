"use client";

import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { MetricDetailView } from "@/components/interactive";
import { Loaded, Skeleton } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Card } from "@/components/ui";
import { useApi } from "@/lib/api";
import type { MetricDetail } from "@/lib/types";

export function MetricDetailClient({ kind }: { kind: string }) {
  const state = useApi<MetricDetail>(`/metrics/${kind}?days=180`);

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-5 lg:px-6 lg:py-6">
      <Link href="/insights" className="mb-4 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text">
        <ChevronLeft className="size-4" /> Insights
      </Link>
      <Loaded
        state={state}
        skeleton={
          <>
            <Skeleton className="mb-4 h-8 w-56" />
            <Skeleton className="h-80" />
          </>
        }
      >
        {(metric) => (
          <>
            <h1 className="mb-4 text-2xl font-semibold tracking-tight text-text">{metric.title}</h1>
            <Card className="p-4 sm:p-5">
              {metric.series.length || metric.facts.length ? (
                <MetricDetailView metric={metric} />
              ) : (
                <EmptyState
                  title={`No ${metric.title.toLowerCase()} readings`}
                  body={metric.meaning}
                  cta="Import data"
                  href="/data"
                  compact={false}
                />
              )}
            </Card>
          </>
        )}
      </Loaded>
    </div>
  );
}
