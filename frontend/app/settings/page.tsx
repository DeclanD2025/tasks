import { Page } from "@/components/shell";
import { ThemeToggle } from "@/components/theme";
import { Card, SectionHeader } from "@/components/ui";

const GROUPS = [
  { label: "Targets", rows: [["Daily protein", "150 g"], ["Sleep need", "7h 07m (learned)"], ["Weekly running", "32 km"], ["Strength sessions", "3 / week"]] },
  { label: "Location & units", rows: [["Location", "Motherwell, UK"], ["Units", "Metric · kg · km"], ["Week starts", "Monday"], ["Currency", "GBP"]] },
  { label: "Account", rows: [["Profile", "Declan"], ["Unlock", "Passphrase"], ["Data", "Local-first, exportable"]] },
];

export default function SettingsPage() {
  return (
    <Page title="Settings" eyebrow="System · preferences">
      <Card className="p-4">
        <SectionHeader title="Appearance" sub="Light, dark, or follow the system. Both themes are first-class." />
        <div className="flex items-center justify-between">
          <span className="text-[13px] text-muted">Theme</span>
          <ThemeToggle />
        </div>
      </Card>

      {GROUPS.map((g) => (
        <Card key={g.label} className="p-4" as="section">
          <SectionHeader title={g.label} />
          <dl className="divide-y divide-border">
            {g.rows.map(([k, v]) => (
              <div key={k} className="flex items-center justify-between py-2.5">
                <dt className="text-[13px] text-muted">{k}</dt>
                <dd className="text-[13px] font-medium text-text">{v}</dd>
              </div>
            ))}
          </dl>
        </Card>
      ))}
    </Page>
  );
}
