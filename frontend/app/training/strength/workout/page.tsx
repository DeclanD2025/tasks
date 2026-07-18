"use client";

/**
 * The active workout tracker.
 *
 * This is the one ORION screen used standing up, one-handed, mid-set, on bad
 * wifi. Everything about it is shaped by that:
 *
 * - **One exercise fills the screen.** Scrolling a list of twelve movements to
 *   find the one in front of you is the wrong interaction at 85% of a 5RM.
 * - **The previous session sits directly above the input.** It is what today
 *   is being judged against, so it should not require a tap to see.
 * - **Logging a set is one tap.** Weight and reps are prefilled from the plan,
 *   or from the last set, or from last week — in that order.
 * - **Writes are optimistic and queued.** The set appears immediately and is
 *   drained to the server in the background, deduplicated on a client key. A
 *   dropped connection costs a retry, never a set.
 * - **Nothing is destructive.** Correcting a set keeps what it said; removing
 *   one voids it rather than deleting it.
 */

import {
  ArrowLeft, ArrowRight, Check, Loader2, Minus, Plus,
  RotateCcw, Timer, TriangleAlert, X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { Page } from "@/components/shell";
import { Button, Card, Chip, Meta, SectionHeader } from "@/components/ui";
import { domainStyle } from "@/lib/domains";
import {
  type ActiveSession,
  type LoggedSet,
  type SessionExercise,
  type SessionSummary,
  describePrescription,
  drainOutbox,
  enqueueSet,
  formatWeight,
  mintClientKey,
  pendingSets,
  platesPerSide,
  strengthApi,
} from "@/lib/strength";
import { getJson } from "@/lib/api";

export default function WorkoutPage() {
  const router = useRouter();
  const [session, setSession] = useState<ActiveSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<SessionSummary | null>(null);

  // Promise callbacks rather than async/await: state is set from the callback,
  // not synchronously in the effect body, which is both what React recommends
  // and what `useApi` next door already does.
  const load = useCallback(
    () =>
      getJson<{ session: ActiveSession | null }>("/strength/session/active")
        .then((payload) => {
          setSession(payload.session);
          setError(null);
        })
        .catch((err: unknown) => {
          setError(err instanceof Error ? err.message : "Could not reach ORION");
        })
        .finally(() => setLoading(false)),
    [],
  );

  useEffect(() => {
    void load();
  }, [load]);

  if (loading) {
    return (
      <Page title="Workout">
        <Card className="p-8 text-center">
          <Loader2 className="mx-auto size-5 animate-spin text-muted" />
        </Card>
      </Page>
    );
  }

  if (summary) return <SessionReview summary={summary} onDone={() => router.push("/training/strength")} />;

  if (error) {
    return (
      <Page title="Workout">
        <Card className="p-6">
          <p className="text-[14px] text-text">{error}</p>
          <Button onClick={() => void load()} variant="ghost" size="sm" className="mt-3">
            <RotateCcw className="size-4" /> Try again
          </Button>
        </Card>
      </Page>
    );
  }

  if (!session) {
    return (
      <Page title="Workout">
        <Card className="p-6 text-center">
          <p className="text-[15px] font-medium text-text">No workout in progress</p>
          <p className="mt-1 text-[13px] text-muted">
            Start one from the strength home and it will appear here.
          </p>
          <Button href="/training/strength" variant="accent" domain="strength" size="md" className="mt-4">
            Go to strength
          </Button>
        </Card>
      </Page>
    );
  }

  return <Tracker session={session} onRefresh={load} onFinished={setSummary} />;
}

// --------------------------------------------------------------------------- //
// Tracker
// --------------------------------------------------------------------------- //
function Tracker({
  session,
  onRefresh,
  onFinished,
}: {
  session: ActiveSession;
  onRefresh: () => Promise<void>;
  onFinished: (summary: SessionSummary) => void;
}) {
  const [index, setIndex] = useState(0);
  const [local, setLocal] = useState<ActiveSession>(session);
  const [queued, setQueued] = useState(() => pendingSets().length);
  const [finishing, setFinishing] = useState(false);
  const [restEndsAt, setRestEndsAt] = useState<number | null>(null);

  // Adjust-during-render rather than a syncing effect: when a server refresh
  // brings a new session object, local state should already reflect it on this
  // paint, not one render later. React re-runs the component immediately and
  // discards the abandoned output, so nothing flashes.
  // https://react.dev/reference/react/useState#storing-information-from-previous-renders
  const [seenSession, setSeenSession] = useState(session);
  if (seenSession !== session) {
    setSeenSession(session);
    setLocal(session);
  }

  // Drain the outbox on mount, whenever the browser says it is back online,
  // and on a slow timer as a backstop for the times it does not say.
  useEffect(() => {
    let cancelled = false;
    const flush = async () => {
      const { remaining } = await drainOutbox();
      if (!cancelled) setQueued(remaining);
    };
    void flush();
    const timer = setInterval(flush, 15_000);
    window.addEventListener("online", flush);
    return () => {
      cancelled = true;
      clearInterval(timer);
      window.removeEventListener("online", flush);
    };
  }, []);

  const exercises = local.exercises;
  const current = exercises[index];
  const remaining = exercises.length - index - 1;

  const applyLocalSet = useCallback((blockId: number, set: LoggedSet) => {
    setLocal((prev) => ({
      ...prev,
      exercises: prev.exercises.map((block) =>
        block.id === blockId ? { ...block, sets: [...block.sets, set] } : block,
      ),
    }));
  }, []);

  const replaceLocalSets = useCallback((blockId: number, sets: LoggedSet[]) => {
    setLocal((prev) => ({
      ...prev,
      exercises: prev.exercises.map((block) =>
        block.id === blockId ? { ...block, sets } : block,
      ),
    }));
  }, []);

  const finish = async (sessionRpe: number | null) => {
    setFinishing(true);
    // Flush anything queued before finishing, or the summary would be computed
    // without sets the user has already logged.
    await drainOutbox();
    try {
      const result = await strengthApi.finish(local.id, { sessionRpe });
      onFinished(result);
    } catch {
      setFinishing(false);
    }
  };

  return (
    <Page
      title={local.name}
      eyebrow={`In progress · ${Math.round(local.elapsedMinutes)} min`}
    >
      <SessionBar
        session={local}
        queued={queued}
        restEndsAt={restEndsAt}
        onClearRest={() => setRestEndsAt(null)}
      />

      {current ? (
        <ExerciseCard
          key={current.id}
          block={current}
          onLogged={(set) => {
            applyLocalSet(current.id, set);
            setQueued(pendingSets().length);
            const rest = current.prescription.restSeconds ?? local.defaultRestSeconds;
            if (rest) setRestEndsAt(Date.now() + rest * 1000);
          }}
          onSetsChanged={(sets) => replaceLocalSets(current.id, sets)}
          onRefresh={onRefresh}
        />
      ) : (
        <Card className="p-6 text-center">
          <p className="text-[14px] text-muted">No exercises in this session yet.</p>
        </Card>
      )}

      <div className="flex items-center justify-between gap-2">
        <Button
          variant="ghost"
          size="md"
          onClick={() => setIndex((i) => Math.max(0, i - 1))}
          disabled={index === 0}
        >
          <ArrowLeft className="size-4" /> Previous
        </Button>
        <Meta>
          {index + 1} of {exercises.length}
          {remaining > 0 ? ` · ${remaining} to go` : " · last exercise"}
        </Meta>
        <Button
          variant="ghost"
          size="md"
          onClick={() => setIndex((i) => Math.min(exercises.length - 1, i + 1))}
          disabled={index >= exercises.length - 1}
        >
          Next <ArrowRight className="size-4" />
        </Button>
      </div>

      <UpNext exercises={exercises} index={index} onJump={setIndex} />

      <FinishCard finishing={finishing} onFinish={finish} />
    </Page>
  );
}

// --------------------------------------------------------------------------- //
// Session bar: elapsed, sync state, rest timer
// --------------------------------------------------------------------------- //
function SessionBar({
  session,
  queued,
  restEndsAt,
  onClearRest,
}: {
  session: ActiveSession;
  queued: number;
  restEndsAt: number | null;
  onClearRest: () => void;
}) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);

  const restLeft = restEndsAt ? Math.max(0, Math.ceil((restEndsAt - now) / 1000)) : null;
  const started = new Date(session.startedAt).getTime();
  const elapsed = Math.floor((now - started) / 1000);

  return (
    <Card className="p-3" style={domainStyle("strength")}>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <div className="flex items-baseline gap-1.5">
          <span className="tnum text-[20px] font-semibold tracking-tight text-text">
            {formatClock(elapsed)}
          </span>
          <Meta>elapsed</Meta>
        </div>

        {restLeft !== null && restLeft > 0 && (
          <button
            type="button"
            onClick={onClearRest}
            className="flex items-center gap-1.5 rounded-full border border-border-strong bg-surface-2 px-2.5 py-1"
          >
            <Timer className="size-3.5 domain-text" />
            <span className="tnum text-[13px] font-semibold text-text">{formatClock(restLeft)}</span>
            <span className="text-[11px] text-muted">rest</span>
          </button>
        )}

        <div className="ml-auto flex items-center gap-2">
          {queued > 0 ? (
            <Chip>
              <Loader2 className="mr-1 inline size-3 animate-spin" />
              {queued} set{queued === 1 ? "" : "s"} syncing
            </Chip>
          ) : (
            <Chip>Saved</Chip>
          )}
        </div>
      </div>

      {session.readiness?.available && (
        <p className="mt-2 text-[11px] text-faint">
          {session.readiness.sleepHours != null && `${session.readiness.sleepHours}h sleep`}
          {session.readiness.hrvMs != null && ` · HRV ${Math.round(session.readiness.hrvMs)}ms`}
          {session.bodyweightKg != null && ` · ${formatWeight(session.bodyweightKg)} kg bodyweight`}
          {(session.readiness.ageDays ?? 0) > 1 && ` · reading is ${session.readiness.ageDays} days old`}
        </p>
      )}
    </Card>
  );
}

