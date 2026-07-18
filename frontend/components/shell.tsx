"use client";

import { PanelLeftClose, PanelLeft, RefreshCw, Sparkles, X } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode, useEffect, useState, useSyncExternalStore } from "react";
import { useApi } from "@/lib/api";
import { cn } from "@/lib/cn";
import { MOBILE_NAV, MORE_ITEMS, SIDEBAR_GROUPS } from "@/lib/nav";
import type { SyncSource } from "@/lib/types";
import { ThemeToggle } from "./theme";

function useActive() {
  const pathname = usePathname();
  return (href: string) => {
    const base = href.split("?")[0];
    if (base === "/") return pathname === "/";
    return pathname === base || pathname.startsWith(base + "/");
  };
}

/* ============================================================ Sidebar */
function Sidebar() {
  const isActive = useActive();
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    setCollapsed(localStorage.getItem("orion-sidebar") === "1");
  }, []);
  function toggle() {
    setCollapsed((c) => {
      localStorage.setItem("orion-sidebar", c ? "0" : "1");
      return !c;
    });
  }

  return (
    <aside
      className="sticky top-0 hidden h-svh shrink-0 flex-col border-r border-border bg-surface lg:flex"
      style={{ width: collapsed ? "4rem" : "var(--sidebar-w)" }}
    >
      <div className={cn("flex h-14 items-center border-b border-border px-3", collapsed ? "justify-center" : "justify-between")}>
        {!collapsed && (
          <Link href="/" className="flex items-center gap-2">
            <span className="grid size-7 place-items-center rounded-lg bg-text text-bg">
              <Sparkles className="size-4" />
            </span>
            <span className="text-[15px] font-semibold tracking-tight">Orion</span>
          </Link>
        )}
        <button onClick={toggle} aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"} className="grid size-8 place-items-center rounded-lg text-faint hover:bg-surface-2 hover:text-text">
          {collapsed ? <PanelLeft className="size-4" /> : <PanelLeftClose className="size-4" />}
        </button>
      </div>

      <nav className="scroll-slim flex-1 overflow-y-auto px-2 py-3">
        {SIDEBAR_GROUPS.map((group) => (
          <div key={group.label} className="mb-4">
            {!collapsed && <p className="mb-1 px-2 text-[10px] font-semibold uppercase tracking-wider text-faint">{group.label}</p>}
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = isActive(item.href);
                const Icon = item.icon;
                return (
                  <li key={item.key}>
                    <Link
                      href={item.href}
                      title={collapsed ? item.label : undefined}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "flex items-center gap-2.5 rounded-lg px-2 py-1.5 text-[13px] font-medium transition-colors",
                        collapsed && "justify-center",
                        active ? "bg-surface-2 text-text" : "text-muted hover:bg-surface-2 hover:text-text",
                      )}
                    >
                      <Icon className={cn("size-[18px] shrink-0", active && "text-text")} />
                      {!collapsed && <span className="truncate">{item.label}</span>}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </div>
        ))}
      </nav>
    </aside>
  );
}

/* ============================================================ TopBar */
/** Today's date, read from the device clock.
 *
 * This is a static export, so anything computed at build time freezes on the
 * build date — the date has to come from the client. The clock is an external
 * mutable source, which is what useSyncExternalStore is for: the null server
 * snapshot means the prerendered HTML carries no date, so there is nothing for
 * the client to mismatch on hydration.
 */
const clock = {
  // A tab left open overnight must not keep yesterday's date on screen.
  subscribe(onChange: () => void) {
    const timer = setInterval(onChange, 60_000);
    return () => clearInterval(timer);
  },
  // Date-granular, so this is a stable value within a day and React's
  // Object.is comparison does not see a change on every tick.
  now: () => new Date().toDateString(),
  onServer: () => null,
};

function useToday(): string | null {
  const stamp = useSyncExternalStore(clock.subscribe, clock.now, clock.onServer);
  if (!stamp) return null;
  return new Date(stamp).toLocaleDateString("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    year: "numeric",
  });
}

/** The freshness chip: how many sources are current, from the real source list. */
function SyncChip() {
  const sources = useApi<{ sources: SyncSource[] }>("/sources");
  if (!sources.data) return null;

  const rows = sources.data.sources ?? [];
  const live = rows.filter((s) => s.status === "ok");
  const degraded = rows.filter((s) => s.status === "stale" || s.status === "error");
  // Colour follows the worst state, so a green tick never hides a stale feed.
  const tone = live.length === 0 ? "text-crit" : degraded.length ? "text-warn" : "text-good";

  return (
    <Link
      href="/data"
      className="hidden items-center gap-1.5 rounded-full border border-border bg-surface px-2.5 py-1 text-[12px] text-muted hover:text-text sm:inline-flex"
      title={
        degraded.length
          ? `${degraded.length} source${degraded.length === 1 ? "" : "s"} need attention`
          : "All connected sources are current"
      }
    >
      <RefreshCw className={cn("size-3.5", tone)} />
      <span className="font-mono">
        {live.length}/{rows.length} live
      </span>
    </Link>
  );
}

