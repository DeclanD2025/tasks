import { ModulePlaceholder } from "@/components/module-placeholder";

export default function IntegrationsPage() {
  return (
    <ModulePlaceholder
      title="Integrations"
      eyebrow="System · connected services"
      domain="neutral"
      summary="Connect and manage data providers. Split out from Settings so the daily surfaces stay uncluttered."
      owns={["Apple Health / Health Auto Export", "Withings, Strava", "Starling & finance providers", "Google Calendar, task sync"]}
      source="OAuth / API tokens (kept in the OS keychain, never in code)"
      state="Health Auto Export and Starling are live on this instance; other connectors are scaffolds pending real credentials."
      link={{ href: "/data", label: "See data freshness" }}
    />
  );
}
