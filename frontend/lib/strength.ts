/**
 * Strength client: types, API calls and the offline outbox.
 *
 * The outbox is the part worth reading. A phone in a basement gym loses signal
 * constantly, and the failure mode that matters is not "the request was slow" —
 * it is "the set the user logged is gone and they have already moved on to the
 * next one". So every set write is queued to localStorage first, applied to the
 * screen immediately, and drained in the background. The server deduplicates on
 * `clientKey`, which is what makes retrying safe rather than a way to
 * double-count a set.
 *
 * This is deliberately not a general offline framework. It queues one kind of
 * write, and anything it cannot replay it surfaces rather than discards.
 */

import { sendJson } from "./api";

// --------------------------------------------------------------------------- //
// Types — mirroring app/domains/strength/sessions.py
// --------------------------------------------------------------------------- //
export type SetType =
  | "warmup" | "working" | "top_set" | "backoff" | "amrap"
  | "drop" | "rest_pause" | "myo_rep" | "technique" | "test" | "failure";

export type LoggedSet = {
  id: number;
  setNumber: number;
  setType: SetType;
  weightKg: number | null;
  reps: number | null;
  durationSeconds: number | null;
  distanceM: number | null;
  assistanceKg: number | null;
  leftReps: number | null;
  rightReps: number | null;
  rpe: number | null;
  rir: number | null;
  restSeconds: number | null;
  toFailure: boolean;
  hasPartials: boolean;
  notes: string;
  completed: boolean;
  completedAt: string | null;
  voided: boolean;
  voidReason: string;
  edited: boolean;
  /** Client-only: this set is queued and not yet acknowledged by the server. */
  pending?: boolean;
};

export type PreviousPerformance = {
  date: string;
  daysAgo: number;
  sets: { weightKg: number | null; reps: number | null; rpe: number | null; setType: string }[];
};

export type Prescription = {
  targetSets?: number;
  targetReps?: number;
  repMin?: number | null;
  repMax?: number | null;
  targetWeightKg?: number | null;
  targetRpe?: number | null;
  restSeconds?: number | null;
  progressionRule?: string;
  notes?: string;
};

export type SessionExercise = {
  id: number;
  exerciseId: number;
  name: string;
  equipment: string;
  primaryMuscle: string;
  loadType: string;
  measurement: "reps" | "duration" | "distance";
  incrementKg: number;
  barWeightKg: number | null;
  section: string;
  supersetGroup: string | null;
  targetSets: number;
  targetReps: number;
  prescription: Prescription;
  substitutedFrom: number | null;
  substitutionReason: string;
  notes: string;
  sets: LoggedSet[];
  voidedSets: LoggedSet[];
  previous: PreviousPerformance | null;
};

export type ActiveSession = {
  id: number;
  name: string;
  status: string;
  startedAt: string;
  finishedAt: string | null;
  elapsedMinutes: number;
  location: string;
  bodyweightKg: number | null;
  readiness: Readiness;
  sessionRpe: number | null;
  notes: string;
  painNotes: string;
  defaultRestSeconds: number;
  exercises: SessionExercise[];
};

export type Readiness = {
  available: boolean;
  day?: string;
  ageDays?: number;
  sleepHours?: number | null;
  hrvMs?: number | null;
  restingHr?: number | null;
  weightKg?: number | null;
};

export type ExerciseSummary = {
  id: number;
  name: string;
  canonicalName: string;
  slug: string;
  familySlug: string;
  primaryMuscle: string;
  secondaryMuscles: string[];
  equipment: string;
  movementPattern: string;
  loadType: string;
  measurement: string;
  laterality: string;
  isCompound: boolean;
  incrementKg: number;
  barWeightKg: number | null;
  defaultSets: number;
  defaultReps: number;
  favorite: boolean;
  isCustom: boolean;
};

export type PersonalRecord = {
  id?: number;
  exercise: string;
  exerciseId: number;
  type: string;
  value: number;
  unit: string;
  qualifier: number | null;
  previous: number | null;
  method: string;
  achievedAt?: string;
  label: string;
};

