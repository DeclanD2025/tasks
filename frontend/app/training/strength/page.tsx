"use client";

/**
 * Strength home.
 *
 * The screen's job is to answer "what am I doing today, and is it working?"
 * before anything else. Two decisions shape it:
 *
 * The **resume banner comes first** when a session is live. Anything else at
 * the top of a screen someone opened mid-workout is in the way.
 *
 * The **Apple Health notice is shown, not hidden.** There are 142 recorded gym
 * sessions with no exercise detail behind them. An empty dashboard next to that
 * history would be a lie of omission, so the page states plainly what those
 * sessions can and cannot contribute.
 */

import { ChevronRight, Dumbbell, Play, TriangleAlert, Trophy } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Loaded } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Button, Card, Meta, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import {
  type ActiveSession,
  type TrainingHome,
  formatVolume,
  strengthApi,
} from "@/lib/strength";
import { getJson } from "@/lib/api";

export default function StrengthHomePage() {
  const state = useApi<TrainingHome>("/strength/home");
  const [active, setActive] = useState<ActiveSession | null>(null);

  useEffect(() => {
    void getJson<{ session: ActiveSession | null }>("/strength/session/active")
      .then((payload) => setActive(payload.session))
      .catch(() => setActive(null));
  }, []);

  return (
    <Loaded state={state}>
      {(data) => <StrengthHome data={data} active={active} />}
    </Loaded>
  );
}

