/**
 * Realistic, internally consistent demo data mirroring the Orion backend
 * read-model contracts (audit §3). Deterministic — no lorem ipsum, no
 * Math.random. The story: an elevated resting-HR morning that drives today's
 * single recommendation to pull back interval volume.
 */
import type { DomainKey } from "./domains";
import { ANCHOR, makeSeries, mean } from "./series";
import type {
  Change,
  DayPlan,
  Goal,
  Habit,
  Insight,
  MetricDetail,
  PersonalRecord,
  QuickLogAction,
  Recommendation,
  SeriesPoint,
  StatusMetric,
  SyncSource,
  TimelineEntry,
  Trend,
} from "./types";

export const USER = { name: "Declan", today: ANCHOR };

function trendOf(series: SeriesPoint[]): Trend {
  if (series.length < 5) return "flat";
  const recent = mean(series.slice(-3).map((p) => p.value));
  const base = mean(series.slice(-10, -3).map((p) => p.value));
  const diff = recent - base;
  const threshold = Math.abs(base) * 0.03 || 0.1;
  if (Math.abs(diff) < threshold) return "flat";
  return diff > 0 ? "up" : "down";
}

function band(series: SeriesPoint[]): [number, number] {
  const vals = [...series.map((p) => p.value)].sort((a, b) => a - b);
  const q = (p: number) => vals[Math.floor(p * (vals.length - 1))];
  return [Number(q(0.25).toFixed(1)), Number(q(0.75).toFixed(1))];
}

// ---------------------------------------------------------------- metrics
const S = {
  sleep: makeSeries(45, { seed: 11, base: 7.1, drift: -0.7, noise: 0.7, min: 4.5, round: 0.05 }),
  hrv: makeSeries(45, { seed: 22, base: 62, drift: 4, noise: 7, min: 20, round: 1 }),
  rhr: makeSeries(45, { seed: 33, base: 58, drift: 1, noise: 2.4, spikeLast: 42, min: 45, round: 1 }),
  weight: makeSeries(45, { seed: 44, base: 79.5, drift: -1.6, noise: 0.5, round: 0.1 }),
  vo2max: makeSeries(90, { seed: 55, base: 48, drift: 2.4, noise: 0.6, round: 0.1 }),
  runKm: makeSeries(45, { seed: 66, base: 6.5, drift: 1.5, noise: 4.5, min: 0, round: 0.1 }),
  steps: makeSeries(45, { seed: 77, base: 9200, drift: 400, noise: 2600, weekly: 3000, min: 800, round: 100 }),
  energy: makeSeries(45, { seed: 88, base: 620, drift: 40, noise: 180, min: 120, round: 5 }),
  mood: makeSeries(45, { seed: 99, base: 6.6, drift: 0.4, noise: 1.1, min: 1, round: 0.5 }),
  load: makeSeries(45, { seed: 101, base: 560, drift: 120, noise: 140, min: 0, round: 10 }),
  mindful: makeSeries(45, { seed: 111, base: 9, drift: 3, noise: 6, min: 0, round: 1 }),
  respRate: makeSeries(45, { seed: 121, base: 14.4, drift: 0, noise: 0.6, round: 0.1 }),
};

const HAE = "Health Auto Export → Apple Health";

function detail(
  kind: string,
  title: string,
  unit: string,
  domain: DomainKey,
  series: SeriesPoint[],
  o: {
    decimals?: number;
    lowerBetter?: boolean;
    meaning: string;
    how: string;
    caveat?: string;
    source?: string;
    freshness?: string;
    interpretation: string;
    quality?: MetricDetail["quality"];
    facts?: MetricDetail["facts"];
    related?: string[];
    displayValue?: string;
  },
): MetricDetail {
  const vals = series.map((p) => p.value);
  const latest = vals.length ? vals[vals.length - 1] : null;
  const dec = o.decimals ?? 1;
  const b7 = vals.length >= 3 ? Number(mean(vals.slice(-7)).toFixed(dec)) : null;
  const b30 = vals.length >= 10 ? Number(mean(vals.slice(-30)).toFixed(dec)) : null;
  return {
    kind,
    title,
    unit,
    domain,
    latest,
    displayValue: o.displayValue ?? (latest !== null ? latest.toFixed(dec) : "—"),
    trend: trendOf(series),
    quality: o.quality ?? "measured",
    series,
    baseline7: b7,
    baseline30: b30,
    band: series.length ? band(series) : null,
    lowerBetter: o.lowerBetter ?? false,
    decimals: dec,
    meaning: o.meaning,
    how: o.how,
    caveat: o.caveat ?? "",
    source: o.source ?? HAE,
    freshness: o.freshness ?? "3h ago",
    interpretation: o.interpretation,
    facts: o.facts ?? [],
    related: o.related ?? [],
  };
}

