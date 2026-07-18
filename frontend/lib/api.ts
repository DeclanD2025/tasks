"use client";

/**
 * The client's only door to ORION.
 *
 * This app is a static export served by the FastAPI process that owns the
 * data, so every call is same-origin and carries the session cookie
 * automatically. The API lives at the origin root (`/api/v2/...`) while the UI
 * itself is served under a base path (`/v2`), so paths here are deliberately
 * absolute and must not be prefixed.
 *
 * Payloads arrive already shaped by `app/web/ui_models.py` — this layer does no
 * arithmetic and no reshaping. If a number looks wrong, it is wrong in Python.
 */
import { useEffect, useState } from "react";

export type Loadable<T> = {
  data: T | null;
  error: string | null;
  loading: boolean;
};

export class SessionExpired extends Error {
  constructor() {
    super("Session expired");
    this.name = "SessionExpired";
  }
}

export async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(`/api/v2${path}`, {
    signal,
    credentials: "same-origin",
    headers: { Accept: "application/json" },
  });
  if (response.status === 401) throw new SessionExpired();
  if (!response.ok) {
    throw new Error(`ORION returned ${response.status} for ${path}`);
  }
  return (await response.json()) as T;
}

/**
 * Fetch one endpoint for the lifetime of a page.
 *
 * On an expired session it sends the browser to the login page rather than
 * rendering a broken screen — the user's session outliving the tab is the
 * common case, not an error worth reporting to them.
 */
export function useApi<T>(path: string): Loadable<T> {
  // The result carries the path it belongs to, so a result for a previous path
  // reads as "still loading" without the effect having to set state up front.
  const [result, setResult] = useState<{
    path: string;
    data: T | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    getJson<T>(path, controller.signal)
      .then((data) => setResult({ path, data, error: null }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        if (err instanceof SessionExpired) {
          window.location.href = "/login";
          return;
        }
        setResult({
          path,
          data: null,
          error: err instanceof Error ? err.message : "Could not reach ORION",
        });
      });
    return () => controller.abort();
  }, [path]);

  if (!result || result.path !== path) {
    return { data: null, error: null, loading: true };
  }
  return { data: result.data, error: result.error, loading: false };
}
