"use client";

import { AlertTriangle, Check, ChevronLeft, Plus, Star } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { type DomainKey, DOMAIN_LABEL, domainStyle } from "@/lib/domains";
import { PLACEHOLDERS, QUICK_LOG } from "@/lib/log-actions";


export default function LogPage() {
  const [active, setActive] = useState<string | null>(null);
  const favourites = QUICK_LOG.filter((a) => a.favourite);
  const rest = QUICK_LOG.filter((a) => !a.favourite);

  if (active === "strength") return <StrengthLogger onBack={() => setActive(null)} />;
  if (active) return <QuickForm actionKey={active} onBack={() => setActive(null)} />;

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-5 lg:px-6 lg:py-6">
      <header className="mb-4">
        <p className="text-[13px] font-medium text-muted">Record</p>
        <h1 className="text-2xl font-semibold tracking-tight text-text lg:text-[28px]">Log</h1>
      </header>

      <p className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-faint">
        <Star className="size-3.5" /> Frequent
      </p>
      <div className="mb-5 grid grid-cols-2 gap-2.5 sm:grid-cols-4">
        {favourites.map((a) => (
          <button key={a.key} onClick={() => setActive(a.key)} style={domainStyle(a.domain)} className="flex flex-col items-start gap-2 rounded-xl border border-border bg-surface p-3.5 text-left transition-colors hover:border-border-strong">
            <span className="grid size-9 place-items-center rounded-lg domain-tint domain-text">
              <Plus className="size-4" />
            </span>
            <span className="text-[13px] font-medium text-text">{a.label}</span>
          </button>
        ))}
      </div>

      <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-faint">Everything else</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {rest.map((a) => (
          <button key={a.key} onClick={() => setActive(a.key)} style={domainStyle(a.domain)} className="flex items-center gap-2.5 rounded-lg border border-border bg-surface px-3 py-2.5 text-left transition-colors hover:border-border-strong">
            <span className="size-2 rounded-full domain-bar" />
            <span className="text-[13px] font-medium text-text">{a.label}</span>
          </button>
        ))}
      </div>
    </div>
  );
}

/* ---------------------------------------------------- strength logger */
const EMPTY_EXERCISE = { id: "ex-1", name: "Exercise 1", sets: [{ weight: 20, reps: 8, done: false }] };

function StrengthLogger({ onBack }: { onBack: () => void }) {
  const [exercises, setExercises] = useState([EMPTY_EXERCISE]);

  function toggle(exId: string, i: number) {
    setExercises((prev) => prev.map((ex) => ex.id !== exId ? ex : { ...ex, sets: ex.sets.map((s, j) => (j === i ? { ...s, done: !s.done } : s)) }));
  }
  function addSet(exId: string) {
    setExercises((prev) => prev.map((ex) => {
      if (ex.id !== exId) return ex;
      const last = ex.sets[ex.sets.length - 1];
      return { ...ex, sets: [...ex.sets, { weight: last.weight, reps: last.reps, done: false }] };
    }));
  }
  function addExercise() {
    setExercises((prev) => [...prev, { id: `ex-${prev.length + 1}`, name: `Exercise ${prev.length + 1}`, sets: [{ weight: 20, reps: 8, done: false }] }]);
  }
  function rename(exId: string, name: string) {
    setExercises((prev) => prev.map((ex) => (ex.id === exId ? { ...ex, name } : ex)));
  }
  function bump(exId: string, i: number, field: "weight" | "reps", delta: number) {
    setExercises((prev) => prev.map((ex) => ex.id !== exId ? ex : { ...ex, sets: ex.sets.map((s, j) => (j === i ? { ...s, [field]: Math.max(0, s[field] + delta) } : s)) }));
  }

  const allSets = exercises.flatMap((ex) => ex.sets);
  const doneSets = allSets.filter((s) => s.done).length;

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-5 lg:px-6 lg:py-6" style={domainStyle("strength")}>
      <button onClick={onBack} className="mb-3 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text">
        <ChevronLeft className="size-4" /> Log
      </button>
      <div className="mb-4 flex items-end justify-between gap-3">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide domain-text">New workout</p>
          <h1 className="text-xl font-semibold tracking-tight text-text">Strength session</h1>
        </div>
        <span className="tnum shrink-0 rounded-full border border-border bg-surface px-2.5 py-1 text-[12px] font-medium text-muted">{doneSets}/{allSets.length} sets</span>
      </div>

      <NotWiredNotice />

      <div className="mt-3 space-y-3">
        {exercises.map((ex) => (
          <div key={ex.id} className="rounded-xl border border-border bg-surface p-3.5">
            <input
              value={ex.name}
              onChange={(e) => rename(ex.id, e.target.value)}
              aria-label="Exercise name"
              className="mb-2 w-full rounded-md border border-transparent bg-transparent text-[15px] font-semibold text-text outline-none hover:border-border focus:border-border-strong"
            />
            <div className="space-y-1.5">
              {ex.sets.map((s, i) => (
                <div key={i} className={cn("flex items-center gap-2 rounded-lg border px-2 py-1.5", s.done ? "border-good/40 bg-good/5" : "border-border bg-surface-2")}>
                  <span className="tnum w-5 text-center text-[12px] font-medium text-faint">{i + 1}</span>
                  <Stepper value={s.weight} unit="kg" onDown={() => bump(ex.id, i, "weight", -2.5)} onUp={() => bump(ex.id, i, "weight", 2.5)} />
                  <span className="text-faint">×</span>
                  <Stepper value={s.reps} unit="reps" onDown={() => bump(ex.id, i, "reps", -1)} onUp={() => bump(ex.id, i, "reps", 1)} />
                  <button onClick={() => toggle(ex.id, i)} aria-pressed={s.done} className={cn("ml-auto grid size-8 place-items-center rounded-lg transition-colors", s.done ? "text-white" : "border border-border text-faint hover:text-text")} style={s.done ? { background: "var(--strength)" } : undefined}>
                    <Check className="size-4" />
                  </button>
                </div>
              ))}
            </div>
            <button onClick={() => addSet(ex.id)} className="mt-2 inline-flex items-center gap-1 text-[12px] font-medium text-muted hover:text-text">
              <Plus className="size-3.5" /> Add set
            </button>
          </div>
        ))}
      </div>

      <button onClick={addExercise} className="mt-3 inline-flex w-full items-center justify-center gap-1 rounded-lg border border-dashed border-border py-2.5 text-[13px] font-medium text-muted hover:text-text">
        <Plus className="size-4" /> Add exercise
      </button>
    </div>
  );
}