function formatClock(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

// --------------------------------------------------------------------------- //
// One exercise
// --------------------------------------------------------------------------- //
function ExerciseCard({
  block,
  onLogged,
  onSetsChanged,
  onRefresh,
}: {
  block: SessionExercise;
  onLogged: (set: LoggedSet) => void;
  onSetsChanged: (sets: LoggedSet[]) => void;
  onRefresh: () => Promise<void>;
}) {
  const prefill = usePrefill(block);
  const [weight, setWeight] = useState<string>(prefill.weight);
  const [reps, setReps] = useState<string>(prefill.reps);
  const [rpe, setRpe] = useState<string>("");
  const [setType, setSetType] = useState<"warmup" | "working">("working");
  const [showPlates, setShowPlates] = useState(false);

  // Re-prefill when the previous set changes, without an effect. The user's
  // own typing wins until they log — at which point the new "last set" becomes
  // the basis for the next one, which is the behaviour they expect.
  const [seenPrefill, setSeenPrefill] = useState(prefill);
  if (seenPrefill.weight !== prefill.weight || seenPrefill.reps !== prefill.reps) {
    setSeenPrefill(prefill);
    setWeight(prefill.weight);
    setReps(prefill.reps);
  }

  const done = block.sets.length;
  const target = block.prescription.targetSets ?? block.targetSets;

  const log = () => {
    const clientKey = mintClientKey();
    const body: Record<string, unknown> = {
      weightKg: weight === "" ? null : Number(weight),
      reps: reps === "" ? null : Number(reps),
      rpe: rpe === "" ? null : Number(rpe),
      setType,
    };

    // Optimistic: the set appears now. `pending` marks it as unacknowledged so
    // the UI can be honest about what has actually reached the server.
    onLogged({
      id: -Date.now(),
      setNumber: done + 1,
      setType,
      weightKg: body.weightKg as number | null,
      reps: body.reps as number | null,
      durationSeconds: null, distanceM: null, assistanceKg: null,
      leftReps: null, rightReps: null,
      rpe: body.rpe as number | null,
      rir: rpe === "" ? null : 10 - Number(rpe),
      restSeconds: null, toFailure: false, hasPartials: false,
      notes: "", completed: true, completedAt: new Date().toISOString(),
      voided: false, voidReason: "", edited: false, pending: true,
    });

    enqueueSet({ clientKey, blockId: block.id, body });
    void drainOutbox().then(() => void onRefresh());
    setRpe("");
  };

  const barKg = block.barWeightKg;
  const numericWeight = weight === "" ? null : Number(weight);

  return (
    <Card className="overflow-hidden" style={domainStyle("strength")}>
      <div className="domain-bar h-1 w-full" />
      <div className="p-4 sm:p-5">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="min-w-0">
            <h2 className="text-[19px] font-semibold tracking-tight text-text">{block.name}</h2>
            <p className="mt-0.5 text-[12px] text-muted">
              {describePrescription(block.prescription, block.targetSets, block.targetReps)}
              {block.equipment ? ` · ${block.equipment}` : ""}
            </p>
          </div>
          <Chip>{done} / {target} sets</Chip>
        </div>

        {block.substitutionReason && (
          <p className="mt-2 rounded-md border border-border bg-surface-2 px-2 py-1 text-[11px] text-muted">
            Substituted — {block.substitutionReason}
          </p>
        )}

        <PreviousBlock block={block} />

        {/* Entry */}
        <div className="mt-4 grid grid-cols-3 gap-2">
          <NumberField
            label={block.loadType === "bodyweight" ? "Added kg" : "Weight kg"}
            value={weight}
            onChange={setWeight}
            step={block.incrementKg}
          />
          <NumberField label="Reps" value={reps} onChange={setReps} step={1} />
          <NumberField label="RPE" value={rpe} onChange={setRpe} step={0.5} placeholder="—" />
        </div>

        <div className="mt-2 flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setSetType(setType === "working" ? "warmup" : "working")}
            className={`rounded-full border px-2.5 py-1 text-[11px] font-medium ${
              setType === "warmup"
                ? "border-border-strong bg-surface-2 text-muted"
                : "border-border text-text"
            }`}
          >
            {setType === "warmup" ? "Warm-up set" : "Working set"}
          </button>
          {barKg != null && numericWeight != null && numericWeight > 0 && (
            <button
              type="button"
              onClick={() => setShowPlates((v) => !v)}
              className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted"
            >
              {showPlates ? "Hide plates" : "Plates"}
            </button>
          )}
        </div>

        {showPlates && barKg != null && numericWeight != null && (
          <PlateHint targetKg={numericWeight} barKg={barKg} />
        )}

        <Button
          onClick={log}
          variant="accent"
          domain="strength"
          size="lg"
          className="mt-3 w-full"
          disabled={reps === "" && weight === ""}
        >
          <Check className="size-4" /> Log set {done + 1}
        </Button>

        <SetList sets={block.sets} onChanged={onSetsChanged} allSets={block.sets} onRefresh={onRefresh} />
      </div>
    </Card>
  );
}

/**
 * What to put in the inputs before the user types.
 *
 * Order matters and is deliberate: the plan first (it is what was decided when
 * the user was thinking clearly), then the last set actually performed, then
 * last week's session. The plan is never overwritten by history — a
 * prescription is an instruction, not a suggestion to be averaged away.
 */
function usePrefill(block: SessionExercise): { weight: string; reps: string } {
  return useMemo(() => {
    const lastLogged = block.sets.filter((s) => !s.voided).at(-1);
    if (lastLogged) {
      return {
        weight: lastLogged.weightKg != null ? String(lastLogged.weightKg) : "",
        reps: lastLogged.reps != null ? String(lastLogged.reps) : "",
      };
    }
    const planned = block.prescription;
    if (planned.targetWeightKg != null) {
      return {
        weight: String(planned.targetWeightKg),
        reps: String(planned.repMin ?? planned.targetReps ?? block.targetReps),
      };
    }
    const previous = block.previous?.sets?.[0];
    if (previous) {
      return {
        weight: previous.weightKg != null ? String(previous.weightKg) : "",
        reps: previous.reps != null ? String(previous.reps) : String(block.targetReps),
      };
    }
    return { weight: "", reps: String(block.targetReps) };
  }, [block]);
}

function PreviousBlock({ block }: { block: SessionExercise }) {
  if (!block.previous) {
    return (
      <p className="mt-3 rounded-md border border-dashed border-border px-2.5 py-2 text-[12px] text-faint">
        First time logging this exercise — nothing to compare against yet.
      </p>
    );
  }
  const { previous } = block;
  return (
    <div className="mt-3 rounded-md border border-border bg-surface-2 px-2.5 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
        Last time · {previous.daysAgo === 0 ? "today" : `${previous.daysAgo}d ago`}
      </p>
      <p className="mt-1 text-[13px] text-text">
        {previous.sets.length === 0
          ? "No working sets recorded."
          : previous.sets
              .map((s) => `${formatWeight(s.weightKg)}×${s.reps ?? "—"}${s.rpe ? ` @${s.rpe}` : ""}`)
              .join("   ")}
      </p>
    </div>
  );
}

function PlateHint({ targetKg, barKg }: { targetKg: number; barKg: number }) {
  const { plates, exact, achieved } = platesPerSide(targetKg, barKg);
  return (
    <div className="mt-2 rounded-md border border-border bg-surface-2 px-2.5 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
        Per side · {barKg} kg bar
      </p>
      <p className="mt-1 text-[13px] text-text">
        {plates.length === 0 ? "Empty bar" : plates.map((p) => `${p}`).join(" + ")}
      </p>
      {!exact && (
        <p className="mt-1 text-[11px] text-muted">
          Closest loadable weight is {achieved} kg.
        </p>
      )}
    </div>
  );
}

function NumberField({
  label,
  value,
  onChange,
  step,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  step: number;
  placeholder?: string;
}) {
  const nudge = (direction: 1 | -1) => {
    const current = value === "" ? 0 : Number(value);
    const next = Math.max(0, Math.round((current + direction * step) * 100) / 100);
    onChange(String(next));
  };

  return (
    <div>
      <label className="mb-1 block text-[10px] font-semibold uppercase tracking-wide text-muted">
        {label}
      </label>
      <div className="flex items-stretch overflow-hidden rounded-lg border border-border bg-surface">
        <button
          type="button"
          onClick={() => nudge(-1)}
          aria-label={`Decrease ${label}`}
          className="px-2 text-muted hover:text-text"
        >
          <Minus className="size-3.5" />
        </button>
        <input
          // `inputMode="decimal"` gets the numeric keypad on iOS without the
          // spinner arrows a number input adds on desktop.
          inputMode="decimal"
          value={value}
          placeholder={placeholder ?? "0"}
          onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))}
          className="tnum min-w-0 flex-1 bg-transparent py-2 text-center text-[17px] font-semibold text-text outline-none"
        />
        <button
          type="button"
          onClick={() => nudge(1)}
          aria-label={`Increase ${label}`}
          className="px-2 text-muted hover:text-text"
        >
          <Plus className="size-3.5" />
        </button>
      </div>
    </div>
  );
}