export type Proposal = {
  id?: number;
  exercise?: string;
  rule: string;
  action: "increase" | "hold" | "reduce" | "deload" | "none";
  reason: string;
  nextWeightKg: number | null;
  nextReps: number | null;
  nextRepTarget: string;
  deltaKg: number | null;
  inputs: Record<string, unknown>;
  conclusive: boolean;
};

export type SessionSummary = {
  id: number;
  name: string;
  status: string;
  startedAt: string;
  durationMinutes: number;
  volumeKg: number;
  workingSets: number;
  hardSets: number;
  totalReps: number;
  sessionRpe: number | null;
  sessionLoad: number | null;
  readiness: Readiness;
  exercises: {
    name: string;
    exerciseId: number;
    workingSets: number;
    hardSets: number;
    volumeKg: number;
    topSetKg: number | null;
    bestE1rmKg: number | null;
    plannedSets: number;
  }[];
  dataQuality: string[];
  newRecords: PersonalRecord[];
  proposals?: Proposal[];
};

export type TrainingHome = {
  programme: { id: number; name: string; week: number | null; weeks: number } | null;
  lastSession: { id: number; name: string; day: string; daysAgo: number; status: string } | null;
  nextPlanned: {
    id: number; date: string; name: string; status: string;
    templateId: number | null; daysAway: number; label: string;
    rescheduledFrom: string | null; rescheduleReason: string;
  }[];
  window: VolumeSummary;
  muscles: MuscleRow[];
  warnings: { severity: string; code: string; message: string }[];
  records: PersonalRecord[];
  proposals: { id: number; exercise: string; rule: string; reason: string; proposal: Proposal }[];
  attention: { exerciseId: number; name: string; issue: string; detail: string }[];
  importedSessions: {
    count: number;
    mostRecent: string | null;
    firstRecorded: string | null;
    note: string;
  };
};

export type VolumeSummary = {
  volumeKg: number;
  workingSets: number;
  hardSets: number;
  reps: number;
  sessions: number;
  ratedSets: number;
};

/** One muscle in the 27-muscle detailed model. */
export type DetailedMuscleRow = {
  muscle: string;
  region: string;
  primarySets: number;
  secondarySets: number;
  stabiliserSets: number;
  weightedSets: number;
  /** Share of weighted sets — the programming currency. */
  sharePercent: number;
  /** Share of tonnage. Disagrees sharply with set share on heavy compounds,
   *  which is why both are shown rather than one being picked silently. */
  volumeSharePercent: number;
  volumeKg: number;
  sessions: number;
  lastTrained: string;
  daysSince: number;
  /** Only stabiliser work touched this muscle — it appears, but was not trained. */
  stabiliserOnly: boolean;
};

export type DetailedMuscles = {
  muscles: DetailedMuscleRow[];
  regions: {
    region: string;
    weightedSets: number;
    sharePercent: number;
    volumeKg: number;
    volumeSharePercent: number;
  }[];
  /** Muscles with no direct work in the window. The gap is often the finding. */
  untrained: string[];
  weighting: { primary: number; secondary: number; stabiliser: number };
  note: string;
};

export type MuscleRow = {
  muscle: string;
  directSets: number;
  indirectSets: number;
  volumeKg: number;
  sessions: number;
  lastTrained: string | null;
  daysSince: number | null;
};