export const METRICS: Record<string, MetricDetail> = {
  sleep: detail("sleep", "Sleep", "h", "sleep", S.sleep, {
    meaning: "Nightly time asleep. Consistency moves recovery more than any single long night.",
    how: "Sum of Apple Health sleep samples per night, converted to hours.",
    interpretation: "6h 19m last night — 48 min under your recent need.",
    displayValue: "6h 19m",
    related: ["sleep_debt", "hrv", "resting_hr"],
    freshness: "on waking, 6h ago",
  }),
  hrv: detail("hrv", "HRV", "ms", "recovery", S.hrv, {
    decimals: 0,
    meaning: "Beat-to-beat variability (SDNN). Above your own baseline usually reads as well-absorbed stress.",
    how: "Daily mean of Apple Watch HRV samples.",
    caveat: "Only your own baseline matters; single-day swings are noise. Alcohol, illness and late meals move it.",
    interpretation: "Above your 30-day baseline — the one reassuring signal this morning.",
    related: ["resting_hr", "sleep", "readiness"],
  }),
  resting_hr: detail("resting_hr", "Resting heart rate", "bpm", "cardio", S.rhr, {
    decimals: 0,
    lowerBetter: true,
    meaning: "Beats per minute at full rest. A sudden rise often precedes illness or follows poor sleep or alcohol.",
    how: "Apple Watch resting-heart-rate estimate, daily mean.",
    caveat: "One elevated morning is not a diagnosis. Re-check tomorrow before drawing conclusions.",
    interpretation: "101 bpm — well above your 59 bpm baseline. Treat today as a recovery flag, not an emergency.",
    related: ["hrv", "vo2max", "readiness"],
  }),
  weight: detail("weight", "Weight", "kg", "nutrition", S.weight, {
    meaning: "Trend, not judgement: the 7-day average is the real signal; daily readings swing on water alone.",
    how: "Latest scale or manual entry per day; chart overlays a 7-day rolling average.",
    interpretation: "Down 1.6 kg across six weeks — a controlled, sustainable slope.",
    source: "Withings scale → Apple Health",
    freshness: "this morning",
    related: ["run_distance", "active_energy"],
  }),
  vo2max: detail("vo2max", "VO₂ max", "ml/kg/min", "cardio", S.vo2max, {
    meaning: "Estimated aerobic capacity. Moves slowly; the 90-day direction is what matters.",
    how: "Apple Watch cardio-fitness estimate from outdoor runs.",
    interpretation: "Trending up over the block — aerobic base is responding to the mileage.",
    freshness: "2 days ago",
    related: ["resting_hr", "run_distance"],
  }),
  run_distance: detail("run_distance", "Running distance", "km", "running", S.runKm, {
    meaning: "Daily running volume. Weekly totals and the four-week average carry the training signal.",
    how: "Sum of running-workout distance per day from Apple Health.",
    interpretation: "This week is tracking ahead of your four-week average — hold the progression.",
    related: ["training_load", "vo2max"],
  }),
  steps: detail("steps", "Steps", "", "cardio", S.steps, {
    decimals: 0,
    meaning: "General daily movement outside structured training.",
    how: "Apple Health step count per day.",
    interpretation: "Partial day — 4,120 so far by 09:12.",
    displayValue: "4,120",
    quality: "measured",
    freshness: "live",
    related: ["active_energy"],
  }),
  active_energy: detail("active_energy", "Active energy", "kcal", "cardio", S.energy, {
    decimals: 0,
    meaning: "Energy burned through movement and exercise.",
    how: "Apple Health active-energy total per day.",
    interpretation: "Building through the day; interval session would add ~450 kcal.",
    related: ["steps", "run_distance"],
  }),
  mood: detail("mood", "Mood", "/10", "mind", S.mood, {
    meaning: "Self-reported daily mood at check-in.",
    how: "Morning and evening check-in scores, averaged per day.",
    interpretation: "Steady around 7 this week — no dips flagged.",
    source: "Orion check-in",
    freshness: "this morning",
    related: ["mindfulness"],
  }),
  training_load: detail("training_load", "Training load", "", "running", S.load, {
    decimals: 0,
    meaning: "Rolling training strain from running and strength. Rises with volume and intensity.",
    how: "Weighted sum of session duration × intensity over a rolling window.",
    caveat: "Load rising faster than fitness is when injury risk climbs — the ramp matters more than the level.",
    interpretation: "Up ~180 vs last week; the acute:chronic ratio is at the top of the safe band.",
    source: "Derived from workouts",
    related: ["run_distance"],
  }),
  mindfulness: detail("mindfulness", "Mindfulness", "min", "mind", S.mindful, {
    decimals: 0,
    meaning: "Time in breathwork, meditation, or mindful walks.",
    how: "Sum of logged mindfulness sessions per day.",
    interpretation: "Trending up — a 12-minute weekly average now.",
    source: "Orion + Apple Health",
    related: ["mood"],
  }),
  respiratory_rate: detail("respiratory_rate", "Respiratory rate", "/min", "recovery", S.respRate, {
    meaning: "Breaths per minute during sleep. A rise can accompany illness or poor recovery.",
    how: "Apple Watch respiratory-rate estimate during sleep.",
    interpretation: "Flat at 14.4 — no elevation to accompany the raised resting HR.",
    related: ["resting_hr", "hrv"],
  }),
};

