/**
 * Client for `POST /api/feedback` (backend F4.3): a thumbs up or down on an answer.
 *
 * The backend keeps the question (≤ 500 characters), the first 500
 * characters of the answer, and which provider/model wrote it, for 90 days.
 * Fields are clipped to the backend's limits here, so a long answer or a long
 * rewritten question never turns into a 422.
 */

import { detail, isNumber, isObject, retryAfter } from "./chat";

export const MAX_FEEDBACK_QUESTION_CHARS = 500;
export const MAX_FEEDBACK_ANSWER_CHARS = 8000;
export const FEEDBACK_TIMEOUT_MS = 10_000;

export type Rating = "up" | "down";

export interface FeedbackRequest {
  rating: Rating;
  question: string;
  answer: string;
  provider?: string;
  model?: string;
}

export class FeedbackError extends Error {
  constructor(
    message: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "FeedbackError";
  }
}

const clip = (text: string, max: number) =>
  Array.from(text.trim()).slice(0, max).join("");

/** The JSON body: trimmed, clipped, and without empty optional fields. */
export function feedbackBody(request: FeedbackRequest): Record<string, string> {
  const body: Record<string, string> = {
    rating: request.rating,
    question: clip(request.question, MAX_FEEDBACK_QUESTION_CHARS),
    answer: clip(request.answer, MAX_FEEDBACK_ANSWER_CHARS),
  };
  const provider = request.provider?.trim();
  const model = request.model?.trim();
  if (provider) body.provider = provider;
  if (model) body.model = model;
  return body;
}

interface SendOptions {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

/** Send one rating; resolves to the stored id, or throws FeedbackError. */
export async function sendFeedback(
  baseUrl: string,
  request: FeedbackRequest,
  { fetchImpl = fetch, timeoutMs = FEEDBACK_TIMEOUT_MS }: SendOptions = {},
): Promise<number> {
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/feedback`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(feedbackBody(request)),
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch {
    throw new FeedbackError("Couldn't send your feedback. Check your connection.");
  }

  if (response.status === 429) {
    const seconds = retryAfter(response);
    throw new FeedbackError(
      `Too much feedback for now. Try again in ${seconds} seconds.`,
      seconds,
    );
  }
  if (response.status === 503) {
    throw new FeedbackError(
      (await detail(response)) ?? "Feedback couldn't be saved right now.",
    );
  }
  if (!response.ok) {
    throw new FeedbackError(`Couldn't send your feedback (HTTP ${response.status}).`);
  }
  try {
    const body: unknown = await response.json();
    if (isObject(body) && isNumber(body.id)) return body.id;
  } catch {
    // fall through
  }
  throw new FeedbackError("Couldn't send your feedback (unexpected response).");
}
