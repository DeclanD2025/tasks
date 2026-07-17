"use client";

import { Check, ChevronLeft, Plus, Star } from "lucide-react";
import { useState } from "react";
import { cn } from "@/lib/cn";
import { type DomainKey, DOMAIN_LABEL, domainStyle } from "@/lib/domains";
import { ACTIVE_WORKOUT, QUICK_LOG } from "@/lib/data";

type SetState = { weight: number; reps: number; done: boolean };

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
function StrengthLogger({ onBack }: { onBack: () => void }) {
  const [sets, setSets] = useState<Record<string, SetState[]>>(() =>
    Object.fromEntries(ACTIVE_WORKOUT.exercises.map((e) => [e.id, e.sets.map((s) => ({ weight: s.weight, reps: s.reps, done: s.done }))])),
  );

  function toggle(exId: string, i: number) {
    setSets((prev) => ({ ...prev, [exId]: prev[exId].map((s, j) => (j === i ? { ...s, done: !s.done } : s)) }));
  }
  function addSet(exId: string) {
    setSets((prev) => {
      const last = prev[exId][prev[exId].length - 1];
      return { ...prev, [exId]: [...prev[exId], { weight: last.weight, reps: last.reps, done: false }] };
    });
  }
  function bump(exId: string, i: number, field: "weight" | "reps", delta: number) {
    setSets((prev) => ({ ...prev, [exId]: prev[exId].map((s, j) => (j === i ? { ...s, [field]: Math.max(0, s[field] + delta) } : s)) }));
  }

  const totalSets = Object.values(sets).flat().length;
  const doneSets = Object.values(sets).flat().filter((s) => s.done).length;

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-5 lg:px-6 lg:py-6" style={domainStyle("strength")}>
      <button onClick={onBack} className="mb-3 inline-flex items-center gap-1 text-[13px] font-medium text-muted hover:text-text">
        <ChevronLeft className="size-4" /> Log
      </button>
      <div className="mb-4 flex items-end justify-between">
        <div>
          <p className="text-[11px] font-semibold uppercase tracking-wide domain-text">Active workout · {ACTIVE_WORKOUT.startedAgoMin}m</p>
          <h1 className="text-xl font-semibold tracking-tight text-text">{ACTIVE_WORKOUT.name}</h1>
        </div>
        <span className="tnum rounded-full border border-border bg-surface px-2.5 py-1 text-[12px] font-medium text-muted">{doneSets}/{totalSets} sets</span>
      </div>

      <div className="space-y-3">
        {ACTIVE_WORKOUT.exercises.map((ex) => (
          <div key={ex.id} className="rounded-xl border border-border bg-surface p-3.5">
            <div className="mb-2 flex items-center justify-between">
              <div>
                <h2 className="text-[15px] font-semibold text-text">{ex.name}</h2>
                <p className="text-[11px] text-faint">{ex.muscle}</p>
              </div>
            </div>
            <div className="space-y-1.5">
              {sets[ex.id].map((s, i) => (
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

      <div className="sticky bottom-4 mt-4 flex gap-2">
        <button onClick={onBack} className="flex-1 rounded-lg border border-border bg-surface py-2.5 text-[13px] font-medium text-text hover:bg-surface-2">Save & close</button>
        <button className="rounded-lg px-4 py-2.5 text-[13px] font-medium text-white" style={{ background: "var(--strength)" }}>Finish workout</button>
      </div>
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
  const [saved, setSaved] = useState(false);

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

      {saved ? (
        <div className="flex items-center gap-3 rounded-xl border border-good/40 bg-good/5 p-4">
          <Check className="size-5 text-good" />
          <p className="text-[14px] text-text">{action.label} logged. Saved offline-safe — it will sync when connected.</p>
        </div>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            setSaved(true);
          }}
          className="space-y-3"
        >
          <Field label="Value" placeholder={placeholderFor(actionKey)} />
          <Field label="Note (optional)" placeholder="Anything worth remembering" />
          <div className="flex items-center gap-2 rounded-lg border border-border bg-surface-2 px-3 py-2 text-[13px] text-muted">
            <span className="text-faint">When</span>
            <span className="ml-auto font-mono text-text">now · Fri 17 Jul 09:12</span>
          </div>
          <button type="submit" className="w-full rounded-lg py-2.5 text-[13px] font-medium text-white" style={{ background: `var(--${action.domain})` }}>
            Save {action.label.toLowerCase()}
          </button>
        </form>
      )}
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

function placeholderFor(key: string) {
  const map: Record<string, string> = {
    meal: "e.g. Chicken & rice · 620 kcal",
    weight: "e.g. 79.2 kg",
    mood: "1–10",
    medication: "e.g. Vitamin D 1000 IU",
    supplement: "e.g. Creatine 5 g",
    journal: "What's on your mind",
    symptom: "e.g. Sore throat",
    habit: "Mark complete",
    note: "Quick note",
    run: "e.g. 8 km · 44:10",
  };
  return map[key] ?? "Value";
}
