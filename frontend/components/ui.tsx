import { ArrowDownRight, ArrowUpRight, Minus } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { cn } from "@/lib/cn";
import { type DomainKey, domainStyle } from "@/lib/domains";
import type { Confidence, Quality, Trend } from "@/lib/types";

/* --------------------------------------------------------------- Card */
export function Card({
  className,
  children,
  as: As = "div",
  style,
}: {
  className?: string;
  children: ReactNode;
  as?: React.ElementType;
  style?: React.CSSProperties;
}) {
  return (
    <As className={cn("rounded-xl border border-border bg-surface shadow-[var(--shadow-sm)]", className)} style={style}>
      {children}
    </As>
  );
}

/* ------------------------------------------------------- Section header */
export function SectionHeader({
  title,
  sub,
  action,
  className,
}: {
  title: string;
  sub?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("mb-3 flex items-end justify-between gap-3", className)}>
      <div>
        <h2 className="text-[15px] font-semibold tracking-tight text-text">{title}</h2>
        {sub && <p className="mt-0.5 text-[13px] text-muted">{sub}</p>}
      </div>
      {action}
    </div>
  );
}

/* ---------------------------------------------------------- Domain dot */
export function DomainDot({ domain, className }: { domain: DomainKey; className?: string }) {
  return (
    <span
      aria-hidden
      style={domainStyle(domain)}
      className={cn("inline-block size-2 shrink-0 rounded-full domain-bar", className)}
    />
  );
}

/* --------------------------------------------------------- Delta badge */
const toneColor = {
  good: "text-good",
  watch: "text-warn",
  flat: "text-faint",
} as const;

export function TrendGlyph({ trend, className }: { trend: Trend; className?: string }) {
  const Icon = trend === "up" ? ArrowUpRight : trend === "down" ? ArrowDownRight : Minus;
  return <Icon className={cn("size-3.5", className)} aria-hidden />;
}

export function DeltaBadge({
  tone,
  trend,
  children,
}: {
  tone: "good" | "watch" | "flat";
  trend?: Trend;
  children: ReactNode;
}) {
  return (
    <span className={cn("inline-flex items-center gap-1 text-[12px] font-medium tnum", toneColor[tone])}>
      {trend && <TrendGlyph trend={trend} />}
      {children}
    </span>
  );
}

/* ------------------------------------------------------------- Button */
const btnBase =
  "inline-flex items-center justify-center gap-1.5 rounded-lg text-[13px] font-medium transition-colors disabled:opacity-50 focus-visible:outline-2";
const btnVariant = {
  primary: "bg-text text-bg hover:opacity-90",
  accent: "text-white",
  ghost: "border border-border bg-surface text-text hover:bg-surface-2",
  subtle: "text-muted hover:text-text hover:bg-surface-2",
} as const;
const btnSize = {
  sm: "h-7 px-2.5",
  md: "h-8 px-3",
  lg: "h-10 px-4 text-[14px]",
} as const;

export function Button({
  variant = "ghost",
  size = "md",
  domain,
  className,
  children,
  href,
  ...rest
}: {
  variant?: keyof typeof btnVariant;
  size?: keyof typeof btnSize;
  domain?: DomainKey;
  className?: string;
  children: ReactNode;
  href?: string;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  const style = variant === "accent" && domain ? { background: `var(--${domain})` } : undefined;
  const cls = cn(btnBase, btnVariant[variant], btnSize[size], className);
  if (href) {
    return (
      <Link href={href} className={cls} style={style}>
        {children}
      </Link>
    );
  }
  return (
    <button className={cls} style={style} {...rest}>
      {children}
    </button>
  );
}

/* --------------------------------------------------- Pills / badges */
export function Chip({
  children,
  domain,
  className,
}: {
  children: ReactNode;
  domain?: DomainKey;
  className?: string;
}) {
  return (
    <span
      style={domain ? domainStyle(domain) : undefined}
      className={cn(
        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium",
        domain ? "domain-tint domain-text domain-border" : "border-border bg-surface-2 text-muted",
        className,
      )}
    >
      {children}
    </span>
  );
}

const qualityLabel: Record<Quality, string> = {
  measured: "Measured",
  calculated: "Calculated",
  estimated: "Estimated",
  missing: "No data",
};
const qualityTone: Record<Quality, string> = {
  measured: "text-good",
  calculated: "text-info",
  estimated: "text-warn",
  missing: "text-faint",
};

export function QualityBadge({ quality }: { quality: Quality }) {
  return (
    <span className={cn("inline-flex items-center gap-1 text-[11px] font-medium", qualityTone[quality])}>
      <span aria-hidden className="size-1.5 rounded-full bg-current" />
      {qualityLabel[quality]}
    </span>
  );
}

export function ConfidenceBadge({ confidence }: { confidence: Confidence }) {
  const tone = confidence === "high" ? "text-good" : confidence === "medium" ? "text-warn" : "text-faint";
  return <span className={cn("text-[11px] font-medium capitalize", tone)}>{confidence} confidence</span>;
}

/* ----------------------------------------------------- Freshness meta */
export function Meta({ children, className }: { children: ReactNode; className?: string }) {
  return <span className={cn("font-mono text-[11px] text-faint", className)}>{children}</span>;
}
