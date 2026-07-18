"use client";

import { Plus } from "lucide-react";
import { useState } from "react";
import { Loaded } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Card, Meta } from "@/components/ui";
import { ApiRejected, getJson, sendJson, useApi } from "@/lib/api";
import { cn } from "@/lib/cn";
import { DOMAIN_LABEL, type DomainKey, domainStyle } from "@/lib/domains";
import type { PlanPayload } from "@/lib/payloads";
import type { Goal } from "@/lib/types";

export default function GoalsPage() {
  const state = useApi<PlanPayload>("/plan");
  return <Loaded state={state}>{(data) => <Goals initial={data.goals} />}</Loaded>;
}

function Goals({ initial }: { initial: Goal[] }) {
  const [goals, setGoals] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  async function create(form: NewGoal) {
    setError(null);
    try {
      await sendJson<{ id: number }>("/goals", "POST", {
        title: form.title,
        domain: form.domain,
        baselineValue: form.baseline === "" ? null : Number(form.baseline),
        targetValue: form.target === "" ? null : Number(form.target),
        manualValue: form.current === "" ? null : Number(form.current),
        unit: form.unit,
        direction: form.direction,
        targetDate: form.due || null,
      });
      setGoals((await getJson<PlanPayload>("/plan")).goals);
      setAdding(false);
    } catch (err) {
      setError(err instanceof ApiRejected ? err.message : "Could not create that goal.");
    }
  }

  return (
    <Page title="Goals" eyebrow="Plan & record · what you're working toward">
      {error && (
        <p
          role="alert"
          className="mb-3 rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-warn"
        >
          {error}
        </p>
      )}

      {goals.length ? (
        <div className="grid gap-4 sm:grid-cols-2">
          {goals.map((g) => (
            <GoalCard key={g.id} goal={g} />
          ))}
        </div>
      ) : (
        <EmptyState
          title="No goals yet"
          body="Set something measurable — a weight, a weekly distance, a target you can check yourself against. ORION tracks progress from your own data where it has it."
          compact={false}
        />
      )}

      {adding ? (
        <NewGoalForm onSubmit={create} onCancel={() => setAdding(false)} />
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-[13px] font-medium text-muted hover:border-border-strong hover:text-text"
        >
          <Plus className="size-4" /> New goal
        </button>
      )}
    </Page>
  );
}