/** Logging has no backend endpoint yet. Say so rather than showing a save
 *  button that quietly does nothing. */
function NotWiredNotice() {
  return (
    <div className="flex items-start gap-2.5 rounded-lg border border-warn/30 bg-warn/10 p-3">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
      <p className="text-[12.5px] text-text">
        Logging isn&rsquo;t connected to ORION yet — entries here are not saved. Use the{" "}
        <a href="/today" className="font-medium underline underline-offset-2">current ORION pages</a> to record data in the meantime.
      </p>
    </div>
  );
}

function Stepper({ value, unit, onDown, onUp }: { value: number; unit: string; onDown: () => void; onUp: () => void }) {
  return (
    <div className="flex items-center gap-1">
      <button onClick={onDown} className="grid size-7 place-items-center rounded-md border border-border text-muted hover:text-text" aria-label={`decrease ${unit}`}>−</button>
      <span className="tnum w-14 text-center text-[13px] font-semibold text-text">{value}<span className="ml-0.5 text-[10px] font-normal text-faint">{unit}</span></span>
      <button onClick={onUp} className="grid size-7 place-items-center rounded-md border border-border text-muted hover:text-text" aria-label={`increase ${unit}`}>+</button>
    </div>
  );
}

/* ------------------------------------------------------- quick form */
function QuickForm({ actionKey, onBack }: { actionKey: string; onBack: () => void }) {
  const action = QUICK_LOG.find((a) => a.key === actionKey)!;

  return (
    <div className="mx-auto w-full max-w-md px-4 py-5 lg:py-6" style={domainStyle(action.domain as DomainKey)}>
      <button onClick={onBack} className="mb-3 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text">
        <ChevronLeft className="size-4" /> Log
      </button>
      <div className="mb-4 flex items-center gap-2">
        <span className="size-2.5 rounded-full domain-bar" />
        <h1 className="text-xl font-semibold tracking-tight text-text">{action.label}</h1>
        <span className="ml-auto text-[11px] text-faint">{DOMAIN_LABEL[action.domain]}</span>
      </div>

      <NotWiredNotice />

      <form onSubmit={(e) => e.preventDefault()} className="mt-3 space-y-3">
        <Field label="Value" placeholder={PLACEHOLDERS[actionKey] ?? "Value"} />
        <Field label="Note (optional)" placeholder="Anything worth remembering" />
        <button type="submit" disabled className="w-full cursor-not-allowed rounded-lg border border-border bg-surface-2 py-2.5 text-[13px] font-medium text-faint">
          Save (not connected yet)
        </button>
      </form>
    </div>
  );
}

function Field({ label, placeholder }: { label: string; placeholder: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[12px] font-medium text-muted">{label}</span>
      <input placeholder={placeholder} className="w-full rounded-lg border border-border bg-surface px-3 py-2.5 text-[14px] text-text outline-none placeholder:text-faint focus:border-border-strong" />
    </label>
  );
}