// -------------------------------------------------- readiness (no series)
const READINESS_SCORE = 72;
export const READINESS: MetricDetail = {
  kind: "readiness",
  title: "Readiness",
  unit: "/100",
  domain: "recovery",
  latest: READINESS_SCORE,
  displayValue: String(READINESS_SCORE),
  trend: "down",
  quality: "calculated",
  series: makeSeries(30, { seed: 202, base: 74, drift: -2, noise: 8, min: 20, round: 1 }),
  baseline7: 76,
  baseline30: 75,
  band: [64, 84],
  lowerBetter: false,
  decimals: 0,
  meaning: "A composite of sleep, HRV, resting HR and recent load — how ready your body is for hard work today.",
  how: "Weighted blend: sleep 30%, HRV 25%, resting HR 25%, recent load 20%, each scored against your own baseline.",
  caveat: "A planning guide, not a medical score. One elevated input can pull it down without anything being wrong.",
  source: "Derived from your own baselines",
  freshness: "recalculated 3h ago",
  interpretation: "Moderate — the raised resting HR is the main drag; HRV and mood are holding.",
  facts: [
    { label: "Sleep", value: "6h 19m", detail: "−48 min vs need · pulls score down" },
    { label: "HRV", value: "66 ms", detail: "above baseline · lifts score" },
    { label: "Resting HR", value: "101 bpm", detail: "+42 vs baseline · main drag" },
    { label: "Recent load", value: "top of band", detail: "acute:chronic 1.28 · slight drag" },
  ],
  related: ["sleep", "hrv", "resting_hr", "training_load"],
};

// ------------------------------------------------------ status strip
export const STATUS_STRIP: StatusMetric[] = [
  { kind: "readiness", label: "Recovery", domain: "recovery", value: "72", unit: "/100", trend: "down", deltaText: "−4 vs 7-day 76", tone: "watch" },
  { kind: "sleep", label: "Sleep", domain: "sleep", value: "6h19", trend: "down", deltaText: "−48m vs need", tone: "watch" },
  { kind: "steps", label: "Activity", domain: "cardio", value: "41", unit: "%", trend: "flat", deltaText: "4,120 steps so far", tone: "flat" },
  { kind: "mood", label: "Check-in", domain: "mind", value: "7", unit: "/10", trend: "flat", deltaText: "logged 08:31", tone: "good" },
];

