import { ALL_METRIC_KINDS } from "@/lib/metrics";
import { MetricDetailClient } from "./client";

export function generateStaticParams() {
  return ALL_METRIC_KINDS.map((kind) => ({ kind }));
}

/** Server shell: a static export needs every kind's route generated at build
 *  time, so the page stays a server component and the fetching happens in the
 *  client child. */
export default async function MetricDetailPage({ params }: { params: Promise<{ kind: string }> }) {
  const { kind } = await params;
  return <MetricDetailClient kind={kind} />;
}
