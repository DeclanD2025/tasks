"use client";

/**
 * Load states, shared so every screen fails the same way.
 *
 * ORION shows nothing rather than something plausible: a page that cannot
 * reach the backend says so, and a metric with no readings says it has none.
 * Neither ever falls back to a placeholder number.
 */
import { AlertTriangle } from "lucide-react";
import type { ReactNode } from "react";
import type { Loadable } from "@/lib/api";
import { cn } from "@/lib/cn";

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("animate-pulse rounded-md bg-surface-2", className)} />;
}

export function PageSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      <Skeleton className="h-7 w-48" />
      <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-32" />
        ))}
      </div>
      <Skeleton className="mt-5 h-64" />
      <span className="sr-only">Loading</span>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-5 lg:px-6 lg:py-6">
      <div className="flex items-start gap-3 rounded-xl border border-border bg-surface p-4">
        <AlertTriangle className="mt-0.5 size-4 shrink-0 text-warn" />
        <div>
          <p className="text-[14px] font-medium text-text">Could not load this page</p>
          <p className="mt-0.5 text-[12.5px] text-muted">{message}</p>
          <button
            onClick={() => window.location.reload()}
            className="mt-2.5 rounded-md border border-border bg-surface-2 px-2.5 py-1 text-[12px] font-medium text-text hover:bg-surface"
          >
            Try again
          </button>
        </div>
      </div>
    </div>
  );
}

/** Render `children` only once the data is really there. */
export function Loaded<T>({
  state,
  children,
  skeleton,
}: {
  state: Loadable<T>;
  children: (data: T) => ReactNode;
  skeleton?: ReactNode;
}) {
  if (state.error) return <ErrorState message={state.error} />;
  if (state.loading || state.data === null) return <>{skeleton ?? <PageSkeleton />}</>;
  return <>{children(state.data)}</>;
}
