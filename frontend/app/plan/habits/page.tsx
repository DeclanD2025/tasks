"use client";

import { Check, Plus } from "lucide-react";
import { useState } from "react";
import { Loaded } from "@/components/loading";
import { EmptyState } from "@/components/patterns";
import { Page } from "@/components/shell";
import { Card, DomainDot, Meta } from "@/components/ui";
import { ApiRejected, getJson, sendJson, useApi } from "@/lib/api";
import { cn } from "@/lib/cn";
import { DOMAIN_LABEL, type DomainKey, domainStyle } from "@/lib/domains";
import type { PlanPayload } from "@/lib/payloads";
import type { Habit } from "@/lib/types";

const DOW = ["M", "T", "W", "T", "F", "S", "S"];

function todayIso(): string {
  const now = new Date();
  // Local date, not toISOString() — that converts to UTC and rolls the day
  // over for anyone west of Greenwich late in the evening.
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export default function HabitsPage() {
  const state = useApi<PlanPayload>("/plan");
  return <Loaded state={state}>{(data) => <Habits initial={data.habits} />}</Loaded>;
}

function Habits({ initial }: { initial: Habit[] }) {
  const [habits, setHabits] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  /** Tick or clear today.
   *
   * Optimistic on the tick itself so the control responds immediately, but the
   * streak comes back from the server — it is derived from the stored entries,
   * and recomputing it here would be a second implementation free to disagree.
   */
  async function toggle(habit: Habit) {
    const next = !habit.doneToday;
    setError(null);
    setPending(habit.id);
    setHabits((list) => list.map((h) => (h.id === habit.id ? { ...h, doneToday: next } : h)));
    try {
      const updated = await sendJson<Habit>(`/habits/${habit.id}/day`, "POST", {
        day: todayIso(),
        done: next,
      });
      setHabits((list) => list.map((h) => (h.id === habit.id ? updated : h)));
    } catch (err) {
      // Put it back: the tick did not happen.
      setHabits((list) => list.map((h) => (h.id === habit.id ? { ...h, doneToday: !next } : h)));
      setError(err instanceof ApiRejected ? err.message : "Could not save that. Try again.");
    } finally {
      setPending(null);
    }
  }

  async function create(form: NewHabit) {
    setError(null);
    try {
      await sendJson<{ id: number }>("/habits", "POST", {
        name: form.name,
        domain: form.domain,
        cadence: form.cadence,
        targetPerPeriod: form.target,
      });
      setHabits((await getJson<PlanPayload>("/plan")).habits);
      setAdding(false);
    } catch (err) {
      setError(err instanceof ApiRejected ? err.message : "Could not create that habit.");
    }
  }

  return (
    <Page title="Habits" eyebrow="Plan & record · routines and streaks">
      {error && (
        <p
          role="alert"
          className="mb-3 rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-warn"
        >
          {error}
        </p>
      )}

      {habits.length ? (
        <Card className="divide-y divide-border">
          {habits.map((h) => (
            <div key={h.id} className="flex items-center gap-4 p-3.5" style={domainStyle(h.domain)}>
              <button
                onClick={() => toggle(h)}
                disabled={pending === h.id}
                aria-pressed={h.doneToday}
                aria-label={`${h.doneToday ? "Clear" : "Mark done"} — ${h.name}`}
                className={cn(
                  "grid size-9 shrink-0 place-items-center rounded-full transition-colors disabled:opacity-50",
                  h.doneToday
                    ? "text-white"
                    : "border border-border text-faint hover:border-border-strong hover:text-muted",
                )}
                style={h.doneToday ? { background: `var(--${h.domain})` } : undefined}
              >
                <Check className="size-4" />
              </button>

              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <DomainDot domain={h.domain} />
                  <p className="text-[14px] font-medium text-text">{h.name}</p>
                </div>
                <p className="text-[12px] text-muted">
                  {h.cadence === "weekly"
                    ? `${h.periodDone}/${h.periodTarget} this week`
                    : h.cadence}
                  {h.streak > 0 && (
                    <> · {h.streak}-{h.cadence === "weekly" ? "week" : "day"} streak</>
                  )}
                  {h.completionRate > 0 && <> · {Math.round(h.completionRate * 100)}% kept</>}
                </p>
              </div>

              <div className="hidden gap-1 sm:flex" aria-hidden>
                {h.weekTicks.map((t, i) => (
                  <div key={i} className="flex flex-col items-center gap-1">
                    <span className="text-[9px] text-faint">{DOW[i]}</span>
                    {/* null = later this week: not done, but not missed either */}
                    <span
                      className={cn(
                        "size-4 rounded-[3px]",
                        t === null
                          ? "border border-dashed border-border"
                          : t
                            ? "domain-bar"
                            : "bg-surface-inset",
                      )}
                    />
                  </div>
                ))}
              </div>
            </div>
          ))}
        </Card>
      ) : (
        <EmptyState
          title="No habits yet"
          body="Track something you want to keep up — a run, a journal entry, ten minutes of reading. ORION counts the streak from what you tick."
          compact={false}
        />
      )}

      {adding ? (
        <NewHabitForm onSubmit={create} onCancel={() => setAdding(false)} />
      ) : (
        <button
          onClick={() => setAdding(true)}
          className="mt-3 inline-flex items-center gap-1.5 rounded-lg border border-border bg-surface px-3 py-2 text-[13px] font-medium text-muted hover:border-border-strong hover:text-text"
        >
          <Plus className="size-4" /> New habit
        </button>
      )}
    </Page>
  );
}

/* ------------------------------------------------------------ NewHabitForm */
type NewHabit = { name: string; domain: DomainKey; cadence: string; target: number };

function NewHabitForm({
  onSubmit,
  onCancel,
}: {
  onSubmit: (form: NewHabit) => void;
  onCancel: () => void;
}) {
  const [form, setForm] = useState<NewHabit>({
    name: "",
    domain: "neutral",
    cadence: "daily",
    target: 1,
  });

  const field =
    "w-full rounded-lg border border-border bg-surface px-2.5 py-2 text-[13.5px] text-text outline-none focus-visible:ring-2 focus-visible:ring-[var(--ring)]";

  return (
    <Card className="mt-3 p-4">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (form.name.trim()) onSubmit(form);
        }}
        className="space-y-3"
      >
        <div>
          <label htmlFor="habit-name" className="mb-1 block text-[12px] font-medium text-muted">
            What are you keeping up?
          </label>
          <input
            id="habit-name"
            autoFocus
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Ten minutes of reading"
            className={field}
          />
        </div>

        <div className="grid gap-3 sm:grid-cols-3">
          <div>
            <label htmlFor="habit-domain" className="mb-1 block text-[12px] font-medium text-muted">
              Area
            </label>
            <select
              id="habit-domain"
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
          <div>
            <label htmlFor="habit-cadence" className="mb-1 block text-[12px] font-medium text-muted">
              How often
            </label>
            <select
              id="habit-cadence"
              value={form.cadence}
              onChange={(e) => setForm({ ...form, cadence: e.target.value })}
              className={field}
            >
              <option value="daily">Every day</option>
              <option value="weekly">Times per week</option>
            </select>
          </div>
          {form.cadence === "weekly" && (
            <div>
              <label htmlFor="habit-target" className="mb-1 block text-[12px] font-medium text-muted">
                Times per week
              </label>
              <input
                id="habit-target"
                type="number"
                min={1}
                max={7}
                value={form.target}
                onChange={(e) => setForm({ ...form, target: Number(e.target.value) })}
                className={field}
              />
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <button
            type="submit"
            disabled={!form.name.trim()}
            className="rounded-lg bg-text px-3 py-2 text-[13px] font-medium text-bg disabled:opacity-40"
          >
            Add habit
          </button>
          <button
            type="button"
            onClick={onCancel}
            className="text-[13px] font-medium text-muted hover:text-text"
          >
            Cancel
          </button>
          <Meta className="ml-auto">Streaks count from the day you add it.</Meta>
        </div>
      </form>
    </Card>
  );
}