function StrengthHome({ data, active }: { data: TrainingHome; active: ActiveSession | null }) {
  const { window: recent, programme, lastSession, nextPlanned } = data;

  return (
    <Page
      title="Strength"
      eyebrow={
        programme
          ? `${programme.name}${programme.week ? ` · week ${programme.week} of ${programme.weeks}` : ""}`
          : "No active programme"
      }
      rail={
        <>
          <Card className="p-4">
            <SectionHeader title="Personal records" />
            {data.records.length ? (
              <ul className="space-y-2">
                {data.records.slice(0, 5).map((record, i) => (
                  <li key={i} className="flex items-start gap-2" style={domainStyle("strength")}>
                    <Trophy className="mt-0.5 size-3.5 shrink-0 domain-text" />
                    <div className="min-w-0">
                      <p className="truncate text-[13px] font-medium text-text">{record.exercise}</p>
                      <p className="text-[11px] text-muted">{record.label}</p>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-faint">
                No records yet. They appear once a lift beats a previous best — the first
                session of an exercise sets a baseline rather than a record.
              </p>
            )}
          </Card>

          <Card className="p-4">
            <SectionHeader title="Muscles trained" sub="Last 28 days" />
            {data.muscles.length ? (
              <ul className="space-y-1.5">
                {data.muscles.map((row) => (
                  <li key={row.muscle} className="flex items-baseline gap-2 text-[13px]">
                    <span className="flex-1 truncate text-text">{row.muscle}</span>
                    <span className="tnum text-[12px] text-muted">{row.directSets} direct</span>
                    {row.daysSince != null && (
                      <span className="tnum w-10 text-right text-[11px] text-faint">
                        {row.daysSince}d
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="text-[12px] text-faint">Nothing logged in this window.</p>
            )}
          </Card>
        </>
      }
    >
      {active && <ResumeBanner session={active} />}

      {!active && (
        <Card className="overflow-hidden" style={domainStyle("strength")}>
          <div className="domain-bar h-1 w-full" />
          <div className="p-4 sm:p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <span className="text-[11px] font-semibold uppercase tracking-wide domain-text">
                  {nextPlanned.length ? `Next · ${nextPlanned[0].label}` : "Nothing scheduled"}
                </span>
                <h2 className="mt-1 text-lg font-semibold tracking-tight text-text">
                  {nextPlanned.length ? nextPlanned[0].name : "Start a session"}
                </h2>
                {lastSession && (
                  <Meta className="mt-1 block">
                    Last session {lastSession.daysAgo === 0 ? "today" : `${lastSession.daysAgo} days ago`}
                    {lastSession.status !== "completed" && ` · ${lastSession.status}`}
                  </Meta>
                )}
              </div>
              <StartButton plannedSessionId={nextPlanned[0]?.id} />
            </div>
          </div>
        </Card>
      )}

      {/* 28-day window */}
      <Card className="p-4 sm:p-5">
        <SectionHeader
          title="Last 28 days"
          sub="Working sets only — warm-ups excluded"
          action={
            <Link href="/training/strength/analytics" className="text-[12px] font-medium text-muted hover:text-text">
              Analytics →
            </Link>
          }
        />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Sessions" value={String(recent.sessions)} />
          <Stat label="Volume" value={formatVolume(recent.volumeKg)} />
          <Stat label="Working sets" value={String(recent.workingSets)} />
          <Stat
            label="Hard sets"
            value={String(recent.hardSets)}
            note={
              recent.ratedSets < recent.workingSets
                ? `${recent.workingSets - recent.ratedSets} unrated`
                : undefined
            }
          />
        </div>
      </Card>

      {data.warnings.length > 0 && (
        <Card className="p-4">
          <SectionHeader title="Worth knowing" sub="Advisory — not rules" />
          <ul className="space-y-1.5">
            {data.warnings.map((warning) => (
              <li key={warning.code} className="flex items-start gap-2 text-[12px] text-muted">
                <TriangleAlert
                  className={`mt-0.5 size-3.5 shrink-0 ${
                    warning.severity === "warning" ? "text-text" : "text-faint"
                  }`}
                />
                {warning.message}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.proposals.length > 0 && (
        <Card className="p-4">
          <SectionHeader
            title="Waiting on you"
            sub="Progression proposals — nothing changes unless accepted"
          />
          <ul className="space-y-2">
            {data.proposals.map((row) => (
              <li key={row.id} className="rounded-md border border-border px-2.5 py-2">
                <p className="text-[13px] font-medium text-text">{row.exercise}</p>
                <p className="mt-0.5 text-[12px] text-muted">{row.reason}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.attention.length > 0 && (
        <Card className="p-4">
          <SectionHeader title="Needs attention" />
          <ul className="space-y-2">
            {data.attention.map((row) => (
              <li key={row.exerciseId} className="rounded-md border border-border px-2.5 py-2">
                <p className="text-[13px] font-medium text-text">{row.name}</p>
                <p className="mt-0.5 text-[12px] text-muted">{row.detail}</p>
              </li>
            ))}
          </ul>
        </Card>
      )}

      {data.importedSessions.count > 0 && (
        <Card className="p-4">
          <SectionHeader title="From Apple Health" />
          <p className="text-[13px] text-text">{data.importedSessions.note}</p>
          {data.importedSessions.firstRecorded && data.importedSessions.mostRecent && (
            <Meta className="mt-1 block">
              {data.importedSessions.firstRecorded} → {data.importedSessions.mostRecent}
            </Meta>
          )}
        </Card>
      )}

      {recent.sessions === 0 && data.importedSessions.count === 0 && (
        <EmptyState
          title="Nothing logged yet"
          body="Start a session and every set is recorded individually — that is what makes the analytics possible later."
          cta="Start a session"
          href="/training/strength/workout"
        />
      )}
    </Page>
  );
}

function ResumeBanner({ session }: { session: ActiveSession }) {
  return (
    <Card className="overflow-hidden" style={domainStyle("strength")}>
      <div className="domain-bar h-1 w-full" />
      <div className="flex flex-wrap items-center gap-3 p-4">
        <Dumbbell className="size-5 domain-text" />
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold text-text">{session.name} is in progress</p>
          <Meta>
            Started {new Date(session.startedAt).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
            {" · "}
            {session.exercises.reduce((n, e) => n + e.sets.length, 0)} sets logged
          </Meta>
        </div>
        <Button href="/training/strength/workout" variant="accent" domain="strength" size="md">
          Resume <ChevronRight className="size-4" />
        </Button>
      </div>
    </Card>
  );
}

function StartButton({ plannedSessionId }: { plannedSessionId?: number }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const start = async () => {
    setBusy(true);
    try {
      await strengthApi.startSession(plannedSessionId ? { plannedSessionId } : {});
      window.location.href = "/training/strength/workout";
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start");
      setBusy(false);
    }
  };

  return (
    <div className="text-right">
      <Button onClick={() => void start()} variant="accent" domain="strength" size="md" disabled={busy}>
        <Play className="size-4" /> {busy ? "Starting…" : "Start"}
      </Button>
      {error && <p className="mt-1 text-[11px] text-muted">{error}</p>}
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="tnum mt-0.5 text-[20px] font-semibold tracking-tight text-text">{value}</p>
      {note && <p className="text-[11px] text-faint">{note}</p>}
    </div>
  );
}
