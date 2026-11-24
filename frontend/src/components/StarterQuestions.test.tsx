import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MAX_QUESTION_CHARS } from "@/lib/chat";

import { STARTER_QUESTIONS, StarterQuestions } from "./StarterQuestions";

describe("StarterQuestions", () => {
  it("shows one card per question, with its title", () => {
    render(<StarterQuestions onPick={() => {}} />);

    const list = screen.getByRole("list", { name: "Starter questions" });
    const cards = within(list).getAllByRole("button");
    expect(cards).toHaveLength(STARTER_QUESTIONS.length);
    expect(cards[0]).toHaveTextContent(STARTER_QUESTIONS[0].title);
    expect(cards[0]).toHaveTextContent(STARTER_QUESTIONS[0].question);
  });

  it("passes the picked question on", async () => {
    const onPick = vi.fn();
    render(<StarterQuestions onPick={onPick} />);

    await userEvent.click(screen.getByRole("button", { name: /Senna vs Prost/ }));

    expect(onPick).toHaveBeenCalledExactlyOnceWith(
      "Tell me about the Senna–Prost rivalry",
    );
  });

  it("disables every card when asked to", async () => {
    const onPick = vi.fn();
    render(<StarterQuestions onPick={onPick} disabled />);

    const cards = screen.getAllByRole("button");
    expect(cards.every((c) => (c as HTMLButtonElement).disabled)).toBe(true);
    await userEvent.click(cards[0]);
    expect(onPick).not.toHaveBeenCalled();
  });

  it("has unique questions the backend will accept", () => {
    const questions = STARTER_QUESTIONS.map((s) => s.question);
    expect(new Set(questions).size).toBe(questions.length);
    for (const s of STARTER_QUESTIONS) {
      expect(s.title.trim()).not.toBe("");
      expect(s.question.trim()).toBe(s.question);
      expect(s.question.length).toBeGreaterThan(0);
      expect(s.question.length).toBeLessThanOrEqual(MAX_QUESTION_CHARS);
    }
  });
});