function SetList({
  sets,
  onChanged,
  allSets,
  onRefresh,
}: {
  sets: LoggedSet[];
  onChanged: (sets: LoggedSet[]) => void;
  allSets: LoggedSet[];
  onRefresh: () => Promise<void>;
}) {
  if (sets.length === 0) {
    return <p className="mt-3 text-[12px] text-faint">No sets logged yet.</p>;
  }

  const remove = async (set: LoggedSet) => {
    onChanged(allSets.filter((s) => s.id !== set.id));
    if (set.id > 0) {
      await strengthApi.voidSet(set.id, "removed during session");
      await onRefresh();
    }
  };

  return (
    <ul className="mt-3 space-y-1.5">
      {sets.map((set) => (
        <li
          key={set.id}
          className="flex items-center gap-2 rounded-md border border-border px-2.5 py-1.5"
        >
          <span className="tnum w-5 text-[11px] text-faint">{set.setNumber}</span>
          <span className="tnum flex-1 text-[14px] font-medium text-text">
            {formatWeight(set.weightKg)} kg × {set.reps ?? "—"}
            {set.rpe != null && <span className="ml-1.5 text-[12px] text-muted">@{set.rpe}</span>}
          </span>
          {set.setType === "warmup" && <Chip>warm-up</Chip>}
          {set.pending && <Loader2 className="size-3.5 animate-spin text-faint" />}
          <button
            type="button"
            onClick={() => void remove(set)}
            aria-label={`Remove set ${set.setNumber}`}
            className="text-faint hover:text-text"
          >
            <X className="size-3.5" />
          </button>
        </li>
      ))}
    </ul>
  );
}

