/**
 * What you can log, and the shape of each form.
 *
 * Interface configuration, not data — it describes the buttons on the Log
 * screen. The values a user enters go to the backend; this list does not.
 */
import type { QuickLogAction } from "./types";

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

export const PLACEHOLDERS: Record<string, string> = {
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
