"use client";

/**
 * The homepage — a daily brief, not a dashboard.
 *
 * It answers three questions in order, and the order is the design: how am I
 * doing, what matters today, what do I do next. Everything else sits below or
 * behind progressive disclosure.
 *
 * What this page deliberately does not do:
 *
 * - **No "95 tasks past due" as the opening statement.** The audit found 90 of
 *   those 95 belong to one project. "One publication's schedule slipped" is the
 *   same fact without the accusation, and it is the one a person can act on.
 * - **No sync-status card.** Plumbing appears only when it changes what ORION
 *   can conclude — one line, in the flow of the sentence it qualifies, never a
 *   permanent grid of green ticks.
 * - **No grid of interchangeable cards.** Hierarchy comes from type size and
 *   spacing: the brief is large and unboxed, priorities are cards because they
 *   are actionable, and everything below is quieter than both.
 * - **No number ORION cannot stand behind.** When a source is stale the page
 *   says so beside the claim, not in grey underneath it.
 *
 * Mobile is not the desktop stack. The brief and priorities come first at full
 * width; the timeline, review and insight follow in that order, because the
 * question "what do I do next" survives a small screen and a metric grid does
 * not.
 */

import {
  Check, ChevronDown, ChevronRight, Clock, Info, Pin, SkipForward,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useState } from "react";