function UpNext({
  exercises,
  index,
  onJump,
}: {
  exercises: SessionExercise[];
  index: number;
  onJump: (i: number) => void;
}) {
  return (
    <Card className="p-4">
      <SectionHeader title="Session" sub={`${exercises.length} exercises`} />
      <ul className="space-y-1">
        {exercises.map((block, i) => {
          const done = block.sets.length;
          const target = block.prescription.targetSets ?? block.targetSets;
          const complete = done >= target && target > 0;
          return (
            <li key={block.id}>
              <button
                type="button"
                onClick={() => onJump(i)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${
                  i === index ? "bg-surface-2" : ""
                }`}
              >
                <span className={`size-1.5 shrink-0 rounded-full ${complete ? "bg-[var(--domain)]" : "bg-border-strong"}`} />
                <span className={`flex-1 truncate text-[13px] ${i === index ? "font-medium text-text" : "text-muted"}`}>
                  {block.name}
                </span>
                <span className="tnum text-[11px] text-faint">{done}/{target}</span>
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

function FinishCard({
  finishing,
  onFinish,
}: {
  finishing: boolean;
  onFinish: (sessionRpe: number | null) => Promise<void>;
}) {
  const [rpe, setRpe] = useState<string>("");
  return (
    <Card className="p-4">
      <SectionHeader
        title="Finish session"
        sub="Session RPE is optional, but without it this session sits out of internal-load trends."
      />
      <div className="flex items-end gap-2">
        <div className="w-28">
          <NumberField label="Session RPE" value={rpe} onChange={setRpe} step={0.5} placeholder="—" />
        </div>
        <Button
          onClick={() => void onFinish(rpe === "" ? null : Number(rpe))}
          variant="accent"
          domain="strength"
          size="md"
          className="flex-1"
          disabled={finishing}
        >
          {finishing ? <Loader2 className="size-4 animate-spin" /> : <Check className="size-4" />}
          Finish
        </Button>
      </div>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Review
// --------------------------------------------------------------------------- //
function SessionReview({ summary, onDone }: { summary: SessionSummary; onDone: () => void }) {
  return (
    <Page title="Session complete" eyebrow={summary.name}>
      <Card className="p-4 sm:p-5" style={domainStyle("strength")}>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="Volume" value={`${Math.round(summary.volumeKg).toLocaleString()} kg`} />
          <Stat label="Working sets" value={String(summary.workingSets)} />
          <Stat label="Hard sets" value={String(summary.hardSets)} />
          <Stat label="Duration" value={`${Math.round(summary.durationMinutes)} min`} />
        </div>
        {summary.status !== "completed" && (
          <p className="mt-3 rounded-md border border-border bg-surface-2 px-2.5 py-2 text-[12px] text-muted">
            Recorded as <strong className="text-text">{summary.status}</strong> — not every
            planned exercise was trained. That distinction is kept so adherence stays honest.
          </p>
        )}
      </Card>

      {summary.newRecords.length > 0 && (
        <Card className="p-4">
          <SectionHeader title="Personal records" sub="Only records that beat something previous" />
          <ul className="space-y-2">
            {summary.newRecords.map((record, i) => (
              <li key={i} className="rounded-md border border-border px-2.5 py-2">
                <p className="text-[13px] font-medium text-text">
                  {record.exercise} — {record.label}
                </p>
                {record.previous != null && (
                  <p className="text-[11px] text-muted">Previous best {formatWeight(record.previous)}</p>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      {summary.proposals && summary.proposals.length > 0 && (
        <Card className="p-4">
          <SectionHeader
            title="Suggested for next time"
            sub="Rule-based proposals. Nothing changes unless you accept it."
          />
          <ul className="space-y-2">
            {summary.proposals.map((proposal) => (
              <ProposalRow key={proposal.id} proposal={proposal} />
            ))}
          </ul>
        </Card>
      )}

      <Card className="p-4">
        <SectionHeader title="What was trained" />
        <ul className="space-y-1.5">
          {summary.exercises.map((exercise) => (
            <li key={exercise.exerciseId} className="flex items-center gap-2 text-[13px]">
              <span className="flex-1 truncate text-text">{exercise.name}</span>
              <span className="tnum text-[12px] text-muted">
                {exercise.workingSets}/{exercise.plannedSets} sets
              </span>
              <span className="tnum w-20 text-right text-[12px] text-muted">
                {Math.round(exercise.volumeKg).toLocaleString()} kg
              </span>
            </li>
          ))}
        </ul>
      </Card>

      {summary.dataQuality.length > 0 && (
        <Card className="p-4">
          <SectionHeader title="Data quality" sub="What this session cannot tell you" />
          <ul className="space-y-1">
            {summary.dataQuality.map((note, i) => (
              <li key={i} className="flex items-start gap-2 text-[12px] text-muted">
                <TriangleAlert className="mt-0.5 size-3.5 shrink-0 text-faint" />
                {note}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Button onClick={onDone} variant="accent" domain="strength" size="lg" className="w-full">
        Done
      </Button>
    </Page>
  );
}

function ProposalRow({ proposal }: { proposal: SessionSummary["proposals"] extends (infer T)[] | undefined ? T : never }) {
  const [decided, setDecided] = useState<"accepted" | "rejected" | null>(null);

  return (
    <li className="rounded-md border border-border px-2.5 py-2">
      <p className="text-[13px] font-medium text-text">
        {proposal.exercise}
        {proposal.nextWeightKg != null && ` → ${formatWeight(proposal.nextWeightKg)} kg`}
      </p>
      <p className="mt-0.5 text-[12px] text-muted">{proposal.reason}</p>
      <Meta className="mt-1 block">Rule: {proposal.rule.replace(/_/g, " ")}</Meta>
      {decided ? (
        <p className="mt-1.5 text-[11px] text-faint">
          {decided === "accepted" ? "Accepted" : "Rejected — kept as-is"}
        </p>
      ) : (
        <div className="mt-2 flex gap-2">
          <Button
            size="sm"
            variant="accent"
            domain="strength"
            onClick={() => {
              if (proposal.id) void strengthApi.decideProposal(proposal.id, true);
              setDecided("accepted");
            }}
          >
            Accept
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => {
              if (proposal.id) void strengthApi.decideProposal(proposal.id, false);
              setDecided("rejected");
            }}
          >
            Not this time
          </Button>
        </div>
      )}
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="tnum mt-0.5 text-[20px] font-semibold tracking-tight text-text">{value}</p>
    </div>
  );
}
