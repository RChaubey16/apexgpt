import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ChatError } from "@/lib/chat";
import type { sendFeedback } from "@/lib/feedback";
import { FakeStream, INFO } from "@/test/stream";

import type { Message } from "@/lib/conversation";

import { Chat } from "./Chat";

const BASE = "http://backend.test";

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
    expect(screen.getByRole("list", { name: "Starter questions" })).toBeInTheDocument();
  });

  it("asks a starter question when its card is picked, then hides the cards", async () => {
    const { fake, user, input } = setup();
    await user.type(input, "my draft");

    await user.click(screen.getByRole("button", { name: /Abu Dhabi 2021/ }));

    expect(fake.requests).toEqual([
      { question: "Explain the 2021 Abu Dhabi Grand Prix controversy", history: [] },
    ]);
    expect(
      screen.getByText("Explain the 2021 Abu Dhabi Grand Prix controversy"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Starter questions" }),
    ).not.toBeInTheDocument();
    expect(input).toHaveValue("my draft"); // a draft isn't thrown away
  });

  it("disables the starter cards when the frontend is misconfigured", async () => {
    const { fake, user } = setup(null);

    const card = screen.getByRole("button", { name: /Abu Dhabi 2021/ });
    expect(card).toBeDisabled();
    await user.click(card);
    expect(fake.requests).toEqual([]);
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

describe("Chat with a saved conversation", () => {
  const saved: Message[] = [
    { id: "q1", role: "user", content: "Who won 1976?" },
    {
      id: "a1",
      role: "assistant",
      status: "done",
      content: "James Hunt.",
      tables: [],
      citations: [],
    },
  ];

  function mount(initialMessages?: Message[]) {
    const fake = new FakeStream();
    const reports: Message[][] = [];
    const user = userEvent.setup();
    const view = render(
      <Chat
        apiBaseUrl={BASE}
        stream={fake.fn}
        initialMessages={initialMessages}
        onMessagesChange={(m) => reports.push(m)}
      />,
    );
    return { fake, reports, user, view, input: screen.getByLabelText("Your question") };
  }

  it("shows the saved messages and continues the conversation", async () => {
    const { fake, user, input, reports } = mount(saved);

    expect(screen.getByText("James Hunt.")).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: "Starter questions" }),
    ).not.toBeInTheDocument();
    expect(reports).toEqual([]); // nothing changed yet

    await user.type(input, "By how much?{Enter}");

    expect(fake.requests[0].history).toEqual([
      { role: "user", content: "Who won 1976?" },
      { role: "assistant", content: "James Hunt." },
    ]);
  });

  it("reports the question and the finished answer, not every token", async () => {
    const { fake, user, input, reports } = mount();

    await user.type(input, "Who won 1976?{Enter}");
    expect(reports).toHaveLength(1);
    expect(reports[0].map((m) => m.role)).toEqual(["user", "assistant"]);

    act(() =>
      fake.push({ type: "token", text: "James " }, { type: "token", text: "Hunt." }),
    );
    await screen.findByText("James Hunt.");
    expect(reports).toHaveLength(1);

    act(() => fake.push({ type: "done", info: INFO }));
    await waitFor(() => expect(reports).toHaveLength(2));
    expect(reports[1][1]).toMatchObject({ status: "done", content: "James Hunt." });
  });

  it("reports what had arrived when it unmounts mid-answer, and stops the answer", async () => {
    const { fake, user, input, reports, view } = mount();
    await user.type(input, "Who won 1976?{Enter}");
    act(() => fake.push({ type: "token", text: "James" }));
    await screen.findByText("James");

    view.unmount();

    expect(fake.signals[0].aborted).toBe(true);
    expect(reports).toHaveLength(2);
    expect(reports[1][1]).toMatchObject({ status: "streaming", content: "James" });
  });

  it("doesn't report on unmount when nothing changed", () => {
    const { reports, view } = mount(saved);

    view.unmount();

    expect(reports).toEqual([]);
  });
});

describe("Chat answer actions", () => {
  it("rates a finished answer once, and reports the rating to be saved", async () => {
    const fake = new FakeStream();
    const send = vi.fn<typeof sendFeedback>(async () => 1);
    const reports: Message[][] = [];
    const user = userEvent.setup();
    render(
      <Chat
        apiBaseUrl={BASE}
        stream={fake.fn}
        feedback={send}
        onMessagesChange={(m) => reports.push(m)}
      />,
    );
    await user.type(screen.getByLabelText("Your question"), "Who won 1976?{Enter}");
    expect(screen.queryByRole("button", { name: "Good answer" })).not.toBeInTheDocument();
    act(() =>
      fake.push(
        { type: "token", text: "James Hunt." },
        { type: "done", info: { ...INFO, question: "Who won the 1976 title?" } },
      ),
    );

    await user.click(await screen.findByRole("button", { name: "Good answer" }));

    expect(send).toHaveBeenCalledExactlyOnceWith(BASE, {
      rating: "up",
      question: "Who won the 1976 title?",
      answer: "James Hunt.",
      provider: INFO.provider,
      model: INFO.model,
    });
    expect(await screen.findByText("Thanks for the feedback.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Good answer" })).toBeDisabled();
    await waitFor(() =>
      expect(reports.at(-1)![1]).toMatchObject({ status: "done", feedback: "up" }),
    );
  });

  it("passes the user's own question when the answer has no details", async () => {
    const send = vi.fn<typeof sendFeedback>(async () => 1);
    const user = userEvent.setup();
    render(
      <Chat
        apiBaseUrl={BASE}
        feedback={send}
        initialMessages={[
          { id: "q1", role: "user", content: "Who won 1988?" },
          {
            id: "a1",
            role: "assistant",
            status: "done",
            content: "Ayrton Senna.",
            tables: [],
            citations: [],
          },
        ]}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Bad answer" }));

    expect(send.mock.calls[0][1]).toMatchObject({ question: "Who won 1988?" });
  });
});

describe("pit wall layout (F8.4b)", () => {
  const saved: Message[] = [
    { id: "q1", role: "user", content: "Who won 1976?" },
    {
      id: "a1",
      role: "assistant",
      status: "done",
      content: "James Hunt.",
      citations: [],
      tables: [],
    },
    { id: "q2", role: "user", content: "And 1977?" },
    {
      id: "a2",
      role: "assistant",
      status: "error",
      content: "",
      citations: [],
      tables: [],
      error: "Too many questions",
    },
  ];

  it("announces each question as the user's, now they aren't bubbles", () => {
    render(<Chat apiBaseUrl={BASE} initialMessages={saved} />);

    const question = screen.getByText("Who won 1976?").parentElement;
    expect(question).toHaveTextContent("You asked: Who won 1976?");
  });

  it("marks each answer's state for its timing-tower stripe", () => {
    const { container } = render(<Chat apiBaseUrl={BASE} initialMessages={saved} />);

    const states = [...container.querySelectorAll("article")].map((a) =>
      a.getAttribute("data-status"),
    );
    expect(states).toEqual(["done", "error"]);
  });
});
