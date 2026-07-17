"use client";

import { useMemo, useRef, useState } from "react";
import { cn } from "@/lib/cn";
import type { DomainKey } from "@/lib/domains";
import type { SeriesPoint } from "@/lib/types";

const W = 640;
const H = 200;
const PAD = { t: 14, r: 8, b: 22, l: 8 };

function extent(values: number[], band?: [number, number]) {
  let lo = Math.min(...values, ...(band ?? []));
  let hi = Math.max(...values, ...(band ?? []));
  if (lo === hi) {
    lo -= 1;
    hi += 1;
  }
  const pad = (hi - lo) * 0.12;
  return [lo - pad, hi + pad] as const;
}

function fmtDay(iso: string) {
  const d = new Date(iso + "T00:00:00");
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
}

/**
 * The one Orion chart. Line or bar, with an optional typical-range band,
 * a baseline reference line, a rolling average, and a hover readout.
 */
export function TrendChart({
  series,
  domain,
  variant = "line",
  band,
  baseline,
  rolling,
  unit = "",
  decimals = 1,
  height = 200,
  lowerBetter = false,
  className,
}: {
  series: SeriesPoint[];
  domain: DomainKey;
  variant?: "line" | "bar";
  band?: [number, number] | null;
  baseline?: number | null;
  rolling?: number; // rolling-average window
  unit?: string;
  decimals?: number;
  height?: number;
  lowerBetter?: boolean;
  className?: string;
}) {
  const ref = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const color = `var(--${domain})`;

  const geo = useMemo(() => {
    const vals = series.map((p) => p.value);
    const [lo, hi] = extent(vals, band ?? undefined);
    const innerW = W - PAD.l - PAD.r;
    const innerH = height - PAD.t - PAD.b;
    const x = (i: number) => PAD.l + (series.length <= 1 ? innerW / 2 : (i / (series.length - 1)) * innerW);
    const y = (v: number) => PAD.t + innerH - ((v - lo) / (hi - lo)) * innerH;
    const roll: (number | null)[] = rolling
      ? vals.map((_, i) => {
          if (i < rolling - 1) return null;
          const w = vals.slice(i - rolling + 1, i + 1);
          return w.reduce((a, b) => a + b, 0) / w.length;
        })
      : [];
    return { lo, hi, innerW, innerH, x, y, roll };
  }, [series, band, height, rolling]);

  const linePath = series.map((p, i) => `${i ? "L" : "M"}${geo.x(i).toFixed(1)},${geo.y(p.value).toFixed(1)}`).join(" ");
  const areaPath = `${linePath} L${geo.x(series.length - 1).toFixed(1)},${(height - PAD.b).toFixed(1)} L${geo.x(0).toFixed(1)},${(height - PAD.b).toFixed(1)} Z`;
  const rollPath = geo.roll
    .map((v, i) => (v === null ? null : `${geo.roll.slice(0, i).every((x) => x === null) ? "M" : "L"}${geo.x(i).toFixed(1)},${geo.y(v).toFixed(1)}`))
    .filter(Boolean)
    .join(" ");

  const barW = Math.max(2, geo.innerW / series.length - 3);

  function onMove(e: React.MouseEvent) {
    const rect = ref.current?.getBoundingClientRect();
    if (!rect) return;
    const rel = ((e.clientX - rect.left) / rect.width) * W;
    const i = Math.round(((rel - PAD.l) / geo.innerW) * (series.length - 1));
    setHover(Math.max(0, Math.min(series.length - 1, i)));
  }

  const uid = domain + series.length;
  const hp = hover !== null ? series[hover] : null;

  return (
    <div className={cn("relative", className)}>
      <svg
        ref={ref}
        viewBox={`0 0 ${W} ${height}`}
        width="100%"
        height={height}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Trend chart, ${series.length} points`}
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
        className="touch-none"
      >
        <defs>
          <linearGradient id={`fill-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity="0.18" />
            <stop offset="100%" stopColor={color} stopOpacity="0" />
          </linearGradient>
        </defs>

        {band && (
          <rect
            x={PAD.l}
            y={geo.y(band[1])}
            width={geo.innerW}
            height={Math.max(0, geo.y(band[0]) - geo.y(band[1]))}
            fill={color}
            opacity="0.08"
          />
        )}
        {baseline != null && (
          <line
            x1={PAD.l}
            x2={W - PAD.r}
            y1={geo.y(baseline)}
            y2={geo.y(baseline)}
            stroke="var(--border-strong)"
            strokeWidth="1"
            strokeDasharray="3 4"
          />
        )}

        {variant === "line" ? (
          <>
            <path d={areaPath} fill={`url(#fill-${uid})`} />
            <path d={linePath} fill="none" stroke={color} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />
            {rollPath && <path d={rollPath} fill="none" stroke="var(--text-3)" strokeWidth="1.4" strokeDasharray="1 3" />}
          </>
        ) : (
          series.map((p, i) => {
            const outlier = band && (p.value > band[1] || p.value < band[0]);
            return (
              <rect
                key={i}
                x={geo.x(i) - barW / 2}
                y={geo.y(p.value)}
                width={barW}
                height={Math.max(0, height - PAD.b - geo.y(p.value))}
                rx="1.5"
                fill={color}
                opacity={hover === i ? 1 : outlier ? 0.95 : 0.6}
              />
            );
          })
        )}

        {hp && (
          <>
            <line x1={geo.x(hover!)} x2={geo.x(hover!)} y1={PAD.t} y2={height - PAD.b} stroke="var(--border-strong)" strokeWidth="1" />
            <circle cx={geo.x(hover!)} cy={geo.y(hp.value)} r="3.5" fill={color} stroke="var(--surface)" strokeWidth="1.5" />
          </>
        )}
      </svg>

      {hp && (
        <div
          className="pointer-events-none absolute -top-1 z-10 -translate-x-1/2 -translate-y-full rounded-md border border-border bg-surface px-2 py-1 text-center shadow-[var(--shadow-md)]"
          style={{ left: `${(geo.x(hover!) / W) * 100}%` }}
        >
          <div className="tnum text-[13px] font-semibold text-text">
            {hp.value.toFixed(decimals)}
            {unit && <span className="text-faint"> {unit}</span>}
          </div>
          <div className="font-mono text-[10px] text-faint">{fmtDay(hp.day)}</div>
        </div>
      )}
      <div className="mt-1 flex justify-between font-mono text-[10px] text-faint">
        <span>{fmtDay(series[0].day)}</span>
        <span>{fmtDay(series[series.length - 1].day)}</span>
      </div>
      {lowerBetter && <span className="sr-only">Lower is better for this metric.</span>}
    </div>
  );
}

