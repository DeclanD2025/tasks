"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useEffect, useState } from "react";
import { cn } from "@/lib/cn";

type Mode = "light" | "dark" | "system";

/** Inline script (no-flash): resolves theme before first paint. */
export const themeScript = `(function(){try{var m=localStorage.getItem('orion-theme')||'system';var d=window.matchMedia('(prefers-color-scheme: dark)').matches;var t=m==='system'?(d?'dark':'light'):m;document.documentElement.setAttribute('data-theme',t);}catch(e){}})();`;

function apply(mode: Mode) {
  const dark = window.matchMedia("(prefers-color-scheme: dark)").matches;
  const t = mode === "system" ? (dark ? "dark" : "light") : mode;
  document.documentElement.setAttribute("data-theme", t);
}

export function ThemeToggle() {
  const [mode, setMode] = useState<Mode>("system");

  useEffect(() => {
    const stored = (localStorage.getItem("orion-theme") as Mode) || "system";
    setMode(stored);
  }, []);

  function choose(next: Mode) {
    setMode(next);
    localStorage.setItem("orion-theme", next);
    apply(next);
  }

  const opts: { key: Mode; icon: typeof Sun; label: string }[] = [
    { key: "light", icon: Sun, label: "Light" },
    { key: "dark", icon: Moon, label: "Dark" },
    { key: "system", icon: Monitor, label: "System" },
  ];

  return (
    <div className="inline-flex items-center gap-0.5 rounded-full border border-border bg-surface-2 p-0.5" role="group" aria-label="Theme">
      {opts.map(({ key, icon: Icon, label }) => (
        <button
          key={key}
          type="button"
          onClick={() => choose(key)}
          aria-pressed={mode === key}
          aria-label={label}
          title={label}
          className={cn(
            "grid size-7 place-items-center rounded-full transition-colors",
            mode === key ? "bg-surface text-text shadow-[var(--shadow-sm)]" : "text-faint hover:text-muted",
          )}
        >
          <Icon className="size-3.5" />
        </button>
      ))}
    </div>
  );
}
