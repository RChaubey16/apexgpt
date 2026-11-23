import { describe, expect, it } from "vitest";

import type { ChatEvent, DoneInfo } from "./chat";
import {
  conversationReducer,
  historyFor,
  initialConversation,
  isAnswering,
  type AssistantMessage,
  type Conversation,
  type Message,
} from "./conversation";

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

function asked(question = "Who won 1976?"): Conversation {
  return conversationReducer(initialConversation, {
    type: "ask",
    userId: "q1",
    answerId: "a1",
    question,
  });
}

function apply(state: Conversation, ...events: ChatEvent[]): Conversation {
  return events.reduce(
    (s, event) => conversationReducer(s, { type: "event", answerId: "a1", event }),
    state,
  );
}

const answer = (state: Conversation) => state.messages[1] as AssistantMessage;

describe("conversationReducer", () => {
  it("adds the question and an empty streaming answer", () => {
    const state = asked();

    expect(state.messages).toEqual([
      { id: "q1", role: "user", content: "Who won 1976?" },
      {
        id: "a1",
        role: "assistant",
        status: "streaming",
        content: "",
        tables: [],
        citations: [],
      },
    ]);
    expect(isAnswering(state)).toBe(true);
  });

  it("builds the answer from events", () => {
    const source = {
      id: "S1",
      title: "1976 Japanese GP",
      url: "https://x",
      section: null,
      season: 1976,
    };
    let state = apply(asked(), { type: "question", text: "Who won the 1976 title?" });
    state = apply(state, { type: "tool", name: "query_stats", status: "started" });
    expect(answer(state).activeTool).toBe("query_stats");

    state = apply(
      state,
      { type: "tool", name: "query_stats", status: "finished", ok: true },
      { type: "table", table: { columns: ["champion"], rows: [["James Hunt"]] } },
      { type: "token", text: "James Hunt " },
      { type: "token", text: "[S1]." },
      { type: "citation", source },
      { type: "citation", source }, // a repeat is ignored
      { type: "done", info: INFO },
    );

    expect(answer(state)).toEqual({
      id: "a1",
      role: "assistant",
      status: "done",
      content: "James Hunt [S1].",
      standaloneQuestion: "Who won the 1976 title?",
      activeTool: undefined,
      tables: [{ columns: ["champion"], rows: [["James Hunt"]] }],
      citations: [source],
      done: INFO,
    });
    expect(isAnswering(state)).toBe(false);
  });

  it("clears the tool status when text starts", () => {
    const state = apply(
      asked(),
      { type: "tool", name: "search_f1_knowledge", status: "started" },
      { type: "token", text: "A" },
    );

    expect(answer(state).activeTool).toBeUndefined();
  });

  it("records a failure with its retry delay", () => {
    let state = apply(asked(), { type: "tool", name: "query_stats", status: "started" });
    state = conversationReducer(state, {
      type: "fail",
      answerId: "a1",
      message: "Too many questions",
      retryAfterSeconds: 30,
    });

    expect(answer(state)).toMatchObject({
      status: "error",
      error: "Too many questions",
      retryAfterSeconds: 30,
      activeTool: undefined,
    });
  });

  it("keeps the partial text when stopped, and ignores later events", () => {
    let state = apply(asked(), { type: "token", text: "Partial" });
    state = conversationReducer(state, { type: "stop", answerId: "a1" });
    state = apply(state, { type: "token", text: " more" }, { type: "done", info: INFO });
    state = conversationReducer(state, { type: "fail", answerId: "a1", message: "late" });

    expect(answer(state)).toMatchObject({ status: "stopped", content: "Partial" });
    expect(answer(state).error).toBeUndefined();
  });

  it("returns the same state for an unknown answer id", () => {
    const state = asked();

    expect(conversationReducer(state, { type: "stop", answerId: "nope" })).toBe(state);
  });
});

describe("historyFor", () => {
  const user = (id: string, content: string): Message => ({ id, role: "user", content });
  const reply = (
    id: string,
    content: string,
    status: AssistantMessage["status"] = "done",
  ): Message => ({
    id,
    role: "assistant",
    status,
    content,
    tables: [],
    citations: [],
  });

  it("is empty for a new conversation", () => {
    expect(historyFor([])).toEqual([]);
  });

  it("keeps finished exchanges in order", () => {
    expect(
      historyFor([
        user("1", "Who won 1988?"),
        reply("2", " Ayrton Senna. "),
        user("3", "How?"),
        reply("4", "By winning 8 races."),
      ]),
    ).toEqual([
      { role: "user", content: "Who won 1988?" },
      { role: "assistant", content: "Ayrton Senna." },
      { role: "user", content: "How?" },
      { role: "assistant", content: "By winning 8 races." },
    ]);
  });

  it("leaves out exchanges whose answer failed, was stopped, is empty or is still streaming", () => {
    expect(
      historyFor([
        user("1", "a"),
        reply("2", "", "error"),
        user("3", "b"),
        reply("4", "partial", "stopped"),
        user("5", "c"),
        reply("6", "  ", "done"),
        user("7", "d"),
        reply("8", "Answer."),
        user("9", "e"),
        reply("10", "stream", "streaming"),
      ]),
    ).toEqual([
      { role: "user", content: "d" },
      { role: "assistant", content: "Answer." },
    ]);
  });

  it("keeps the last 20 messages, each within 8,000 characters", () => {
    const messages: Message[] = [];
    for (let i = 0; i < 15; i++) {
      messages.push(user(`q${i}`, `question ${i}`), reply(`a${i}`, "x".repeat(9000)));
    }

    const history = historyFor(messages);

    expect(history).toHaveLength(20);
    expect(history[0]).toEqual({ role: "user", content: "question 5" });
    expect(history.every((m) => m.content.length <= 8000)).toBe(true);
  });
});
