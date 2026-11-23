import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  ChatError,
  type ChatEvent,
  type ChatRequest,
  type DoneInfo,
  type streamChat,
} from "@/lib/chat";

import { Chat } from "./Chat";

const BASE = "http://backend.test";
const INFO: DoneInfo = {
  question: "q",
  provider: "groq",
  model: "m",
  sources: [],
  tools: [],
  latencyMs: 1,
  promptTokens: 1,
  completionTokens: 1,
  cached: false,
};

/** A controllable fake of streamChat: the test pushes events or ends it. */
class FakeStream {
  requests: ChatRequest[] = [];
  signals: AbortSignal[] = [];
  private queue: (ChatEvent | Error)[] = [];
  private wake: (() => void) | null = null;

  push(...items: (ChatEvent | Error)[]) {
    this.queue.push(...items);
    this.wake?.();
  }

  readonly fn = ((
    _base: string,
    request: ChatRequest,
    options?: { signal?: AbortSignal },
  ) => {
    this.requests.push(request);
    const signal = options?.signal ?? new AbortController().signal;
    this.signals.push(signal);
    signal.addEventListener("abort", () => this.wake?.());
    return this.events(signal);
  }) as unknown as typeof streamChat;

  private async *events(signal: AbortSignal): AsyncGenerator<ChatEvent> {
    while (true) {
      if (signal.aborted) throw new DOMException("aborted", "AbortError");
      const item = this.queue.shift();
      if (item === undefined) {
        await new Promise<void>((resolve) => (this.wake = resolve));
        continue;
      }
      if (item instanceof Error) throw item;
      yield item;
      if (item.type === "done") return;
    }
  }
}

function setup(apiBaseUrl: string | null = BASE) {
  const fake = new FakeStream();
  const user = userEvent.setup();
  render(<Chat apiBaseUrl={apiBaseUrl} stream={fake.fn} />);
  return { fake, user, input: screen.getByLabelText("Your question") };
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Chat", () => {
  it("shows a prompt before the first question", () => {
    setup();

    expect(screen.getByText(/Ask about any driver/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });

  it("sends a question with Enter and streams the answer", async () => {
    const { fake, user, input } = setup();

    await user.type(input, "  Who won 1976?  {Enter}");

    expect(fake.requests).toEqual([{ question: "Who won 1976?", history: [] }]);
    expect(input).toHaveValue("");
    expect(screen.getByText("Who won 1976?")).toBeInTheDocument();
    expect(screen.getByText("Thinking…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeInTheDocument();

    act(() => fake.push({ type: "tool", name: "query_stats", status: "started" }));
    expect(await screen.findByText("Checking the stats…")).toBeInTheDocument();

    act(() => fake.push({ type: "tool", name: "query_stats", status: "finished", ok: true },
                        { type: "token", text: "James Hunt " })); // prettier-ignore
    expect(await screen.findByText("James Hunt")).toBeInTheDocument();

    act(() =>
      fake.push({ type: "token", text: "won by a point." }, { type: "done", info: INFO }),
    );
    expect(await screen.findByText("James Hunt won by a point.")).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument(),
    );
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();
  });

  it("keeps Shift+Enter as a new line", async () => {
    const { fake, user, input } = setup();

    await user.type(input, "line one{Shift>}{Enter}{/Shift}line two");

    expect(input).toHaveValue("line one\nline two");
    expect(fake.requests).toEqual([]);
  });

  it("sends the finished exchanges as history for a follow-up", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "Who won 1988?{Enter}");
    act(() =>
      fake.push({ type: "token", text: "Ayrton Senna." }, { type: "done", info: INFO }),
    );
    await screen.findByText("Ayrton Senna.");

    await user.type(input, "How many poles did he get?{Enter}");
    act(() =>
      fake.push({
        type: "question",
        text: "How many poles did Ayrton Senna get in 1988?",
      }),
    );

    expect(fake.requests[1]).toEqual({
      question: "How many poles did he get?",
      history: [
        { role: "user", content: "Who won 1988?" },
        { role: "assistant", content: "Ayrton Senna." },
      ],
    });
    expect(
      await screen.findByText("Answering: How many poles did Ayrton Senna get in 1988?"),
    ).toBeInTheDocument();
  });

  it("can stop an answer, keeping what arrived", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "Explain Abu Dhabi 2021{Enter}");
    act(() => fake.push({ type: "token", text: "The title decider" }));
    await screen.findByText("The title decider");

    await user.click(screen.getByRole("button", { name: "Stop" }));

    expect(fake.signals[0].aborted).toBe(true);
    expect(await screen.findByText("Stopped.")).toBeInTheDocument();
    expect(screen.getByText("The title decider")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument();
  });

  it("shows the backend's error message", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "q{Enter}");

    act(() =>
      fake.push(new ChatError("answer_error", "All providers failed; please try again")),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "All providers failed; please try again",
    );
  });

  it("shows a generic message for an unexpected failure", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "q{Enter}");

    act(() => fake.push(new TypeError("x is undefined")));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Something went wrong. Please try again.",
    );
  });

  it("blocks sending until a rate limit has passed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const { fake, user, input } = setup();
    await user.type(input, "q{Enter}");
    act(() =>
      fake.push(
        new ChatError(
          "rate_limited",
          "Too many questions for now. Try again in 30 seconds.",
          30,
        ),
      ),
    );
    await screen.findByRole("alert");

    await user.type(input, "next");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();

    act(() => vi.advanceTimersByTime(30_000));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "Send" })).toBeEnabled(),
    );
  });

  it("shows a counter near the limit and won't send past it", async () => {
    const { fake, user, input } = setup();

    await user.click(input);
    await user.paste("x".repeat(450));
    expect(screen.getByText("450/500")).toBeInTheDocument();

    await user.paste("x".repeat(60));
    expect(screen.getByText("510/500")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.keyboard("{Enter}");
    expect(fake.requests).toEqual([]);
  });

  it("doesn't send while an answer is streaming", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "first{Enter}");

    await user.type(input, "second{Enter}");

    expect(fake.requests).toHaveLength(1);
    expect(input).toHaveValue("second");
  });

  it("marks a cached answer", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "q{Enter}");

    act(() =>
      fake.push(
        { type: "token", text: "A." },
        { type: "done", info: { ...INFO, cached: true } },
      ),
    );

    expect(await screen.findByText("Answered from cache")).toBeInTheDocument();
  });

  it("is disabled when the frontend is misconfigured", () => {
    const { input } = setup(null);

    expect(input).toBeDisabled();
    expect(input).toHaveAttribute(
      "placeholder",
      "Chat is unavailable (frontend misconfigured)",
    );
  });

  it("stops the answer when the page goes away", async () => {
    const fake = new FakeStream();
    const user = userEvent.setup();
    const { unmount } = render(<Chat apiBaseUrl={BASE} stream={fake.fn} />);
    await user.type(screen.getByLabelText("Your question"), "q{Enter}");

    unmount();

    expect(fake.signals[0].aborted).toBe(true);
  });
});
