/**
 * Response shapes for `/api/v2/*`, one per endpoint.
 *
 * These mirror `app/web/ui_models.py` exactly. If you change a payload there,
 * change it here — TypeScript is the only thing keeping the two honest.
 */
import type {
  Change,
  DayPlan,
  Goal,
  Habit,
  Insight,
  Lede,
  MetricDetail,
  PersonalRecord,
  Recommendation,
  StatusMetric,
  SyncSource,
  TaskDemands,
  TimelineEntry,
} from "./types";

export type MetricMap = Record<string, MetricDetail>;

export type TodayPayload = {
  user: { name: string; today: string };
  status: string;
  score: number | null;
  scoreLabel: string;
  estimated: boolean;
  freshness: string;
  sleepDebtLabel: string;
  statusStrip: StatusMetric[];
  lede: Lede;
  tasks: TaskDemands;
  recommendation: Recommendation | null;
  /** Served here so Today is one request, not three — the read models behind
   *  training and sources are expensive to rebuild. */
  nextRun: {
    title: string;
    detail: string;
    distanceKm: number;
    intensity: string;
    dayLabel: string;
    phase: string;
  } | null;
  syncSources: SyncSource[];
  timeline: TimelineEntry[];
  changes: Change[];
  insights: Insight[];
};

export type RecoveryFactor = {
  label: string;
  value: string;
  impact: string;
  contribution: number;
  delta: number;
  present: boolean;
};

export type RecoveryPayload = {
  score: number | null;
  label: string;
  estimated: boolean;
  dataQuality: string;
  recommendation: string;
  changes: { metric: string; text: string; tone: string }[];
  factors: RecoveryFactor[];
  sleepDebt: { label: string; calibrating: boolean; nightsRecorded: number };
  metrics: MetricMap;
};

export type RunSession = {
  dayLabel: string;
  title: string;
  detail: string;
  distanceKm: number;
  intensity: string;
  sessionType?: string;
};

export type TrainingPayload = {
  runPlan: {
    goal: string;
    phase: string;
    weekTargetKm: number;
    weekDoneKm: number;
    fourWeekAvgKm: number;
    avgPace: string;
    adherence: string;
    guardrail: string;
    nextRun: RunSession;
    week: RunSession[];
  };
  strength: {
    weekSessions: number;
    weekVolumeKg: number;
    personalBests: string[];
    progressionInsight: string;
    recentSessions: {
      id: number;
      day: string;
      title: string;
      category: string;
      completed: boolean;
      durationMinutes: number | null;
      rpe: number | null;
      setCount: number;
      volume: number;
    }[];
  };
  metrics: MetricMap;
};

export type PlannedSession = {
  id: string;
  domain: string;
  /** The day the planner committed this to, e.g. "Tue 21 Jul". */
  when: string;
  title: string;
  detail: string;
  distanceKm: number;
  sessionType: string;
  intensity: string;
  /** "observed" when the weekday came from the athlete's own running history,
   *  "spread" when there was too little history and this is an even fallback.
   *  A default must not be presented as a finding. */
  daySource: "observed" | "spread";
};

export type PlanPayload = {
  /** Mon–Sun of this week: what was actually recorded. */
  week: DayPlan[];
  planned: PlannedSession[];
  habits: Habit[];
  goals: Goal[];
  /** Why a section is empty, when ORION has no producer for it at all. */
  unavailable: { habits?: string; goals?: string };
};

export type InsightsPayload = {
  insights: Insight[];
  metrics: MetricMap;
  personalRecords: PersonalRecord[];
  syncSources: SyncSource[];
};

export type HealthPayload = { metrics: MetricMap };
