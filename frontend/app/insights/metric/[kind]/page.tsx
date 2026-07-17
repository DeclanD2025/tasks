import { ChevronLeft } from "lucide-react";
import Link from "next/link";
import { notFound } from "next/navigation";
import { MetricDetailView } from "@/components/interactive";
import { Card } from "@/components/ui";
import { ALL_METRIC_KINDS, getMetric } from "@/lib/data";

export function generateStaticParams() {
  return ALL_METRIC_KINDS.map((kind) => ({ kind }));
}

export default async function MetricDetailPage({ params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  const metric = getMetric(kind);
  if (!metric) notFound();

  return (
    <div className="mx-auto w-full max-w-3xl px-4 py-5 lg:px-6 lg:py-6">
      <Link href="/insights" className="mb-4 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text">
        <ChevronLeft className="size-4" /> Insights
      </Link>
      <h1 className="mb-4 text-2xl font-semibold tracking-tight text-text">{metric.title}</h1>
      <Card className="p-4 sm:p-5">
        <MetricDetailView metric={metric} />
      </Card>
    </div>
  );
}
