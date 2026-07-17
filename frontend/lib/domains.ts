/**
 * Semantic domains and their colour (Stage 2 §5, brief §11).
 * The CSS var name is the single source of truth for a domain's colour; every
 * component reads `var(--<domain>)` so colour stays consistent everywhere.
 */
export type DomainKey =
  | "sleep"
  | "recovery"
  | "running"
  | "strength"
  | "cardio"
  | "mind"
  | "nutrition"
  | "meds"
  | "neutral";

export const DOMAIN_LABEL: Record<DomainKey, string> = {
  sleep: "Sleep",
  recovery: "Recovery",
  running: "Running",
  strength: "Strength",
  cardio: "Cardiovascular",
  mind: "Mind",
  nutrition: "Nutrition",
  meds: "Medication",
  neutral: "General",
};

/** CSS colour reference for a domain, e.g. `var(--recovery)`. */
export function domainColor(key: DomainKey): string {
  return `var(--${key})`;
}

/** Inline style object that sets `--c` so `.domain-*` helpers resolve. */
export function domainStyle(key: DomainKey): React.CSSProperties {
  return { ["--c" as string]: `var(--${key})` } as React.CSSProperties;
}