// ------------------------------------------------------ recommendation
export const TODAY_RECOMMENDATION: Recommendation = {
  id: "rec-interval-volume",
  title: "Reduce today's interval volume",
  body: "Resting heart rate is well above your recent range and sleep ran short. Do 4 repetitions instead of 6 and reassess after the warm-up — if HR settles, you can add the last two.",
  domain: "running",
  confidence: "medium",
  evidence: [
    { label: "Resting HR", value: "101 bpm", tone: "watch" },
    { label: "Baseline", value: "59 bpm", tone: "flat" },
    { label: "Sleep", value: "6h 19m", tone: "watch" },
    { label: "HRV", value: "above baseline", tone: "good" },
    { label: "Resp. rate", value: "normal (14.4)", tone: "good" },
  ],
  actions: [
    { label: "Apply adjustment", kind: "primary" },
    { label: "View evidence", kind: "ghost" },
    { label: "Dismiss", kind: "ghost" },
  ],
};

// ------------------------------------------------------ today timeline
export const TIMELINE: TimelineEntry[] = [
  { id: "t1", time: "07:00", title: "Vitamin D + omega-3", domain: "meds", status: "done" },
  { id: "t2", time: "07:20", title: "Sleep synced", detail: "6h 19m · 2 wakes", domain: "sleep", status: "done" },
  { id: "t3", time: "08:31", title: "Morning check-in", detail: "Mood 7 · energy 6", domain: "mind", status: "done" },
  { id: "t4", time: "12:30", title: "Zone-2 run · 40 min", detail: "Adjusted from intervals — 4×3 min, not 6×3 min", domain: "running", status: "upcoming", adjusted: true, loggable: true },
  { id: "t5", time: "13:15", title: "Lunch", detail: "Target ~40g protein", domain: "nutrition", status: "upcoming", loggable: true },
  { id: "t6", time: "18:00", title: "Push session (planned)", detail: "Chest / shoulders / triceps", domain: "strength", status: "upcoming", loggable: true },
  { id: "t7", time: "21:00", title: "Magnesium", domain: "meds", status: "upcoming" },
  { id: "t8", time: "22:30", title: "Wind-down target", detail: "Aim for 7h30 to clear the shortfall", domain: "sleep", status: "target" },
];

// ------------------------------------------------------ meaningful changes
export const CHANGES: Change[] = [
  { metric: "Resting HR", domain: "cardio", text: "+42 bpm vs baseline — first spike in 3 weeks", tone: "watch" },
  { metric: "Sleep debt", domain: "sleep", text: "1h 06m over 14 nights — up from 24 min", tone: "watch" },
  { metric: "VO₂ max", domain: "cardio", text: "48.6 — new 90-day high", tone: "good" },
];

// ------------------------------------------------------ insights (classified)
export const INSIGHTS: Insight[] = [
  { id: "i1", title: "Resting HR spiked to 101 bpm", body: "42 bpm above your 30-day baseline of 59. Respiratory rate and HRV are normal, so illness is not clearly indicated yet.", domain: "cardio", klass: "measured", confidence: "high" },
  { id: "i2", title: "Sleep debt is climbing", body: "Net shortfall of 1h 06m against your personal need over 14 nights, up from 24 min last week.", domain: "sleep", klass: "calculated", confidence: "high" },
  { id: "i3", title: "Shorter sleep tends to precede your RHR spikes", body: "In the last 90 days, 4 of your 5 highest resting-HR mornings followed a night under 6h 30m. This is an association in your own data, not a proven cause.", domain: "recovery", klass: "association", confidence: "medium" },
  { id: "i4", title: "Aerobic base may be lifting VO₂ max", body: "Weekly mileage is up 23% over the block while VO₂ max reached a 90-day high. A plausible contributor, not the only one.", domain: "running", klass: "hypothesis", confidence: "low" },
  { id: "i5", title: "Hold interval volume down until RHR normalises", body: "Given the RHR flag and rising load, keep intensity capped for 24–48h and re-check tomorrow.", domain: "running", klass: "recommendation", confidence: "medium" },
];

// ------------------------------------------------------ training
export const RUN_PLAN = {
  goal: "Sub-45 10k",
  phase: "Base — week 4 of 8",
  weekTargetKm: 32,
  weekDoneKm: 21.4,
  fourWeekAvgKm: 26.8,
  avgPace: "5:24 /km",
  adherence: "5 of 6 planned sessions",
  nextRun: {
    title: "Zone-2 intervals (adjusted)",
    structure: [
      { part: "Warm-up", detail: "10 min easy + 4 strides", intensity: "easy" as const },
      { part: "Main set", detail: "4 × 3 min @ 4:40/km", intensity: "hard" as const },
      { part: "Recovery", detail: "2 min jog between reps", intensity: "easy" as const },
      { part: "Cooldown", detail: "8 min easy", intensity: "easy" as const },
    ],
    estMin: 42,
  },
};

