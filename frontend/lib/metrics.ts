/**
 * The metric kinds ORION can produce a drilldown for.
 *
 * This is build-time configuration, not data: a static export has to know
 * every `/insights/metric/[kind]` route up front. It must stay in step with
 * `METRIC_SPECS` in `app/domains/health/metric_details.py`; a kind listed here
 * that the backend doesn't know renders an honest "not found" rather than
 * breaking the page.
 */
export const ALL_METRIC_KINDS = [
  "readiness",
  "sleep",
  "sleep_debt",
  "hrv",
  "resting_hr",
  "weight",
  "vo2max",
  "run_distance",
  "steps",
  "active_energy",
  "mindfulness",
  "mood",
  "stress",
  "training_load",
  "blood_pressure",
  "respiratory_rate",
] as const;

/** Shown on Health. */
export const HEALTH_METRICS = [
  "vo2max",
  "resting_hr",
  "weight",
  "respiratory_rate",
  "blood_pressure",
];

/** Shown on Recovery. */
export const RECOVERY_METRICS = ["readiness", "sleep", "hrv", "resting_hr"];
