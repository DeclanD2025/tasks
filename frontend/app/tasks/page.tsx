import { ModulePlaceholder } from "@/components/module-placeholder";

export default function TasksPage() {
  return (
    <ModulePlaceholder
      title="Tasks"
      eyebrow="More · open loops"
      domain="neutral"
      summary="Your open-loop list, grouped by area and synced with your external task source. Distinct from Habits, which are recurring routines with streaks."
      owns={["Open tasks grouped by area", "Due dates & completion", "Two-way sync status"]}
      source="External task provider (mirrored locally)"
      state="Built in the backend; UI porting to the new system."
    />
  );
}
