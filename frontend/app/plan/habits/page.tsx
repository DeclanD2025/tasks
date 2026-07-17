import { Check } from "lucide-react";
import { Page } from "@/components/shell";
import { Card, DomainDot } from "@/components/ui";
import { domainStyle } from "@/lib/domains";
import { HABITS } from "@/lib/data";

const DOW = ["M", "T", "W", "T", "F", "S", "S"];

export default function HabitsPage() {
  return (
    <Page title="Habits" eyebrow="Plan & record · routines and streaks">
      <Card className="divide-y divide-border">
        {HABITS.map((h) => (
          <div key={h.id} className="flex items-center gap-4 p-3.5" style={domainStyle(h.domain)}>
            <button
              aria-pressed={h.doneToday}
              className={`grid size-9 shrink-0 place-items-center rounded-full transition-colors ${h.doneToday ? "text-white" : "border border-border text-faint"}`}
              style={h.doneToday ? { background: `var(--${h.domain})` } : undefined}
            >
              <Check className="size-4" />
            </button>
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2">
                <DomainDot domain={h.domain} />
                <p className="text-[14px] font-medium text-text">{h.name}</p>
              </div>
              <p className="text-[12px] text-muted">{h.cadence} · {h.streak}-day streak</p>
            </div>
            <div className="hidden gap-1 sm:flex">
              {h.weekTicks.map((t, i) => (
                <div key={i} className="flex flex-col items-center gap-1">
                  <span className="text-[9px] text-faint">{DOW[i]}</span>
                  <span className={`size-4 rounded-[3px] ${t ? "domain-bar" : "bg-surface-inset"}`} />
                </div>
              ))}
            </div>
          </div>
        ))}
      </Card>
      <p className="px-1 text-[11px] text-faint">Ticks feed streaks and appear on Today under “Due now”. Missed days never break the underlying data — only the streak count.</p>
    </Page>
  );
}
