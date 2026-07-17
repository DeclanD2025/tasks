import type { SeriesPoint } from "./types";

/** Deterministic PRNG (mulberry32) so SSR and client hydration match. */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export const ANCHOR = "2026-07-17";

export function isoDaysBack(n: number, anchor = ANCHOR): string[] {
  const end = new Date(anchor + "T00:00:00");
  const out: string[] = [];
  for (let i = n - 1; i >= 0; i--) {
    const d = new Date(end);
    d.setDate(end.getDate() - i);
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

type Shape = {
  seed: number;
  base: number;
  drift?: number; // total drift across window
  noise?: number;
  weekly?: number; // weekend dip amplitude
  spikeLast?: number; // add to the final point (e.g. RHR spike)
  min?: number;
  round?: number; // rounding step
};

/** Build an organic-looking but deterministic daily series. */
export function makeSeries(days: number, s: Shape): SeriesPoint[] {
  const dates = isoDaysBack(days);
  const rand = rng(s.seed);
  const noise = s.noise ?? s.base * 0.05;
  const drift = s.drift ?? 0;
  return dates.map((day, i) => {
    const t = i / (days - 1);
    let v = s.base + drift * t;
    v += (rand() - 0.5) * 2 * noise;
    if (s.weekly) {
      const dow = new Date(day + "T00:00:00").getDay();
      if (dow === 0 || dow === 6) v += (rand() - 0.5) * s.weekly - s.weekly * 0.2;
    }
    if (i === days - 1 && s.spikeLast) v += s.spikeLast;
    if (s.min !== undefined) v = Math.max(s.min, v);
    if (s.round) v = Math.round(v / s.round) * s.round;
    return { day, value: Number(v.toFixed(2)) };
  });
}

export function mean(nums: number[]): number {
  return nums.length ? nums.reduce((a, b) => a + b, 0) / nums.length : 0;
}
