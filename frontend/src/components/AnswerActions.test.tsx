import { act, fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssistantMessage } from "@/lib/conversation";
import { FeedbackError, type Rating, type sendFeedback } from "@/lib/feedback";
import { INFO } from "@/test/stream";

import { AnswerActions, copyText } from "./AnswerActions";

const BASE = "http://backend.test";
const SOURCE = {
  id: "S1",
  title: "1976 Japanese Grand Prix",
  url: "https://en.wikipedia.org/wiki/1976_Japanese_Grand_Prix",
  section: "Race",
  season: 1976,
};

function answer(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "a1",
    role: "assistant",
    status: "done",
    content: "James Hunt won by one point [S1].",
    tables: [],
    citations: [SOURCE],
    done: {
      ...INFO,
      question: "Who won the 1976 drivers' title?",
      provider: "groq",
      model: "gpt",
    },
    ...overrides,
  };
}

function show(
  a: AssistantMessage = answer(),
  {
    send = vi.fn<typeof sendFeedback>(async () => 1),
    apiBaseUrl = BASE as string | null,
  } = {},
) {
  const onRated = vi.fn<(rating: Rating) => void>();
  const view = render(
    <AnswerActions
      answer={a}
      question="And 1976?"
      apiBaseUrl={apiBaseUrl}
      onRated={onRated}
      send={send}
    />,
  );
  return { send, onRated, view };
}

afterEach(() => vi.useRealTimers());

describe("copyText", () => {
  it("is the answer, then its sources", () => {
    expect(copyText(answer())).toBe(
      "James Hunt won by one point [S1].\n\nSources:\n[S1] 1976 Japanese Grand Prix › Race — https://en.wikipedia.org/wiki/1976_Japanese_Grand_Prix",
    );
  });

  it("is just the text when nothing was cited", () => {
    expect(copyText(answer({ content: "  Ferrari, 249 wins.\n", citations: [] }))).toBe(
      "Ferrari, 249 wins.",
    );
  });
});

describe("AnswerActions", () => {
  it("copies the answer and says so, then resets", async () => {
    const user = userEvent.setup();
    show();

    await user.click(screen.getByRole("button", { name: "Copy" }));

    await expect(navigator.clipboard.readText()).resolves.toBe(copyText(answer()));
    expect(screen.getByRole("button", { name: "✓ Copied" })).toBeInTheDocument();
    await act(() => new Promise((r) => setTimeout(r, 2100)));
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
  });

  it("says when the clipboard isn't available", async () => {
    show();
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: () => Promise.reject(new DOMException("denied", "NotAllowedError")),
      },
    });

    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Copy" })));

    expect(screen.getByRole("button", { name: "Couldn't copy" })).toBeInTheDocument();
  });

  it("sends a rating with the question answered and the model, then thanks", async () => {
    const user = userEvent.setup();
    const { send, onRated } = show();

    await user.click(screen.getByRole("button", { name: "Good answer" }));

    expect(send).toHaveBeenCalledExactlyOnceWith(BASE, {
      rating: "up",
      question: "Who won the 1976 drivers' title?",
      answer: "James Hunt won by one point [S1].",
      provider: "groq",
      model: "gpt",
    });
    expect(onRated).toHaveBeenCalledExactlyOnceWith("up");
  });

  it("uses the asked question when the answer has no details", async () => {
    const user = userEvent.setup();
    const { send } = show(answer({ done: undefined }));

    await user.click(screen.getByRole("button", { name: "Bad answer" }));

    expect(send.mock.calls[0][1]).toMatchObject({
      rating: "down",
      question: "And 1976?",
      provider: undefined,
    });
  });

  it("disables both buttons while sending", async () => {
    let finish!: () => void;
    const send = vi.fn<typeof sendFeedback>(
      () => new Promise((resolve) => (finish = () => resolve(1))),
    );
    const user = userEvent.setup();
    const { onRated } = show(answer(), { send });

    await user.click(screen.getByRole("button", { name: "Good answer" }));

    expect(screen.getByText("Sending…")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Good answer" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Bad answer" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Bad answer" }));
    expect(send).toHaveBeenCalledTimes(1);

    await act(async () => finish());
    expect(onRated).toHaveBeenCalledExactlyOnceWith("up");
  });

  it("shows why feedback failed and lets the user try again", async () => {
    const send = vi
      .fn<typeof sendFeedback>()
      .mockRejectedValueOnce(new FeedbackError("Too much feedback for now."))
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValueOnce(7);
    const user = userEvent.setup();
    const { onRated } = show(answer(), { send });

    await user.click(screen.getByRole("button", { name: "Bad answer" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Too much feedback for now.");
    expect(onRated).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Bad answer" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Couldn't send your feedback.");

    await user.click(screen.getByRole("button", { name: "Bad answer" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(onRated).toHaveBeenCalledExactlyOnceWith("down");
  });

  it("shows a recorded rating, and can't rate again", async () => {
    const user = userEvent.setup();
    const { send } = show(answer({ feedback: "down" }));

    const down = screen.getByRole("button", { name: "Bad answer" });
    expect(down).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Good answer" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(down).toBeDisabled();
    expect(screen.getByText("Thanks for the feedback.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Good answer" }));
    expect(send).not.toHaveBeenCalled();
  });

  it("offers only Copy for a stopped answer, or when the frontend is misconfigured", () => {
    const { view } = show(answer({ status: "stopped" }));
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Good answer" })).not.toBeInTheDocument();
    view.unmount();

    show(answer(), { apiBaseUrl: null });
    expect(screen.getByRole("button", { name: "Copy" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Good answer" })).not.toBeInTheDocument();
  });

  it.each([
    ["streaming", answer({ status: "streaming" })],
    ["failed", answer({ status: "error", content: "partial" })],
    ["empty", answer({ content: "  " })],
  ])("shows nothing for an answer that is %s", (_, a) => {
    const { view } = show(a);

    expect(view.container).toBeEmptyDOMElement();
  });
});