export const STRENGTH = {
  weekSessions: 2,
  weekTarget: 3,
  weekSets: 41,
  weekVolumeKg: 18240,
  lastTrained: "Pull · 2 days ago",
  nextBias: "Push",
  recentPRs: [
    { domain: "strength" as DomainKey, label: "Incline DB press", value: "34 kg × 8", when: "2 days ago", isNew: true },
    { domain: "strength" as DomainKey, label: "Weighted pull-up", value: "+22.5 kg × 5", when: "5 days ago" },
    { domain: "running" as DomainKey, label: "5k time-trial", value: "22:41", when: "9 days ago" },
  ] as PersonalRecord[],
};

/** Active strength workout for the quick-log demo. */
export const ACTIVE_WORKOUT = {
  name: "Push · chest / shoulders / triceps",
  startedAgoMin: 18,
  exercises: [
    {
      id: "e1",
      name: "Barbell bench press",
      muscle: "Chest",
      sets: [
        { n: 1, weight: 60, reps: 10, rpe: 7, done: true },
        { n: 2, weight: 70, reps: 8, rpe: 8, done: true },
        { n: 3, weight: 75, reps: 6, rpe: 8.5, done: false, suggested: "75 kg × 6" },
      ],
    },
    {
      id: "e2",
      name: "Seated DB shoulder press",
      muscle: "Shoulders",
      sets: [
        { n: 1, weight: 22, reps: 10, rpe: 7, done: true },
        { n: 2, weight: 24, reps: 8, rpe: 8, done: false, suggested: "24 kg × 8" },
      ],
    },
  ],
};

// ------------------------------------------------------ week plan
const DOW = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
export function weekPlan(): DayPlan[] {
  // Build the current Mon..Sun explicitly around the anchor (Fri 2026-07-17).
  const anchor = new Date(ANCHOR + "T00:00:00");
  const monday = new Date(anchor);
  monday.setDate(anchor.getDate() - ((anchor.getDay() + 6) % 7));
  const plan: DayPlan[] = [];
  const sessionsByOffset: Record<number, DayPlan["sessions"]> = {
    0: [{ id: "s-mon", domain: "strength", title: "Pull session", detail: "Back / biceps · 6 exercises", durationMin: 55, intensity: "hard", status: "done" }],
    1: [{ id: "s-tue", domain: "running", title: "Easy 6 km", detail: "Zone 2 · 5:40/km", durationMin: 36, intensity: "easy", status: "done" }],
    2: [
      { id: "s-wed", domain: "running", title: "Zone-2 intervals", detail: "4×3 min (adjusted from 6)", durationMin: 42, intensity: "hard", status: "adjusted" },
      { id: "s-wed2", domain: "strength", title: "Push session", detail: "Chest / shoulders / triceps", durationMin: 50, intensity: "moderate", status: "planned" },
    ],
    3: [{ id: "s-thu", domain: "recovery", title: "Rest / mobility", detail: "15 min mobility", durationMin: 15, intensity: "easy", status: "planned" }],
    4: [{ id: "s-fri", domain: "running", title: "Tempo 8 km", detail: "3 km @ threshold", durationMin: 45, intensity: "hard", status: "planned" }],
    5: [{ id: "s-sat", domain: "strength", title: "Legs session", detail: "Squat focus", durationMin: 60, intensity: "hard", status: "planned" }],
    6: [{ id: "s-sun", domain: "running", title: "Long run 14 km", detail: "Progressive finish", durationMin: 82, intensity: "moderate", status: "planned" }],
  };
  const loadByOffset: DayPlan["loadBand"][] = ["loaded", "light", "heavy", "clear", "loaded", "loaded", "heavy"];
  for (let i = 0; i < 7; i++) {
    const d = new Date(monday);
    d.setDate(monday.getDate() + i);
    const iso = d.toISOString().slice(0, 10);
    plan.push({
      date: iso,
      dow: DOW[i],
      dom: d.getDate(),
      isToday: iso === ANCHOR,
      sessions: sessionsByOffset[i] ?? [],
      loadBand: loadByOffset[i],
    });
  }
  return plan;
}

