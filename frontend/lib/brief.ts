/** Types for the composed daily brief (`GET /api/v2/brief`). */

import { sendJson } from "./api";

export type Daypart = "morning" | "afternoon" | "evening" | "night";

export type ScoreComponent = {
  key: string;
  label: string;
  points: number;
  detail: string;
};

export type Priority = {
  taskId: number;
  title: string;
  area: string;
  project: string;
  dueDate: string | null;
  nextAction: string;
  estimateMinutes: number | null;
  blocked: boolean;
  waitingFor: string;
  score: number;
  components: ScoreComponent[];
  /** The single most load-bearing reason, for the card. */
  why: string;
  /** Key of the component `why` describes, so the UI can avoid restating it. */
  whyKey: string;
  selectedBy: "you" | "orion";
  pinned: boolean;
};

export type BriefInsight = {
  id: string;
  title: string;
  body: string;
  tone: "good" | "watch" | "flat";
  domain: string;
  klass: string;
  confidence: string;
  evidence: Record<string, unknown>;
};

export type ReviewBucket = {
  key: string;
  label: string;
  count: number;
  note: string;
  examples: { taskId: number; title: string; area: string; dueDate: string | null }[];
};

export type SourceQuality = {
  domain: string;
  label: string;
  latestRecord: string | null;
  ageDays: number | null;
  count: number;
  trust: "live" | "stale" | "empty";
  note: string;
  /** The same fact as a fragment, for listing several sources together. */
  fact: string;
};

export type TimelineItem = {
  id: string;
  time: string;
  title: string;
  detail: string;
  kind: string;
  allDay: boolean;
  past: boolean;
};

export type Brief = {
  day: string;
  daypart: Daypart;
  stateSummary: string;
  focus: string;
  nextAction: string;
  priorities: Priority[];
  insight: BriefInsight | Record<string, never>;
  review: {
    total: number;
    headline: string;
    dominantProject: string | null;
    buckets: ReviewBucket[];
  };
  timeline: TimelineItem[];
  evidence: Record<string, unknown>;
  dataQuality: { domain: string; severity: string; message: string; fact: string }[];
  sources: Record<string, SourceQuality>;
  confidence: "high" | "medium" | "low";
  ruleVersion: string;
  sourceDataAt: string | null;
  edited?: boolean;
};

export const briefApi = {
  defer: (taskId: number, until?: string) =>
    sendJson<Brief>(`/brief/priorities/${taskId}/defer`, "POST", { until: until ?? null }),
  pin: (taskId: number) => sendJson<Brief>(`/brief/priorities/${taskId}/pin`, "POST"),
  complete: (taskId: number) =>
    sendJson<Brief>(`/brief/priorities/${taskId}/complete`, "POST"),
  event: (kind: string, taskId?: number, subject = "") =>
    sendJson<{ ok: true }>("/brief/events", "POST", { kind, taskId, subject }),
};

const DAYPART_LABEL: Record<Daypart, string> = {
  morning: "morning",
  afternoon: "afternoon",
  evening: "evening",
  night: "night",
};

/** "Saturday evening" — the brief's own daypart, not the browser's guess. */
export function dayHeading(day: string, daypart: Daypart): string {
  const date = new Date(`${day}T12:00:00`);
  const weekday = date.toLocaleDateString(undefined, { weekday: "long" });
  return `${weekday} ${DAYPART_LABEL[daypart]}`;
}

export function dueLabel(iso: string | null): string {
  if (!iso) return "";
  const due = new Date(`${iso}T12:00:00`);
  const today = new Date();
  today.setHours(12, 0, 0, 0);
  const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (days === 0) return "due today";
  if (days === 1) return "due tomorrow";
  if (days > 0) return `due in ${days} days`;
  if (days === -1) return "1 day past";
  return `${Math.abs(days)} days past`;
}
