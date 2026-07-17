import { ArrowRight, Circle } from "lucide-react";
import Link from "next/link";
import { Page } from "@/components/shell";
import { Card } from "@/components/ui";
import { type DomainKey, domainStyle } from "@/lib/domains";

/**
 * Honest scaffold for a destination that the redesign has specced but not yet
 * built out. Compact by design (audit §5 — empty states must not dominate).
 */
export function ModulePlaceholder({
  title,
  eyebrow,
  domain = "neutral",
  summary,
  owns,
  source,
  state,
  link,
}: {
  title: string;
  eyebrow: string;
  domain?: DomainKey;
  summary: string;
  owns: string[];
  source: string;
  state: string;
  link?: { href: string; label: string };
}) {
  return (
    <Page title={title} eyebrow={eyebrow}>
      <Card className="p-5" style={domainStyle(domain)}>
        <div className="flex items-center gap-2">
          <span className="size-2.5 rounded-full domain-bar" />
          <span className="text-[11px] font-semibold uppercase tracking-wide domain-text">Specced · incremental build</span>
        </div>
        <p className="mt-2 max-w-2xl text-[15px] leading-relaxed text-text">{summary}</p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2">
          <div>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">This screen owns</p>
            <ul className="space-y-1">
              {owns.map((o) => (
                <li key={o} className="flex items-start gap-2 text-[13px] text-muted">
                  <Circle className="mt-1.5 size-1.5 shrink-0 fill-current domain-text" />
                  {o}
                </li>
              ))}
            </ul>
          </div>
          <div className="space-y-3 text-[13px]">
            <div>
              <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Data source</p>
              <p className="text-muted">{source}</p>
            </div>
            <div>
              <p className="mb-0.5 text-[11px] font-semibold uppercase tracking-wide text-faint">Current state</p>
              <p className="text-muted">{state}</p>
            </div>
          </div>
        </div>

        {link && (
          <Link href={link.href} className="mt-4 inline-flex items-center gap-1 text-[13px] font-medium domain-text">
            {link.label} <ArrowRight className="size-4" />
          </Link>
        )}
      </Card>
    </Page>
  );
}