// ------------------------------------------------------ habits & goals
export const HABITS: Habit[] = [
  { id: "h1", name: "Morning check-in", domain: "mind", cadence: "Daily", streak: 23, weekTicks: [true, true, true, false, false, false, false], doneToday: true },
  { id: "h2", name: "10-min mobility", domain: "recovery", cadence: "Daily", streak: 6, weekTicks: [true, false, true, false, false, false, false], doneToday: false },
  { id: "h3", name: "Protein ≥ 150 g", domain: "nutrition", cadence: "Daily", streak: 4, weekTicks: [true, true, false, false, false, false, false], doneToday: false },
  { id: "h4", name: "Read 20 min", domain: "mind", cadence: "Daily", streak: 11, weekTicks: [true, true, true, false, false, false, false], doneToday: false },
  { id: "h5", name: "No alcohol", domain: "recovery", cadence: "Weekdays", streak: 9, weekTicks: [true, true, true, false, false, false, false], doneToday: true },
];

export const GOALS: Goal[] = [
  { id: "g1", title: "Sub-45 10k", domain: "running", progress: 0.62, metricLabel: "Current 10k estimate", current: "47:10", target: "44:59", dueLabel: "Race 21 Sep", projection: "On track — projected 45:20 at current slope; needs one more speed block." },
  { id: "g2", title: "Reach 77 kg", domain: "nutrition", progress: 0.71, metricLabel: "Weight (7-day avg)", current: "79.2 kg", target: "77.0 kg", dueLabel: "by 1 Sep", projection: "Ahead of schedule at −0.4 kg/week." },
  { id: "g3", title: "Bench 100 kg", domain: "strength", progress: 0.85, metricLabel: "Est. 1RM", current: "92 kg", target: "100 kg", dueLabel: "open", projection: "e1RM +6 kg this block; ~8 kg to go." },
  { id: "g4", title: "Sleep ≥ 7h avg", domain: "sleep", progress: 0.4, metricLabel: "14-night average", current: "6h 41m", target: "7h 00m", dueLabel: "ongoing", projection: "Behind — debt rising this week; protect bedtime." },
];

// ------------------------------------------------------ data / sync
export const SYNC_SOURCES: SyncSource[] = [
  { name: "Health Auto Export", status: "ok", freshness: "3h ago" },
  { name: "Withings scale", status: "ok", freshness: "this morning" },
  { name: "Strava", status: "stale", freshness: "2 days ago" },
  { name: "Starling Bank", status: "ok", freshness: "1h ago" },
  { name: "Google Calendar", status: "disconnected", freshness: "—" },
];

// ------------------------------------------------------ quick log
export const QUICK_LOG: QuickLogAction[] = [
  { key: "strength", label: "Strength set", domain: "strength", favourite: true },
  { key: "run", label: "Run / cardio", domain: "running", favourite: true },
  { key: "meal", label: "Meal", domain: "nutrition", favourite: true },
  { key: "weight", label: "Weight", domain: "nutrition", favourite: true },
  { key: "mood", label: "Mood", domain: "mind" },
  { key: "medication", label: "Medication", domain: "meds" },
  { key: "supplement", label: "Supplement", domain: "meds" },
  { key: "journal", label: "Journal", domain: "mind" },
  { key: "symptom", label: "Symptom", domain: "cardio" },
  { key: "habit", label: "Habit tick", domain: "recovery" },
  { key: "note", label: "Note", domain: "neutral" },
];

export function getMetric(kind: string): MetricDetail | undefined {
  if (kind === "readiness") return READINESS;
  return METRICS[kind];
}

export const HEALTH_METRICS = ["vo2max", "resting_hr", "weight", "respiratory_rate"];
export const RECOVERY_METRICS = ["readiness", "sleep", "hrv", "resting_hr"];
export const ALL_METRIC_KINDS = [
  "readiness", "sleep", "hrv", "resting_hr", "run_distance", "training_load",
  "weight", "vo2max", "steps", "active_energy", "mood", "mindfulness", "respiratory_rate",
];
