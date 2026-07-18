import type { DomainKey } from "./domains";

export type Trend = "up" | "down" | "flat";
export type Quality = "measured" | "calculated" | "estimated" | "missing";
export type Confidence = "high" | "medium" | "low";

/** A daily point in a metric series. */
export type SeriesPoint = { day: string; value: number };

export type BaselineCoverage = { used: number; of: number };

/** Mirrors metric_details.get_metric_detail() (audit §3). */
export type MetricDetail = {
  kind: string;
  title: string;
  unit: string;
  domain: DomainKey;
  latest: number | null;
  displayValue: string;
  trend: Trend;
  quality: Quality;
  series: SeriesPoint[];
  baseline7: number | null;
  baseline30: number | null;
  /** What each baseline was drawn from — days the device was actually worn,
   *  out of the days in the window. A baseline from 3 of 7 is a weaker claim. */
  coverage7: BaselineCoverage | null;
  coverage30: BaselineCoverage | null;
  band: [number, number] | null; // typical range
  lowerBetter: boolean;
  decimals: number;
  meaning: string;
  how: string; // calculation transparency
  caveat: string;
  source: string;
  freshness: string; // human "3h ago"
  interpretation: string;
  facts: { label: string; value: string; detail?: string }[];
  related: { kind: string; title: string }[];
};

export type StatusMetric = {
  kind: string;
  label: string;
  domain: DomainKey;
  value: string;
  unit?: string;
  trend: Trend;
  deltaText: string;
  tone: "good" | "watch" | "flat";
  /** Age of the underlying reading. `latest` is the last *recorded* value, not
   *  necessarily a recent one, so a metric that stopped arriving weeks ago must
   *  say so rather than pose as today's state. */
  ageDays: number | null;
  ageLabel: string;
  stale: boolean;
};

export type TaskDemands = {
  open: number;
  overdue: number;
  dueToday: number;
  undated: number;
  soonest: {
    id: number;
    title: string;
    area: string;
    priority: string;
    dueLabel: string;
    overdue: boolean;
  }[];
};

/** The one-line read on today. Assembled from facts the strip and task summary
 *  already established — it introduces no opinion of its own, so it cannot
 *  contradict the recommendation beneath it. */
export type Lede = {
  state: string;
  demand: string;
  nudge: string;
};

export type Recommendation = {
  id: string;
  title: string;
  body: string;
  domain: DomainKey;
  confidence: Confidence;
  evidence: { label: string; value: string; tone?: "good" | "watch" | "flat" }[];
  actions: { label: string; kind: "primary" | "ghost" }[];
};

export type TimelineEntry = {
  id: string;
  time: string; // HH:MM
  title: string;
  detail?: string;
  domain: DomainKey;
  status: "done" | "now" | "upcoming" | "target";
  adjusted?: boolean;
  loggable?: boolean;
};

export type Change = {
  metric: string;
  domain: DomainKey;
  text: string;
  tone: "good" | "watch" | "flat";
};

export type EvidenceClass =
  | "measured"
  | "calculated"
  | "association"
  | "hypothesis"
  | "recommendation";

export type Insight = {
  id: string;
  title: string;
  body: string;
  domain: DomainKey;
  klass: EvidenceClass;
  confidence: Confidence;
  /** What the rule suggests doing. Kept apart from `body` — a finding and a
   *  recommendation warrant different levels of trust. */
  action?: string;
  severity?: "critical" | "warning" | "info" | "positive";
};

export type PlannedSession = {
  id: string;
  domain: DomainKey;
  title: string;
  detail: string;
  durationMin: number;
  intensity: "easy" | "moderate" | "hard";
  status: "planned" | "done" | "adjusted";
  /** Only on planned entries: how the weekday was arrived at. */
  daySource?: "observed" | "spread";
};

export type DayPlan = {
  date: string; // ISO
  dow: string;
  dom: number;
  isToday: boolean;
  sessions: PlannedSession[];
  loadBand?: "clear" | "light" | "loaded" | "heavy";
};

export type Habit = {
  id: string;
  name: string;
  detail: string | null;
  domain: DomainKey;
  cadence: string;
  streak: number;
  bestStreak: number;
  periodDone: number;
  periodTarget: number;
  completionRate: number; // 0..1, judged against the habit's own target
  /** Mon..Sun. `null` means later this week — not done, but not missed
   *  either, so it must not render like a failure. */
  weekTicks: (boolean | null)[];
  doneToday: boolean;
};

export type Goal = {
  id: string;
  title: string;
  detail: string | null;
  domain: DomainKey;
  /** 0..1, or null when progress cannot be computed honestly — no target, or
   *  a decrease goal with no baseline to measure the fall from. Null must not
   *  render as a zero-width bar; that reads as "no progress", a different claim. */
  progress: number | null;
  metricLabel: string;
  current: string;
  target: string;
  dueLabel: string;
  /** Where the current value came from, so a measured goal and a
   *  hand-maintained one are not presented as equally solid. */
  source: "measured" | "manual" | "none";
  direction: "increase" | "decrease";
  status: string;
};

export type SyncSource = {
  name: string;
  status: "ok" | "stale" | "disconnected" | "mock" | "error";
  freshness: string;
};

export type PersonalRecord = {
  domain: DomainKey;
  label: string;
  value: string;
  when: string;
  isNew?: boolean;
};

export type QuickLogAction = {
  key: string;
  label: string;
  domain: DomainKey;
  favourite?: boolean;
};
