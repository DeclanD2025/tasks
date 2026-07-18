"use client";

/**
 * Strength analytics.
 *
 * Every block on this page answers one stated question, and none of it does
 * arithmetic — the numbers arrive finished from `app/domains/strength/
 * reporting.py`, so the chart and the CSV export can never disagree.
 *
 * The design rule that matters most here is that the page has to be as willing
 * to say "not enough data" as it is to draw a bar. Sections that cannot be
 * computed honestly render their reason instead of an empty axis, because an
 * empty chart reads as "zero" and that is a different claim from "unknown".
 */

import { useState } from "react";
import { Loaded } from "@/components/loading";
import { Page } from "@/components/shell";
import { Card, Chip, Meta, SectionHeader } from "@/components/ui";
import { useApi } from "@/lib/api";
import { domainStyle } from "@/lib/domains";
import { type Analytics, type DetailedMuscles, formatVolume } from "@/lib/strength";

const WINDOWS = [
  { days: 7, label: "7d" },
  { days: 28, label: "4w" },
  { days: 84, label: "12w" },
  { days: 182, label: "6m" },
  { days: 365, label: "12m" },
];

export default function StrengthAnalyticsPage() {
  const [days, setDays] = useState(28);
  const state = useApi<Analytics>(`/strength/analytics?days=${days}`);

  return (
    <Page
      title="Strength analytics"
      eyebrow="Working sets only · warm-ups excluded throughout"
    >
      <div className="flex flex-wrap gap-1.5">
        {WINDOWS.map((window) => (
          <button
            key={window.days}
            type="button"
            onClick={() => setDays(window.days)}
            className={`rounded-full border px-3 py-1 text-[12px] font-medium ${
              days === window.days
                ? "border-border-strong bg-surface-2 text-text"
                : "border-border text-muted hover:text-text"
            }`}
          >
            {window.label}
          </button>
        ))}
      </div>

      <Loaded state={state}>{(data) => <AnalyticsBody data={data} />}</Loaded>
    </Page>
  );
}