/* --------------------------------------------------- Sparkline (static) */
export function Sparkline({
  series,
  domain,
  className,
}: {
  series: SeriesPoint[];
  domain: DomainKey;
  className?: string;
}) {
  const vals = series.map((p) => p.value);
  const lo = Math.min(...vals);
  const hi = Math.max(...vals) || 1;
  const span = hi - lo || 1;
  const w = 100;
  const h = 28;
  const pts = series
    .map((p, i) => `${((i / (series.length - 1)) * w).toFixed(1)},${(h - 2 - ((p.value - lo) / span) * (h - 4)).toFixed(1)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className={cn("w-full", className)} preserveAspectRatio="none" aria-hidden>
      <polyline points={pts} fill="none" stroke={`var(--${domain})`} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/* --------------------------------------------------------- Score ring */
export function Ring({
  value,
  max = 100,
  domain = "recovery",
  size = 120,
  label,
}: {
  value: number | null;
  max?: number;
  domain?: DomainKey;
  size?: number;
  label?: string;
}) {
  const r = 46;
  const c = 2 * Math.PI * r;
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value / max));
  return (
    <div className="relative grid place-items-center" style={{ width: size, height: size }}>
      <svg viewBox="0 0 110 110" width={size} height={size} className="-rotate-90">
        <circle cx="55" cy="55" r={r} fill="none" stroke="var(--surface-inset)" strokeWidth="8" />
        <circle
          cx="55"
          cy="55"
          r={r}
          fill="none"
          stroke={`var(--${domain})`}
          strokeWidth="8"
          strokeLinecap="round"
          strokeDasharray={`${(pct * c).toFixed(1)} ${c.toFixed(1)}`}
        />
      </svg>
      <div className="absolute text-center">
        <div className="tnum text-2xl font-semibold text-text">{value ?? "—"}</div>
        {label && <div className="text-[11px] text-faint">{label}</div>}
      </div>
    </div>
  );
}

/* --------------------------------------------------- Calendar heatmap */
export function CalendarHeatmap({
  series,
  domain,
  weeks = 12,
}: {
  series: SeriesPoint[];
  domain: DomainKey;
  weeks?: number;
}) {
  const recent = series.slice(-weeks * 7);
  const max = Math.max(...recent.map((p) => p.value), 1);
  return (
    <div className="flex gap-1 overflow-x-auto scroll-slim" aria-hidden>
      {Array.from({ length: weeks }).map((_, wi) => (
        <div key={wi} className="flex flex-col gap-1">
          {Array.from({ length: 7 }).map((_, di) => {
            const p = recent[wi * 7 + di];
            const intensity = p ? Math.min(1, p.value / max) : 0;
            return (
              <span
                key={di}
                title={p ? `${p.day}: ${p.value}` : ""}
                className="size-3 rounded-[3px] border border-border"
                style={{ background: p ? `color-mix(in oklab, var(--${domain}) ${10 + intensity * 80}%, transparent)` : "var(--surface-inset)" }}
              />
            );
          })}
        </div>
      ))}
    </div>
  );
}