import { Loaded } from "@/components/loading";
import { Page } from "@/components/shell";
import { Button, Card, Meta } from "@/components/ui";
import { getJson, useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import {
  type Brief,
  type Priority,
  briefApi,
  dayHeading,
  dueLabel,
} from "@/lib/brief";

export default function HomePage() {
  const state = useApi<Brief>("/brief");
  return <Loaded state={state}>{(data) => <Home initial={data} />}</Loaded>;
}

function Home({ initial }: { initial: Brief }) {
  const [brief, setBrief] = useState<Brief>(initial);

  const refresh = useCallback(() => {
    void getJson<Brief>("/brief").then(setBrief).catch(() => undefined);
  }, []);

  return (
    <Page title="" bare>
      <Orientation brief={brief} />

      {brief.priorities.length > 0 && (
        <Priorities brief={brief} onChange={setBrief} onRefresh={refresh} />
      )}

      <div className="grid gap-6 lg:grid-cols-[1.45fr_1fr]">
        <div className="space-y-6">
          <Flow brief={brief} />
          <Review brief={brief} />
        </div>
        <div className="space-y-6">
          {"title" in brief.insight && <Insight brief={brief} />}
          <Progress />
        </div>
      </div>

      <Provenance brief={brief} />
    </Page>
  );
}

// --------------------------------------------------------------------------- //
// 1. Daily orientation
// --------------------------------------------------------------------------- //
/**
 * The first screen. Unboxed and set large on purpose: this is the one thing
 * that should be readable at a glance, and putting it in a card would make it
 * a peer of everything below it.
 */
function Orientation({ brief }: { brief: Brief }) {
  const blocking = brief.dataQuality.filter((w) => w.severity === "warning");

  return (
    <header className="pt-1">
      <p className="text-[12px] font-semibold uppercase tracking-[0.08em] text-muted">
        {dayHeading(brief.day, brief.daypart)}
      </p>

      <h1 className="mt-2 max-w-[34ch] text-[26px] font-semibold leading-[1.25] tracking-tight text-text lg:text-[32px]">
        {brief.stateSummary}
      </h1>

      {brief.focus && (
        <p className="mt-3 max-w-[52ch] text-[16px] leading-relaxed text-muted lg:text-[17px]">
          {brief.focus}
        </p>
      )}

      {brief.nextAction && (
        <div className="mt-5 flex flex-wrap items-baseline gap-x-2 gap-y-1">
          <span className="text-[12px] font-semibold uppercase tracking-wide text-muted">
            Next
          </span>
          <span className="text-[17px] font-medium text-text">{brief.nextAction}</span>
        </div>
      )}

      {blocking.length > 0 && (
        <p className="mt-4 max-w-[62ch] border-l-2 border-border-strong pl-3 text-[13px] leading-relaxed text-muted">
          {blocking.map((w) => w.message).join(" ")}
        </p>
      )}
    </header>
  );
}

// --------------------------------------------------------------------------- //
// 2. Priorities — never more than three
// --------------------------------------------------------------------------- //
function Priorities({
  brief,
  onChange,
  onRefresh,
}: {
  brief: Brief;
  onChange: (b: Brief) => void;
  onRefresh: () => void;
}) {
  return (
    <section aria-labelledby="priorities-heading" className="space-y-2.5">
      <div className="flex items-baseline justify-between gap-3">
        <h2
          id="priorities-heading"
          className="text-[13px] font-semibold uppercase tracking-wide text-muted"
        >
          Worth finishing
        </h2>
        <Link href="/tasks" className="text-[12px] font-medium text-muted hover:text-text">
          All tasks →
        </Link>
      </div>

      {brief.priorities.map((priority) => (
        <PriorityCard
          key={priority.taskId}
          priority={priority}
          onChange={onChange}
          onRefresh={onRefresh}
        />
      ))}
    </section>
  );
}

function PriorityCard({
  priority,
  onChange,
  onRefresh,
}: {
  priority: Priority;
  onChange: (b: Brief) => void;
  onRefresh: () => void;
}) {
  const [showEvidence, setShowEvidence] = useState(false);
  const [busy, setBusy] = useState(false);

  const act = async (fn: () => Promise<Brief>) => {
    setBusy(true);
    try {
      onChange(await fn());
    } catch {
      onRefresh();
    } finally {
      setBusy(false);
    }
  };

  const due = dueLabel(priority.dueDate);

  return (
    <Card className="p-4">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <h3 className="text-[16px] font-medium leading-snug text-text">{priority.title}</h3>
        {priority.pinned && (
          <span className="inline-flex items-center gap-1 text-[11px] font-medium text-muted">
            <Pin className="size-3" aria-hidden="true" />
            pinned
          </span>
        )}
      </div>

      <p className="mt-0.5 text-[12px] text-muted">
        {priority.project}
        {due && ` · ${due}`}
        {priority.estimateMinutes ? ` · ~${priority.estimateMinutes} min` : ""}
      </p>

      {/* One sentence on why. The full breakdown is behind "Why this?" — an
          explanation nobody asked for is noise. */}
      <p className="mt-2 text-[13px] leading-relaxed text-muted">{priority.why}</p>

      {priority.nextAction && (
        <p className="mt-2 border-l-2 border-border pl-2.5 text-[13px] text-text">
          {priority.nextAction}
        </p>
      )}

      {priority.blocked && priority.waitingFor && (
        <p className="mt-2 text-[12px] text-muted">
          Blocked — waiting on {priority.waitingFor}.
        </p>
      )}

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          variant="accent"
          onClick={() => void act(() => briefApi.complete(priority.taskId))}
          disabled={busy}
        >
          <Check className="size-3.5" aria-hidden="true" /> Done
        </Button>
        <Button
          size="sm"
          variant="ghost"
          onClick={() => void act(() => briefApi.defer(priority.taskId))}
          disabled={busy}
        >
          <SkipForward className="size-3.5" aria-hidden="true" /> Not today
        </Button>
        {!priority.pinned && (
          <Button
            size="sm"
            variant="ghost"
            onClick={() => void act(() => briefApi.pin(priority.taskId))}
            disabled={busy}
          >
            <Pin className="size-3.5" aria-hidden="true" /> Pin
          </Button>
        )}
        <button
          type="button"
          onClick={() => {
            if (!showEvidence) void briefApi.event("evidence_opened", priority.taskId);
            setShowEvidence((v) => !v);
          }}
          aria-expanded={showEvidence}
          className="ml-auto inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text"
        >
          Why this?
          <ChevronDown
            className={`size-3.5 transition-transform ${showEvidence ? "rotate-180" : ""}`}
            aria-hidden="true"
          />
        </button>
      </div>

      {showEvidence && (
        <div className="mt-3 border-t border-border pt-3">
          <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-muted">
            {priority.selectedBy === "you" ? "You chose this" : "How ORION scored it"}
          </p>
          <ul className="space-y-1">
            {priority.components.map((component) => (
              <li key={component.key} className="flex items-baseline gap-2 text-[12px]">
                <span
                  className={`tnum w-11 shrink-0 text-right font-medium ${
                    component.points >= 0 ? "text-text" : "text-muted"
                  }`}
                >
                  {component.points > 0 ? "+" : ""}
                  {component.points}
                </span>
                <span className="text-muted">{component.detail}</span>
              </li>
            ))}
          </ul>
          <p className="mt-2 text-[11px] leading-relaxed text-faint">
            Total {priority.score}. The score ranks suggestions against each
            other — it is not a judgement about the task.
          </p>
        </div>
      )}
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// 3. Today's flow — open space stays open
// --------------------------------------------------------------------------- //
function Flow({ brief }: { brief: Brief }) {
  // Defaulted rather than assumed present. A brief that arrives without a
  // section should cost that section, not the whole page — the alternative is
  // one absent key white-screening the homepage, which is exactly what it did.
  const remaining = (brief.timeline ?? []).filter((item) => !item.past);
  const calendar = brief.sources?.calendar;

  return (
    <section aria-labelledby="flow-heading">
      <h2
        id="flow-heading"
        className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-muted"
      >
        Rest of the day
      </h2>
      {calendar?.trust !== "live" ? (
        <p className="text-[14px] leading-relaxed text-muted">
          {calendar?.note || "No calendar data."}
        </p>
      ) : remaining.length === 0 ? (
        <p className="text-[14px] leading-relaxed text-muted">
          Nothing else scheduled. The time is genuinely open.
        </p>
      ) : (
        <ul className="space-y-0">
          {remaining.map((item, i) => (
            <li
              key={item.id}
              className={`flex gap-3 py-2.5 ${i > 0 ? "border-t border-border" : ""}`}
            >
              <span className="tnum w-14 shrink-0 text-[13px] font-medium text-muted">
                {item.allDay ? "all day" : item.time}
              </span>
              <div className="min-w-0">
                <p className="text-[14px] text-text">{item.title}</p>
                {item.detail && <Meta>{item.detail}</Meta>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

// --------------------------------------------------------------------------- //
// 4. One insight, or none
// --------------------------------------------------------------------------- //
function Insight({ brief }: { brief: Brief }) {
  const insight = brief.insight as {
    title: string;
    body: string;
    confidence: string;
    evidence: Record<string, unknown>;
  };
  const [open, setOpen] = useState(false);

  return (
    <section aria-labelledby="insight-heading">
      <h2
        id="insight-heading"
        className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-muted"
      >
        Worth knowing
      </h2>
      <Card className="p-4" style={domainStyle("recovery")}>
        <p className="text-[14px] leading-relaxed text-text">{insight.body}</p>
        <button
          type="button"
          onClick={() => {
            if (!open) void briefApi.event("insight_viewed", undefined, insight.title);
            setOpen((v) => !v);
          }}
          aria-expanded={open}
          className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text"
        >
          <Info className="size-3.5" aria-hidden="true" />
          Evidence
        </button>
        {open && (
          <dl className="mt-2 space-y-1 border-t border-border pt-2 text-[12px]">
            {Object.entries(insight.evidence || {}).map(([key, value]) => (
              <div key={key} className="flex justify-between gap-3">
                <dt className="text-muted">{humanise(key)}</dt>
                <dd className="tnum text-text">{String(value)}</dd>
              </div>
            ))}
            <div className="flex justify-between gap-3">
              <dt className="text-muted">Confidence</dt>
              <dd className="text-text">{insight.confidence}</dd>
            </div>
          </dl>
        )}
      </Card>
    </section>
  );
}

function humanise(key: string): string {
  return key
    .replace(/([A-Z])/g, " $1")
    .replace(/^./, (c) => c.toUpperCase())
    .trim();
}

// --------------------------------------------------------------------------- //
// 5. Review — what replaces the overdue counter
// --------------------------------------------------------------------------- //
function Review({ brief }: { brief: Brief }) {
  const buckets = (brief.review?.buckets ?? []).filter((b) => b.count > 0);
  if (buckets.length === 0) return null;

  return (
    <section aria-labelledby="review-heading">
      <h2
        id="review-heading"
        className="mb-2 text-[13px] font-semibold uppercase tracking-wide text-muted"
      >
        Needs a decision
      </h2>
      {/* The reframing, in prose, before any counts. */}
      <p className="mb-3 max-w-[58ch] text-[14px] leading-relaxed text-text">
        {brief.review?.headline}
      </p>
      <ul className="space-y-1.5">
        {buckets.map((bucket) => (
          <li key={bucket.key} className="flex items-baseline gap-2.5">
            <span className="tnum w-8 shrink-0 text-right text-[15px] font-semibold text-text">
              {bucket.count}
            </span>
            <span className="shrink-0 text-[14px] text-text">{bucket.label}</span>
            <span className="min-w-0 flex-1 truncate text-[12px] text-faint">
              {bucket.note}
            </span>
          </li>
        ))}
      </ul>
      <Link
        href="/tasks"
        className="mt-3 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text"
      >
        Work through them
        <ChevronRight className="size-3.5" aria-hidden="true" />
      </Link>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// 6. Lately
// --------------------------------------------------------------------------- //
/**
 * Reads from training, the only stream currently producing data — task
 * completions stopped 14 days ago, so a progress section built on them would
 * be permanently empty or quietly misleading.
 */
function Progress() {
  const training = useApi<{ window: { sessions: number; volumeKg: number } }>(
    "/strength/home",
  );
  const data = training.data;
  if (!data || data.window.sessions === 0) return null;

  return (
    <section aria-labelledby="progress-heading">
      <h2
        id="progress-heading"
        className="mb-2.5 text-[13px] font-semibold uppercase tracking-wide text-muted"
      >
        Lately
      </h2>
      <p className="text-[14px] leading-relaxed text-text">
        {data.window.sessions} strength session
        {data.window.sessions === 1 ? "" : "s"} in the last four weeks,{" "}
        {Math.round(data.window.volumeKg).toLocaleString()} kg of working volume.
      </p>
      <Link
        href="/training/strength"
        className="mt-2 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text"
      >
        Training
        <ChevronRight className="size-3.5" aria-hidden="true" />
      </Link>
    </section>
  );
}

// --------------------------------------------------------------------------- //
// 7. Provenance — the quietest thing on the page
// --------------------------------------------------------------------------- //
function Provenance({ brief }: { brief: Brief }) {
  return (
    <footer className="border-t border-border pt-3">
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] text-faint">
        <Clock className="size-3" aria-hidden="true" />
        <span>
          Brief for {brief.day} ({brief.daypart}) · confidence {brief.confidence}
        </span>
        {brief.sourceDataAt && <span>· data to {brief.sourceDataAt.slice(0, 10)}</span>}
        <span>· rules v{brief.ruleVersion}</span>
        {brief.edited && <span>· edited by you</span>}
      </p>
    </footer>
  );
}