export type Analytics = {
  windowDays: number;
  from: string;
  to: string;
  summary: VolumeSummary;
  allTime: VolumeSummary;
  byWeek: ({ period: string } & VolumeSummary)[];
  byExercise: { key: string; volumeKg: number; sets: number; hardSets: number; sessions: number }[];
  byMovement: { key: string; volumeKg: number; sets: number; hardSets: number; sessions: number }[];
  byMuscle: MuscleRow[];
  detailedMuscles: DetailedMuscles;
  balance: {
    pushSets: number; pullSets: number; pushPull: number | null;
    squatSets: number; hingeSets: number; squatHinge: number | null;
    upperSets: number; lowerSets: number; upperLower: number | null;
  };
  intensity: {
    averageLoadKg: number | null;
    averageRpe: number | null;
    ratedShare: number | null;
    repDistribution: Record<string, number>;
    rpeDistribution: Record<string, number>;
    failureSets: number;
    failureShare: number | null;
  };
  warnings: { severity: string; code: string; message: string }[];
  adherence: {
    plannedSessions: number; completedSessions: number; partialSessions: number;
    abandonedSessions: number; skippedSessions: number; rescheduledSessions: number;
    unplannedSessions: number; completionRate: number | null;
    rateAvailable: boolean; note: string;
  };
  associations: {
    input: string; outcome: string; available: boolean;
    observations: number; required?: number;
    coefficient?: number | null; direction?: string; strength?: string;
    from?: string | null; to?: string | null; missingRate?: number | null;
    note: string;
  }[];
  weighting: { primary: number; secondary: number };
};

// --------------------------------------------------------------------------- //
// API
// --------------------------------------------------------------------------- //
const BASE = "/strength";

export const strengthApi = {
  home: () => `${BASE}/home`,
  activeSession: () => `${BASE}/session/active`,
  analytics: (days: number) => `${BASE}/analytics?days=${days}`,
  exercises: (q: string) => `${BASE}/exercises?q=${encodeURIComponent(q)}`,
  exercise: (id: number) => `${BASE}/exercises/${id}`,
  templates: () => `${BASE}/templates`,
  history: () => `${BASE}/history`,

  startSession: (body: { templateId?: number; plannedSessionId?: number; name?: string }) =>
    sendJson<ActiveSession>(`${BASE}/session`, "POST", body),
  addExercise: (sessionId: number, exerciseId: number) =>
    sendJson<{ id: number; session: ActiveSession }>(
      `${BASE}/session/${sessionId}/exercises`, "POST", { exerciseId },
    ),
  substitute: (blockId: number, exerciseId: number, reason: string) =>
    sendJson<{ ok: true }>(`${BASE}/blocks/${blockId}/substitute`, "POST", { exerciseId, reason }),
  finish: (sessionId: number, body: { sessionRpe?: number | null; notes?: string; painNotes?: string }) =>
    sendJson<SessionSummary>(`${BASE}/session/${sessionId}/finish`, "POST", body),
  abandon: (sessionId: number, reason: string) =>
    sendJson<{ ok: true }>(`${BASE}/session/${sessionId}/abandon`, "POST", { reason }),
  discard: (sessionId: number) =>
    sendJson<{ ok: true }>(`${BASE}/session/${sessionId}`, "DELETE"),
  updateSet: (setId: number, body: Record<string, unknown>) =>
    sendJson<LoggedSet>(`${BASE}/sets/${setId}`, "PATCH", body),
  voidSet: (setId: number, reason: string) =>
    sendJson<{ ok: true }>(`${BASE}/sets/${setId}?reason=${encodeURIComponent(reason)}`, "DELETE"),
  decideProposal: (eventId: number, accepted: boolean) =>
    sendJson<{ ok: true }>(`${BASE}/proposals/${eventId}`, "POST", { accepted }),
};

// --------------------------------------------------------------------------- //
// Offline outbox
// --------------------------------------------------------------------------- //
export type QueuedSet = {
  clientKey: string;
  blockId: number;
  body: Record<string, unknown>;
  queuedAt: number;
  attempts: number;
};

const OUTBOX_KEY = "orion.strength.outbox.v1";

function readOutbox(): QueuedSet[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = window.localStorage.getItem(OUTBOX_KEY);
    return raw ? (JSON.parse(raw) as QueuedSet[]) : [];
  } catch {
    // A corrupt outbox must not brick the tracker. Losing the queue is bad;
    // being unable to open the page at all is worse.
    return [];
  }
}