function AnalyticsBody({ data }: { data: Analytics }) {
  const empty = data.summary.workingSets === 0;

  if (empty) {
    return (
      <Card className="p-6 text-center">
        <p className="text-[15px] font-medium text-text">Nothing logged in this window</p>
        <p className="mx-auto mt-1 max-w-[46ch] text-[13px] text-muted">
          Analytics need individually logged sets. Sessions imported from Apple Health count
          as training done, but carry no exercise detail to analyse.
        </p>
      </Card>
    );
  }

  return (
    <>
      <Card className="p-4 sm:p-5" style={domainStyle("strength")}>
        <SectionHeader title="Totals" sub={`${data.from} → ${data.to}`} />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <Stat label="Sessions" value={String(data.summary.sessions)} />
          <Stat label="Volume" value={formatVolume(data.summary.volumeKg)} />
          <Stat label="Working sets" value={String(data.summary.workingSets)} />
          <Stat label="Hard sets" value={String(data.summary.hardSets)} />
          <Stat label="Reps" value={data.summary.reps.toLocaleString()} />
        </div>
        {data.summary.ratedSets < data.summary.workingSets && (
          <p className="mt-3 text-[11px] text-faint">
            {data.summary.workingSets - data.summary.ratedSets} of {data.summary.workingSets} sets
            have no effort rating, so the hard-set count is a floor rather than a total.
          </p>
        )}
      </Card>

      {/* Volume by week — is training load rising or falling? */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="Volume by week" sub="Is total work rising or falling?" />
        <BarRows
          rows={data.byWeek.map((week) => ({
            key: week.period,
            label: week.period.replace(/^\d{4}-/, ""),
            value: week.volumeKg,
            detail: `${week.workingSets} sets · ${week.sessions} sessions`,
          }))}
          format={formatVolume}
        />
      </Card>

      <DetailedMuscleBreakdown data={data.detailedMuscles} />

      {/* Muscle balance — what is actually being trained? */}
      <Card className="p-4 sm:p-5">
        <SectionHeader
          title="Sets per muscle group"
          sub={`Coarse grouping. Indirect weighted at ${data.weighting.secondary}× and shown separately.`}
        />
        <table className="w-full text-[13px]">
          <thead>
            <tr className="border-b border-border text-left text-[11px] uppercase tracking-wide text-muted">
              <th className="pb-1.5 font-semibold">Muscle</th>
              <th className="pb-1.5 text-right font-semibold">Direct</th>
              <th className="pb-1.5 text-right font-semibold">Indirect</th>
              <th className="pb-1.5 text-right font-semibold">Volume</th>
              <th className="pb-1.5 text-right font-semibold">Last</th>
            </tr>
          </thead>
          <tbody>
            {data.byMuscle.map((row) => (
              <tr key={row.muscle} className="border-b border-border/50 last:border-0">
                <td className="py-1.5 text-text">{row.muscle}</td>
                <td className="tnum py-1.5 text-right text-text">{row.directSets}</td>
                <td className="tnum py-1.5 text-right text-muted">{row.indirectSets || "—"}</td>
                <td className="tnum py-1.5 text-right text-muted">{formatVolume(row.volumeKg)}</td>
                <td className="tnum py-1.5 text-right text-faint">
                  {row.daysSince != null ? `${row.daysSince}d` : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-2 text-[11px] text-faint">
          Indirect sets are a convention for comparability, not a physiological measurement.
        </p>
      </Card>

      {/* Balance — is the programme lopsided? */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="Balance" sub="Is the programme lopsided?" />
        <div className="grid gap-3 sm:grid-cols-3">
          <Ratio
            label="Push : pull"
            ratio={data.balance.pushPull}
            left={data.balance.pushSets}
            right={data.balance.pullSets}
          />
          <Ratio
            label="Squat : hinge"
            ratio={data.balance.squatHinge}
            left={data.balance.squatSets}
            right={data.balance.hingeSets}
          />
          <Ratio
            label="Upper : lower"
            ratio={data.balance.upperLower}
            left={data.balance.upperSets}
            right={data.balance.lowerSets}
          />
        </div>
      </Card>

      {/* Intensity — how hard, and at what rep ranges? */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="Intensity" sub="How heavy, and in what rep ranges?" />
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat
            label="Average load"
            value={data.intensity.averageLoadKg != null ? `${Math.round(data.intensity.averageLoadKg)} kg` : "—"}
          />
          <Stat
            label="Average RPE"
            value={data.intensity.averageRpe != null ? data.intensity.averageRpe.toFixed(1) : "—"}
            note={
              data.intensity.ratedShare != null
                ? `${Math.round(data.intensity.ratedShare * 100)}% of sets rated`
                : undefined
            }
          />
          <Stat label="To failure" value={String(data.intensity.failureSets)} />
          <Stat
            label="Failure share"
            value={
              data.intensity.failureShare != null
                ? `${Math.round(data.intensity.failureShare * 100)}%`
                : "—"
            }
          />
        </div>
        <div className="mt-4">
          <Meta className="mb-1.5 block">Rep distribution</Meta>
          <BarRows
            rows={Object.entries(data.intensity.repDistribution).map(([range, count]) => ({
              key: range,
              label: `${range} reps`,
              value: count,
              detail: `${count} sets`,
            }))}
            format={(v) => String(v)}
          />
        </div>
      </Card>

      {/* Exercises */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="Volume by exercise" sub="Where the work went" />
        <BarRows
          rows={data.byExercise.map((row) => ({
            key: row.key,
            label: row.key,
            value: row.volumeKg,
            detail: `${row.sets} sets · ${row.sessions} sessions`,
          }))}
          format={formatVolume}
        />
      </Card>

      {/* Adherence */}
      <Card className="p-4 sm:p-5">
        <SectionHeader title="Adherence" sub="Planned against completed" />
        {data.adherence.rateAvailable ? (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <Stat label="Planned" value={String(data.adherence.plannedSessions)} />
              <Stat label="Completed" value={String(data.adherence.completedSessions)} />
              <Stat label="Partial" value={String(data.adherence.partialSessions)} />
              <Stat
                label="Completion"
                value={
                  data.adherence.completionRate != null
                    ? `${Math.round(data.adherence.completionRate * 100)}%`
                    : "—"
                }
              />
            </div>
            {data.adherence.unplannedSessions > 0 && (
              <p className="mt-3 text-[11px] text-faint">
                {data.adherence.unplannedSessions} unplanned session
                {data.adherence.unplannedSessions === 1 ? "" : "s"} are counted but kept out of the
                rate — training that was never scheduled is not adherence to a schedule.
              </p>
            )}
          </>
        ) : (
          <p className="text-[13px] text-muted">{data.adherence.note}</p>
        )}
      </Card>

      {/* Associations */}
      <Card className="p-4 sm:p-5">
        <SectionHeader
          title="Readiness and performance"
          sub="Associations in your own log — never evidence of cause"
        />
        <ul className="space-y-2.5">
          {data.associations.map((row, i) => (
            <li key={i} className="rounded-md border border-border px-3 py-2.5">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <p className="text-[13px] font-medium text-text">
                  {row.input} <span className="text-muted">vs</span> {row.outcome}
                </p>
                {row.available ? (
                  <Chip>
                    {row.strength} {row.direction}
                    {row.coefficient != null && ` · r ${row.coefficient}`}
                  </Chip>
                ) : (
                  <Chip>not enough data</Chip>
                )}
              </div>
              <p className="mt-1 text-[12px] text-muted">{row.note}</p>
              {row.available && (
                <Meta className="mt-1 block">
                  {row.observations} observations · {row.from} → {row.to}
                  {row.missingRate != null && ` · ${Math.round(row.missingRate * 100)}% of sessions missing data`}
                </Meta>
              )}
            </li>
          ))}
        </ul>
      </Card>

      {data.warnings.length > 0 && (
        <Card className="p-4">
          <SectionHeader title="Observations" sub="Advisory — every one has a legitimate exception" />
          <ul className="space-y-1.5">
            {data.warnings.map((warning) => (
              <li key={warning.code} className="text-[12px] text-muted">
                {warning.message}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card className="p-4">
        <SectionHeader title="Export" sub="Your data, in a form other tools can read" />
        <div className="flex flex-wrap gap-2">
          <a
            href="/api/v2/strength/export.csv?table=sets"
            className="rounded-lg border border-border px-3 py-1.5 text-[13px] font-medium text-text hover:bg-surface-2"
          >
            Sets CSV
          </a>
          <a
            href="/api/v2/strength/export.csv?table=sessions"
            className="rounded-lg border border-border px-3 py-1.5 text-[13px] font-medium text-text hover:bg-surface-2"
          >
            Sessions CSV
          </a>
          <a
            href="/api/v2/strength/export.json"
            className="rounded-lg border border-border px-3 py-1.5 text-[13px] font-medium text-text hover:bg-surface-2"
          >
            Full JSON backup
          </a>
        </div>
      </Card>
    </>
  );
}

/**
 * The 27-muscle breakdown.
 *
 * Two things this deliberately refuses to do. It does not merge the three
 * contribution tiers into one bar — a muscle whose share is entirely
 * stabiliser work has not been trained, and a single bar would say it had. And
 * it does not pick between set share and volume share: they disagree sharply
 * on heavy compounds (a bench-led session is ~45% chest by tonnage and ~14% by
 * sets) and both are true, so the reading is switchable and labelled.
 */
function DetailedMuscleBreakdown({ data }: { data: DetailedMuscles }) {
  const [basis, setBasis] = useState<"sets" | "volume">("sets");
  const [showAll, setShowAll] = useState(false);

  if (data.muscles.length === 0) {
    return null;
  }

  const key = basis === "sets" ? "sharePercent" : "volumeSharePercent";
  const rows = [...data.muscles].sort((a, b) => b[key] - a[key]);
  const visible = showAll ? rows : rows.slice(0, 12);
  const max = Math.max(...rows.map((r) => r[key]), 1);

  return (
    <Card className="p-4 sm:p-5">
      <SectionHeader
        title="Muscle breakdown"
        sub="27-muscle model. Front, side and rear delts counted separately."
        action={
          <div className="flex gap-1" role="group" aria-label="Weighting basis">
            {(["sets", "volume"] as const).map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => setBasis(option)}
                aria-pressed={basis === option}
                className={`rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${
                  basis === option
                    ? "border-border-strong bg-surface-2 text-text"
                    : "border-border text-muted hover:text-text"
                }`}
              >
                by {option}
              </button>
            ))}
          </div>
        }
      />

      {/* Regions first — six numbers are readable at a glance, 27 are not. */}
      <ul className="mb-4 flex flex-wrap gap-x-4 gap-y-1.5">
        {data.regions.map((region) => (
          <li key={region.region} className="flex items-baseline gap-1.5">
            <span className="text-[13px] text-text">{region.region}</span>
            <span className="tnum text-[13px] font-semibold text-text">
              {basis === "sets" ? region.sharePercent : region.volumeSharePercent}%
            </span>
          </li>
        ))}
      </ul>

      <ul className="space-y-2">
        {visible.map((row) => (
          <li key={row.muscle}>
            <div className="flex items-baseline justify-between gap-2">
              <span className="truncate text-[13px] text-text">
                {row.muscle}
                {row.stabiliserOnly && (
                  <span className="ml-1.5 text-[11px] text-faint">stabiliser only</span>
                )}
              </span>
              <span className="tnum shrink-0 text-[12px] font-medium text-text">
                {row[key]}%
              </span>
            </div>
            {/* Three stacked segments, so direct work and stabiliser work stay
                visually distinct rather than merging into one claim. */}
            <div
              className="mt-1 flex h-1.5 overflow-hidden rounded-full bg-surface-2"
              aria-hidden="true"
            >
              {(["primarySets", "secondarySets", "stabiliserSets"] as const).map(
                (tier, i) => {
                  const total =
                    row.primarySets + row.secondarySets + row.stabiliserSets || 1;
                  const width = (row[tier] / total) * (row[key] / max) * 100;
                  return width > 0 ? (
                    <div
                      key={tier}
                      className="h-full"
                      style={{
                        ...domainStyle("strength"),
                        width: `${width}%`,
                        background: "var(--domain)",
                        opacity: [1, 0.55, 0.28][i],
                      }}
                    />
                  ) : null;
                },
              )}
            </div>
            <Meta className="mt-0.5 block">
              {row.primarySets > 0 && `${row.primarySets} direct`}
              {row.secondarySets > 0 && `${row.primarySets > 0 ? " · " : ""}${row.secondarySets} synergist`}
              {row.stabiliserSets > 0 && `${row.primarySets > 0 || row.secondarySets > 0 ? " · " : ""}${row.stabiliserSets} stabiliser`}
              {` · last ${row.daysSince === 0 ? "today" : `${row.daysSince}d ago`}`}
            </Meta>
          </li>
        ))}
      </ul>

      {rows.length > 12 && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="mt-3 text-[12px] font-medium text-muted hover:text-text"
        >
          {showAll ? "Show top 12" : `Show all ${rows.length}`}
        </button>
      )}

      {data.untrained.length > 0 && (
        <div className="mt-4 border-t border-border pt-3">
          {/* The gap is often the finding: a muscle with no row is easy to miss. */}
          <p className="text-[11px] font-semibold uppercase tracking-wide text-muted">
            No direct work in this window
          </p>
          <p className="mt-1 text-[12px] text-muted">{data.untrained.join(" · ")}</p>
        </div>
      )}

      <p className="mt-3 text-[11px] text-faint">
        {data.note} Synergists count {data.weighting.secondary}×, stabilisers{" "}
        {data.weighting.stabiliser}×.
      </p>
    </Card>
  );
}

// --------------------------------------------------------------------------- //
// Presentation
// --------------------------------------------------------------------------- //
function BarRows({
  rows,
  format,
}: {
  rows: { key: string; label: string; value: number; detail?: string }[];
  format: (value: number) => string;
}) {
  if (rows.length === 0) {
    return <p className="text-[12px] text-faint">Nothing to show in this window.</p>;
  }
  const max = Math.max(...rows.map((row) => row.value), 1);

  return (
    <ul className="space-y-2">
      {rows.map((row) => (
        <li key={row.key}>
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-[13px] text-text">{row.label}</span>
            <span className="tnum shrink-0 text-[12px] font-medium text-text">
              {format(row.value)}
            </span>
          </div>
          {/* The bar is a reading aid; the number above it is the data. */}
          <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-surface-2" aria-hidden="true">
            <div
              className="h-full rounded-full bg-[var(--domain)]"
              style={{ ...domainStyle("strength"), width: `${(row.value / max) * 100}%` }}
            />
          </div>
          {row.detail && <Meta className="mt-0.5 block">{row.detail}</Meta>}
        </li>
      ))}
    </ul>
  );
}

function Ratio({
  label,
  ratio,
  left,
  right,
}: {
  label: string;
  ratio: number | null;
  left: number;
  right: number;
}) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</p>
      {ratio != null ? (
        <p className="tnum mt-0.5 text-[18px] font-semibold tracking-tight text-text">
          {ratio}:1
        </p>
      ) : (
        <p className="mt-0.5 text-[13px] text-muted">
          {left === 0 && right === 0 ? "No work either side" : "Nothing on one side"}
        </p>
      )}
      <Meta className="mt-0.5 block">{left} vs {right} sets</Meta>
    </div>
  );
}

function Stat({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div>
      <p className="text-[10px] font-semibold uppercase tracking-wide text-muted">{label}</p>
      <p className="tnum mt-0.5 text-[20px] font-semibold tracking-tight text-text">{value}</p>
      {note && <p className="text-[11px] text-faint">{note}</p>}
    </div>
  );
}
