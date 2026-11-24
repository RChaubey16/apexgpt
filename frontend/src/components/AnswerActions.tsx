"use client";

/**
 * Actions under an answer: Copy, and 👍/👎 feedback.
 *
 * - Copy puts the answer's markdown on the clipboard, followed by its cited
 *   sources ("[S1] Title › Section — URL"), so the [S#] markers still mean
 *   something once pasted.
 * - Feedback: one rating per answer. It is recorded on the answer (and so in
 *   the saved chat) only once the backend has stored it; on failure the
 *   buttons come back with the reason. Only finished answers can be rated.
 */

import { useEffect, useState } from "react";

import type { AssistantMessage } from "@/lib/conversation";
import { FeedbackError, sendFeedback, type Rating } from "@/lib/feedback";

import { sourceLabel } from "./AnswerContent";

const COPIED_MS = 2000;

/** The answer as copied: its text, then the sources it cites. */
export function copyText(answer: AssistantMessage): string {
  const text = answer.content.trim();
  if (answer.citations.length === 0) return text;
  const sources = answer.citations.map((s) => `[${s.id}] ${sourceLabel(s)} — ${s.url}`);
  return `${text}\n\nSources:\n${sources.join("\n")}`;
}

interface AnswerActionsProps {
  answer: AssistantMessage;
  /** The question this answers, as the user asked it. */
  question: string;
  /** Validated backend URL, or null if config is invalid. */
  apiBaseUrl: string | null;
  onRated: (rating: Rating) => void;
  /** For tests: the feedback client. */
  send?: typeof sendFeedback;
}

const actionButton =
  "inline-flex h-7 items-center gap-1 rounded-md px-2 text-xs text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200 disabled:cursor-not-allowed disabled:hover:bg-transparent";

export function AnswerActions({
  answer,
  question,
  apiBaseUrl,
  onRated,
  send = sendFeedback,
}: AnswerActionsProps) {
  const [copy, setCopy] = useState<"idle" | "copied" | "failed">("idle");
  const [sending, setSending] = useState<Rating | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (copy === "idle") return;
    const timer = setTimeout(() => setCopy("idle"), COPIED_MS);
    return () => clearTimeout(timer);
  }, [copy]);

  if (
    !answer.content.trim() ||
    (answer.status !== "done" && answer.status !== "stopped")
  ) {
    return null;
  }

  const doCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyText(answer));
      setCopy("copied");
    } catch {
      setCopy("failed"); // no clipboard (insecure page) or permission refused
    }
  };

  const rate = async (rating: Rating) => {
    if (!apiBaseUrl) return; // not offered then; narrows the type
    // A second click can't happen: the buttons are disabled while sending and once rated.
    setSending(rating);
    setError(null);
    try {
      await send(apiBaseUrl, {
        rating,
        question: answer.done?.question || question,
        answer: answer.content,
        provider: answer.done?.provider,
        model: answer.done?.model,
      });
      onRated(rating);
    } catch (e) {
      setError(e instanceof FeedbackError ? e.message : "Couldn't send your feedback.");
    } finally {
      setSending(null);
    }
  };

  const canRate = answer.status === "done" && apiBaseUrl !== null;
  const rated = answer.feedback;

  return (
    <div className="flex flex-wrap items-center gap-1">
      <button type="button" onClick={doCopy} className={actionButton}>
        {copy === "copied" ? "✓ Copied" : copy === "failed" ? "Couldn't copy" : "Copy"}
      </button>
      {canRate && (
        <>
          {(["up", "down"] as const).map((rating) => (
            <button
              key={rating}
              type="button"
              onClick={() => rate(rating)}
              disabled={sending !== null || rated !== undefined}
              aria-pressed={rated === rating}
              aria-label={rating === "up" ? "Good answer" : "Bad answer"}
              className={`${actionButton} ${rated === rating ? "bg-zinc-800 text-zinc-100" : ""} ${rated && rated !== rating ? "opacity-40" : ""}`}
            >
              <span aria-hidden="true">{rating === "up" ? "👍" : "👎"}</span>
            </button>
          ))}
          {rated && (
            <span className="text-xs text-zinc-500" role="status">
              Thanks for the feedback.
            </span>
          )}
          {sending && (
            <span className="text-xs text-zinc-500" role="status">
              Sending…
            </span>
          )}
        </>
      )}
      {error && (
        <span className="text-xs text-red-400" role="alert">
          {error}
        </span>
      )}
    </div>
  );
}
