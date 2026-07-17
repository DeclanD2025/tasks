import { ModulePlaceholder } from "@/components/module-placeholder";

export default function MindPage() {
  return (
    <ModulePlaceholder
      title="Mind"
      eyebrow="Plan & record · mood, journal, mindfulness"
      domain="mind"
      summary="Morning brief and evening debrief, mood and stress tracking, a CBT-style thought record, journalling and mindfulness sessions."
      owns={["Mood, energy, anxiety, stress scales", "Morning intention + evening reflection", "Thought record & protective actions", "Mindfulness minutes and streaks"]}
      source="Orion check-ins + Apple Health mindful minutes"
      state="Built in the current backend; check-in flows and the journal move here. Mood also appears on Today and Insights."
      link={{ href: "/log?for=mood", label: "Log a check-in" }}
    />
  );
}
