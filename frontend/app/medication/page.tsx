import { ModulePlaceholder } from "@/components/module-placeholder";

export default function MedicationPage() {
  return (
    <ModulePlaceholder
      title="Medication"
      eyebrow="Understand · medication & supplements"
      domain="meds"
      summary="Your medication and supplement schedule with adherence and reminders. New module — one of three the redesign adds (with Habits and Goals)."
      owns={["Scheduled meds & supplements", "Taken / missed adherence", "Reminders on the Today timeline", "Interactions & notes"]}
      source="Manual entry + Orion schedule"
      state="New in the redesign — not present in the current app. Timeline entries already show Vitamin D, omega-3 and magnesium on Today."
      link={{ href: "/log?for=medication", label: "Log a dose" }}
    />
  );
}