/* ---------------------------------------------------------------- GoalCard */
function GoalCard({ goal }: { goal: Goal }) {
  // Progress is null when it cannot be computed honestly — no target, or a
  // decrease goal with no baseline to measure the fall from. A zero-width bar
  // would read as "no progress made", which is a different and wrong claim, so
  // the bar is replaced by the reason instead.
  const measurable = goal.progress !== null;

  return (
    <Card className="p-4" style={domainStyle(goal.domain)}>
      <div className="mb-2 flex items-baseline justify-between gap-3">
        <h2 className="text-[15px] font-semibold text-text">{goal.title}</h2>
        <span className="tnum shrink-0 text-[12px] text-muted">{goal.dueLabel}</span>
      </div>

      {measurable ? (
        <>
          <div
            className="mb-2 h-1.5 overflow-hidden rounded-full bg-surface-inset"
            role="progressbar"
            aria-valuenow={Math.round((goal.progress ?? 0) * 100)}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`${goal.title} progress`}
          >
            <div
              className="domain-bar h-full rounded-full"
              style={{ width: `${(goal.progress ?? 0) * 100}%` }}
            />
          </div>
          <p className="tnum text-[13px] text-text">
            {goal.current} → {goal.target}
            <span className="ml-1.5 text-muted">
              {Math.round((goal.progress ?? 0) * 100)}%
            </span>
          </p>
        </>
      ) : (
        <p className="tnum text-[13px] text-text">
          {goal.current}
          {goal.target !== "—" && <> → {goal.target}</>}
        </p>
      )}

      <p className="mt-1 text-[12.5px] text-muted">
        {goal.source === "measured" ? (
          <>Tracked from {goal.metricLabel.toLowerCase()}</>
        ) : goal.source === "manual" ? (
          <>Updated by hand</>
        ) : (
          <>No value recorded yet</>
        )}
        {!measurable && goal.source !== "none" && (
          <> · needs a target{goal.direction === "decrease" ? " and a starting point" : ""} to show progress</>
        )}
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------- NewGoalForm */
type NewGoal = {
  title: string;
  domain: DomainKey;
  baseline: string;
  current: string;
  target: string;
  unit: string;
  direction: string;
  due: string;
};

function NewGoalForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (form: NewGoal) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<NewGoal>({
    title: "",
    domain: "neutral",
    baseline: "",
    current: "",
    target: "",
    unit: "",
    direction: "increase",
    due: "",
  });

  const field =
    "w-full rounded-lg border border-border bg-surface px-2.5 py-2 text-[13.5px] text-text outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";
  const label = "mb-1 block text-[12px] font-medium text-muted";

  return (
    <Card className="mt-3 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (form.title.trim()) onSubmit(form);
        }}
        className="space-y-3"
      >
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="goal-title" className={label}>
              What are you working toward?
            </label>
            <input
              id="goal-title"
              autoFocus
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Run 30 km a week"
              className={field}
            />
          </div>
          <div>
            <label htmlFor="goal-domain" className={label}>
              Area
            </label>
            <select
              id="goal-domain"
              value={form.domain}
              onChange={(e) => setForm({ ...form, domain: e.target.value as DomainKey })}
              className={field}
            >
              {(Object.keys(DOMAIN_LABEL) as DomainKey[]).map((key) => (
                <option key={key} value={key}>
                  {DOMAIN_LABEL[key]}
                </option>
              ))}
            </select>
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-4">
          <div>
            <label htmlFor="goal-baseline" className={label}>
              Starting at
            </label>
            <input
              id="goal-baseline"
              inputMode="decimal"
              value={form.baseline}
              onChange={(e) => setForm({ ...form, baseline: e.target.value })}
              className={field}
            />
          </div>
          <div>
            <label htmlFor="goal-current" className={label}>
              Now
            </label>
            <input
              id="goal-current"
              inputMode="decimal"
              value={form.current}
              onChange={(e) => setForm({ ...form, current: e.target.value })}
              className={field}
            />
          </div>
          <div>
            <label htmlFor="goal-target" className={label}>
              Target
            </label>
            <input
              id="goal-target"
              inputMode="decimal"
              value={form.target}
              onChange={(e) => setForm({ ...form, target: e.target.value })}
              className={field}
            />
          </div>
          <div>
            <label htmlFor="goal-unit" className={label}>
              Unit
            </label>
            <input
              id="goal-unit"
              value={form.unit}
              onChange={(e) => setForm({ ...form, unit: e.target.value })}
              placeholder="kg"
              className={field}
            />
          </div>
        </div>

        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <label htmlFor="goal-direction" className={label}>
              Progress means
            </label>
            <select
              id="goal-direction"
              value={form.direction}
              onChange={(e) => setForm({ ...form, direction: e.target.value })}
              className={field}
            >
              <option value="increase">Going up</option>
              <option value="decrease">Coming down</option>
            </select>
          </div>
          <div>
            <label htmlFor="goal-due" className={label}>
              By when (optional)
            </label>
            <input
              id="goal-due"
              type="date"
              value={form.due}
              onChange={(e) => setForm({ ...form, due: e.target.value })}
              className={field}
            />
          </div>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={!form.title.trim()}
            className="rounded-lg bg-text px-3 py-2 text-[13px] font-medium text-bg disabled:opacity-40"
          >
            Add goal
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="text-[13px] font-medium text-muted hover:text-text"
          >
            Cancel
          </button>
          <Meta className="ml-auto hidden sm:block">
            A starting point is what makes progress measurable.
          </Meta>
        </div>
      </form>
    </Card>
  );
}
