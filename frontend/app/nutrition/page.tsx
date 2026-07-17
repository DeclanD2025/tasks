import { ModulePlaceholder } from "@/components/module-placeholder";

export default function NutritionPage() {
  return (
    <ModulePlaceholder
      title="Nutrition"
      eyebrow="Plan & record · fuel"
      domain="nutrition"
      summary="Daily and weekly intake with search, barcode scan, quick-add and saved templates. Local-first: your corrections win future lookups."
      owns={["Calories, protein, carbs, fat, fibre, water", "Search + Open Food Facts barcode scan", "Meal templates & repeat-yesterday", "Weekly averages vs targets"]}
      source="Local food database + Open Food Facts + Apple Health"
      state="Fully built in the current backend — porting the UI to the new system next. Log meals fast from the Log tab."
      link={{ href: "/log?for=meal", label: "Log a meal" }}
    />
  );
}
