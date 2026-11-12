"use client";

import { useEffect, useState } from "react";

import { checkReadiness, type ReadinessState } from "@/lib/api";

type DisplayState = ReadinessState | "checking" | "misconfigured";

const MESSAGES: Record<DisplayState, { label: string; tone: string }> = {
  checking: { label: "Connecting to the pit wall…", tone: "bg-zinc-500" },
  ready: { label: "All systems go", tone: "bg-emerald-500" },
  database_unavailable: {
    label: "Backend is up, but the database is unavailable",
    tone: "bg-amber-500",
  },
  unreachable: { label: "Can't reach the backend", tone: "bg-red-500" },
  unexpected_response: {
    label: "Backend sent an unexpected response",
    tone: "bg-red-500",
  },
  misconfigured: {
    label: "Frontend is misconfigured (backend URL missing or invalid)",
    tone: "bg-red-500",
  },
};

interface BackendStatusProps {
  /** Validated backend URL, or null if config is invalid. */
  apiBaseUrl: string | null;
}

export function BackendStatus({ apiBaseUrl }: BackendStatusProps) {
  const [state, setState] = useState<DisplayState>(
    apiBaseUrl ? "checking" : "misconfigured",
  );
  // Bumped by "Retry" to re-run the check effect.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Runs on page load (state starts as "checking") and on each retry. The
    // first call also wakes a suspended Neon database before the user asks
    // anything. State is only set from the promise callback, once settled.
    if (!apiBaseUrl) return;
    const controller = new AbortController();
    checkReadiness(apiBaseUrl, { signal: controller.signal }).then((result) => {
      if (!controller.signal.aborted) setState(result);
    });
    return () => controller.abort();
  }, [apiBaseUrl, attempt]);

  const retry = () => {
    setState("checking");
    setAttempt((n) => n + 1);
  };

  const { label, tone } = MESSAGES[state];
  const canRetry = apiBaseUrl !== null && state !== "checking" && state !== "ready";

  return (
    <div
      className="flex items-center gap-3 rounded-full border border-zinc-800 bg-zinc-900/60 px-4 py-2 text-sm"
      role="status"
      aria-live="polite"
    >
      <span
        className={`h-2.5 w-2.5 rounded-full ${tone} ${state === "checking" ? "animate-pulse" : ""}`}
        aria-hidden="true"
      />
      <span data-testid="backend-status" data-state={state}>
        {label}
      </span>
      {canRetry && (
        <button
          type="button"
          onClick={retry}
          className="ml-1 rounded-full border border-zinc-700 px-3 py-0.5 text-xs text-zinc-300 hover:border-zinc-500 hover:text-white"
        >
          Retry
        </button>
      )}
    </div>
  );
}