function writeOutbox(items: QueuedSet[]): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(OUTBOX_KEY, JSON.stringify(items));
  } catch {
    /* storage full or blocked — the in-flight request is still the real path */
  }
}

/** Mint an idempotency key. The server dedupes on this, so a retry is free. */
export function mintClientKey(): string {
  const random = typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `set-${random}`;
}

export function enqueueSet(item: Omit<QueuedSet, "queuedAt" | "attempts">): void {
  const outbox = readOutbox();
  outbox.push({ ...item, queuedAt: Date.now(), attempts: 0 });
  writeOutbox(outbox);
}

export function dequeueSet(clientKey: string): void {
  writeOutbox(readOutbox().filter((item) => item.clientKey !== clientKey));
}

export function pendingSets(): QueuedSet[] {
  return readOutbox();
}

/**
 * Try to send everything queued. Returns how many are still outstanding.
 *
 * Failures stay queued and their attempt count rises — nothing is dropped on
 * the floor, because a silently discarded set is exactly the outcome the whole
 * mechanism exists to prevent.
 */
export async function drainOutbox(): Promise<{ sent: number; remaining: number }> {
  const outbox = readOutbox();
  if (outbox.length === 0) return { sent: 0, remaining: 0 };

  let sent = 0;
  const survivors: QueuedSet[] = [];

  for (const item of outbox) {
    try {
      await sendJson<LoggedSet>(
        `${BASE}/blocks/${item.blockId}/sets`, "POST",
        { ...item.body, clientKey: item.clientKey },
      );
      sent += 1;
    } catch {
      survivors.push({ ...item, attempts: item.attempts + 1 });
    }
  }

  writeOutbox(survivors);
  return { sent, remaining: survivors.length };
}

// --------------------------------------------------------------------------- //
// Formatting
// --------------------------------------------------------------------------- //
export function formatWeight(kg: number | null | undefined): string {
  if (kg === null || kg === undefined) return "—";
  return Number.isInteger(kg) ? `${kg}` : kg.toFixed(1);
}

export function formatVolume(kg: number): string {
  if (kg >= 1000) return `${(kg / 1000).toFixed(1)}t`;
  return `${Math.round(kg)} kg`;
}

/** "3×8 @ 60 kg" — the prescription in the shorthand lifters actually use. */
export function describePrescription(p: Prescription, fallbackSets: number, fallbackReps: number): string {
  const sets = p.targetSets ?? fallbackSets;
  const reps = p.repMin && p.repMax && p.repMin !== p.repMax
    ? `${p.repMin}–${p.repMax}`
    : `${p.targetReps ?? fallbackReps}`;
  const load = p.targetWeightKg ? ` @ ${formatWeight(p.targetWeightKg)} kg` : "";
  const rpe = p.targetRpe ? ` · RPE ${p.targetRpe}` : "";
  return `${sets}×${reps}${load}${rpe}`;
}

/**
 * Plate loading per side, mirroring calc.plates_for.
 *
 * Duplicated in the client on purpose: the plate calculator has to answer
 * instantly between sets, and a round trip to work out that 100 kg is two
 * twenties a side is a round trip too many. The server keeps the canonical
 * implementation for anything that gets stored.
 */
const PLATES = [25, 20, 15, 10, 5, 2.5, 1.25];

export function platesPerSide(targetKg: number, barKg: number): { plates: number[]; exact: boolean; achieved: number } {
  if (targetKg < barKg) return { plates: [], exact: targetKg === barKg, achieved: barKg };
  let remaining = (targetKg - barKg) / 2;
  const plates: number[] = [];
  for (const plate of PLATES) {
    while (remaining >= plate - 1e-9) {
      plates.push(plate);
      remaining -= plate;
    }
  }
  const achieved = barKg + 2 * plates.reduce((a, b) => a + b, 0);
  return { plates, exact: Math.abs(achieved - targetKg) < 1e-6, achieved };
}
