import { describe, expect, it, vi } from "vitest";

import {
  FeedbackError,
  feedbackBody,
  sendFeedback,
  type FeedbackRequest,
} from "./feedback";

const BASE = "http://backend.test";
const REQUEST: FeedbackRequest = {
  rating: "up",
  question: "Who won the 1976 title?",
  answer: "James Hunt, by one point.",
  provider: "groq",
  model: "openai/gpt-oss-120b",
};

function respond(status: number, body?: unknown, headers: Record<string, string> = {}) {
  return vi.fn<typeof fetch>(
    async () =>
      new Response(body === undefined ? null : JSON.stringify(body), {
        status,
        headers: { "Content-Type": "application/json", ...headers },
      }),
  );
}

async function failure(promise: Promise<unknown>): Promise<FeedbackError> {
  try {
    await promise;
  } catch (error) {
    expect(error).toBeInstanceOf(FeedbackError);
    return error as FeedbackError;
  }
  throw new Error("expected a FeedbackError");
}

describe("feedbackBody", () => {
  it("sends the rating, question, answer and model", () => {
    expect(feedbackBody(REQUEST)).toEqual(REQUEST);
  });

  it("trims, clips to the backend's limits, and leaves out empty optional fields", () => {
    const body = feedbackBody({
      rating: "down",
      question: `  ${"q".repeat(600)}  `,
      answer: "a".repeat(9000),
      provider: "  ",
      model: undefined,
    });

    expect(body.question).toHaveLength(500);
    expect(body.answer).toHaveLength(8000);
    expect(body).not.toHaveProperty("provider");
    expect(body).not.toHaveProperty("model");
  });

  it("clips by character, so an emoji isn't split", () => {
    const body = feedbackBody({ ...REQUEST, question: "🏁".repeat(600) });

    expect(Array.from(body.question)).toHaveLength(500);
    expect(body.question).toBe("🏁".repeat(500));
  });
});

describe("sendFeedback", () => {
  it("posts the feedback and returns the stored id", async () => {
    const fetchImpl = respond(201, { id: 42 });

    await expect(sendFeedback(BASE, REQUEST, { fetchImpl })).resolves.toBe(42);

    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/feedback`);
    expect(init).toMatchObject({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      cache: "no-store",
    });
    expect(JSON.parse(init!.body as string)).toEqual(REQUEST);
    expect(init!.signal).toBeInstanceOf(AbortSignal);
  });

  it("says when to try again after a 429", async () => {
    const error = await failure(
      sendFeedback(BASE, REQUEST, {
        fetchImpl: respond(429, { detail: "x" }, { "Retry-After": "17" }),
      }),
    );

    expect(error.message).toBe("Too much feedback for now. Try again in 17 seconds.");
    expect(error.retryAfterSeconds).toBe(17);
  });

  it("shows the backend's message when it can't store feedback", async () => {
    const error = await failure(
      sendFeedback(BASE, REQUEST, {
        fetchImpl: respond(503, { detail: "Feedback could not be saved right now" }),
      }),
    );

    expect(error.message).toBe("Feedback could not be saved right now");
  });

  it.each([
    ["another status", respond(500, { detail: "secret internals" }), "HTTP 500"],
    ["a body without an id", respond(201, { ok: true }), "unexpected response"],
    [
      "a body that isn't JSON",
      vi.fn<typeof fetch>(async () => new Response("<html>")),
      "unexpected response",
    ],
    [
      "a network error",
      vi.fn<typeof fetch>(async () => {
        throw new TypeError("Failed to fetch");
      }),
      "Check your connection",
    ],
  ])("fails with a safe message for %s", async (_, fetchImpl, message) => {
    const error = await failure(sendFeedback(BASE, REQUEST, { fetchImpl }));

    expect(error.message).toContain(message);
    expect(error.message).not.toContain("secret");
  });

  it("gives up after the timeout", async () => {
    const fetchImpl = vi.fn<typeof fetch>(
      (_url, init) =>
        new Promise((_, reject) =>
          init!.signal!.addEventListener("abort", () => reject(init!.signal!.reason)),
        ),
    );

    const error = await failure(
      sendFeedback(BASE, REQUEST, { fetchImpl, timeoutMs: 10 }),
    );

    expect(error.message).toContain("Check your connection");
  });
});