function TopBar() {
  const today = useToday();

  return (
    <header
      className="sticky top-0 z-30 flex min-h-14 items-center justify-between gap-3 border-b border-border bg-bg/85 px-4 backdrop-blur-md lg:px-6"
      style={{
        // The layout sets viewportFit: "cover", so on a notched phone the page
        // extends beneath the status bar. Without these the wordmark collides
        // with the clock and the controls sit under the battery icon.
        paddingTop: "env(safe-area-inset-top)",
        paddingLeft: "max(1rem, env(safe-area-inset-left))",
        paddingRight: "max(1rem, env(safe-area-inset-right))",
      }}
    >
      <div className="flex items-center gap-2 lg:hidden">
        <span className="grid size-7 place-items-center rounded-lg bg-text text-bg">
          <Sparkles className="size-4" />
        </span>
        <span className="text-[15px] font-semibold tracking-tight">Orion</span>
      </div>
      <div className="hidden text-[13px] text-muted lg:block">
        <span className="font-mono text-faint">{today ?? ""}</span>
      </div>
      <div className="flex items-center gap-2">
        <SyncChip />
        <ThemeToggle />
        <Link href="/settings" aria-label="Profile" className="grid size-8 place-items-center rounded-full bg-surface-2 text-[12px] font-semibold text-text ring-1 ring-border">
          D
        </Link>
      </div>
    </header>
  );
}

/* ========================================================= BottomNav */
function BottomNav() {
  const isActive = useActive();
  const [moreOpen, setMoreOpen] = useState(false);

  return (
    <>
      <nav className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-surface/95 backdrop-blur-md lg:hidden" style={{ paddingBottom: "env(safe-area-inset-bottom)" }}>
        <ul className="mx-auto grid max-w-md grid-cols-5">
          {MOBILE_NAV.map((item) => {
            const Icon = item.icon;
            const active = item.key === "more" ? moreOpen : isActive(item.href);
            const isLog = item.key === "log";
            if (item.key === "more") {
              return (
                <li key="more">
                  <button onClick={() => setMoreOpen(true)} className={cn("flex w-full flex-col items-center gap-0.5 py-2 text-[10px] font-medium", active ? "text-text" : "text-faint")}>
                    <Icon className="size-5" />
                    {item.label}
                  </button>
                </li>
              );
            }
            return (
              <li key={item.key} className="grid place-items-center">
                <Link href={item.href} aria-current={active ? "page" : undefined} className={cn("flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium", isLog ? "-mt-4" : "", active ? "text-text" : "text-faint")}>
                  {isLog ? (
                    <span className="grid size-11 place-items-center rounded-full bg-text text-bg shadow-[var(--shadow-md)]">
                      <Icon className="size-5" />
                    </span>
                  ) : (
                    <Icon className="size-5" />
                  )}
                  <span className={isLog ? "mt-0.5" : ""}>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>

      {moreOpen && (
        <div className="fixed inset-0 z-50 lg:hidden" role="dialog" aria-modal="true">
          <div className="absolute inset-0 bg-[var(--overlay)]" onClick={() => setMoreOpen(false)} />
          <div className="absolute inset-x-0 bottom-0 max-h-[80svh] overflow-y-auto rounded-t-2xl border-t border-border bg-surface p-4 rise" style={{ paddingBottom: "calc(env(safe-area-inset-bottom) + 1rem)" }}>
            <div className="mx-auto mb-3 h-1 w-9 rounded-full bg-border-strong" />
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-[15px] font-semibold">More</h2>
              <button onClick={() => setMoreOpen(false)} aria-label="Close" className="grid size-8 place-items-center rounded-full text-faint hover:bg-surface-2">
                <X className="size-4" />
              </button>
            </div>
            <div className="grid grid-cols-3 gap-2">
              {MORE_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <Link key={item.key} href={item.href} onClick={() => setMoreOpen(false)} className="flex flex-col items-center gap-1.5 rounded-xl border border-border bg-surface-2 px-2 py-3 text-center text-[11px] font-medium text-muted hover:text-text">
                    <Icon className="size-5" />
                    {item.label}
                  </Link>
                );
              })}
            </div>
          </div>
        </div>
      )}
    </>
  );
}

/* ========================================================= AppShell */
export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-svh">
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar />
        <main className="flex-1 pb-24 lg:pb-0">{children}</main>
        <BottomNav />
      </div>
    </div>
  );
}

/* ======================================================= Page + Rail */
export function Page({
  title,
  eyebrow,
  children,
  rail,
}: {
  title: string;
  eyebrow?: string;
  children: ReactNode;
  rail?: ReactNode;
}) {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      <div className="mb-4">
        {eyebrow && <p className="text-[12px] font-medium text-muted">{eyebrow}</p>}
        <h1 className="text-2xl font-semibold tracking-tight text-text lg:text-[28px]">{title}</h1>
      </div>
      {rail ? (
        <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_var(--rail-w)]">
          <div className="min-w-0 space-y-5">{children}</div>
          <aside className="space-y-4 xl:sticky xl:top-[4.5rem] xl:h-fit">{rail}</aside>
        </div>
      ) : (
        <div className="space-y-5">{children}</div>
      )}
    </div>
  );
}
