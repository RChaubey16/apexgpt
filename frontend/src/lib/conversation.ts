/**
 * Conversation state: the messages on screen, built from chat events.
 *
 * Pure functions, so the UI's behaviour is testable without React:
 * - `conversationReducer` applies one action (ask, event, finish, fail, stop);
 * - `historyFor` is what `/api/chat` gets as `history` for a follow-up: the
 *   finished exchanges before the new question, newest last, within the
 *   backend's limits (20 messages of ≤ 8,000 characters).
 */

import {
  MAX_HISTORY_CHARS,
  MAX_HISTORY_MESSAGES,
  type ChatEvent,
  type DoneInfo,
  type HistoryMessage,
  type Source,
  type Table,
} from "./chat";

export interface UserMessage {
  id: string;
  role: "user";
  content: string;
}

export type AnswerStatus = "streaming" | "done" | "error" | "stopped";

export interface AssistantMessage {
  id: string;
  role: "assistant";
  status: AnswerStatus;
  content: string;
  /** The standalone question the backend answered, when a follow-up was rewritten. */
  standaloneQuestion?: string;
  /** The tool running right now (cleared when it finishes). */
  activeTool?: string;
  tables: Table[];
  citations: Source[];
  done?: DoneInfo;
  error?: string;
  /** Seconds to wait before asking again (rate limited). */
  retryAfterSeconds?: number;
}

export type Message = UserMessage | AssistantMessage;

export interface Conversation {
  messages: Message[];
}

export type Action =
  | { type: "ask"; userId: string; answerId: string; question: string }
  | { type: "event"; answerId: string; event: ChatEvent }
  | { type: "fail"; answerId: string; message: string; retryAfterSeconds?: number }
  | { type: "stop"; answerId: string };

export const initialConversation: Conversation = { messages: [] };

function updateAnswer(
  state: Conversation,
  id: string,
  update: (m: AssistantMessage) => AssistantMessage,
): Conversation {
  let changed = false;
  const messages = state.messages.map((m) => {
    if (m.id !== id || m.role !== "assistant") return m;
    changed = true;
    return update(m);
  });
  return changed ? { messages } : state;
}

function applyEvent(m: AssistantMessage, event: ChatEvent): AssistantMessage {
  if (m.status !== "streaming") return m; // late events after stop/fail
  switch (event.type) {
    case "question":
      return { ...m, standaloneQuestion: event.text };
    case "tool":
      return { ...m, activeTool: event.status === "started" ? event.name : undefined };
    case "table":
      return { ...m, tables: [...m.tables, event.table] };
    case "token":
      return { ...m, content: m.content + event.text, activeTool: undefined };
    case "citation":
      return m.citations.some((c) => c.id === event.source.id)
        ? m
        : { ...m, citations: [...m.citations, event.source] };
    case "done":
      return { ...m, status: "done", activeTool: undefined, done: event.info };
    case "error":
      return { ...m, status: "error", activeTool: undefined, error: event.message };
  }
}

export function conversationReducer(state: Conversation, action: Action): Conversation {
  switch (action.type) {
    case "ask":
      return {
        messages: [
          ...state.messages,
          { id: action.userId, role: "user", content: action.question },
          {
            id: action.answerId,
            role: "assistant",
            status: "streaming",
            content: "",
            tables: [],
            citations: [],
          },
        ],
      };
    case "event":
      return updateAnswer(state, action.answerId, (m) => applyEvent(m, action.event));
    case "fail":
      return updateAnswer(state, action.answerId, (m) =>
        m.status === "streaming"
          ? {
              ...m,
              status: "error",
              activeTool: undefined,
              error: action.message,
              retryAfterSeconds: action.retryAfterSeconds,
            }
          : m,
      );
    case "stop":
      return updateAnswer(state, action.answerId, (m) =>
        m.status === "streaming" ? { ...m, status: "stopped", activeTool: undefined } : m,
      );
  }
}

export function isAnswering(state: Conversation): boolean {
  return state.messages.some((m) => m.role === "assistant" && m.status === "streaming");
}

/**
 * History for the next question: completed exchanges only (a question whose
 * answer failed or was stopped is left out with it), the newest last.
 */
export function historyFor(messages: Message[]): HistoryMessage[] {
  const history: HistoryMessage[] = [];
  for (let i = 0; i + 1 < messages.length; i++) {
    const question = messages[i];
    const answer = messages[i + 1];
    if (
      question.role === "user" &&
      answer.role === "assistant" &&
      answer.status === "done" &&
      answer.content.trim()
    ) {
      history.push(
        { role: "user", content: question.content.slice(0, MAX_HISTORY_CHARS) },
        { role: "assistant", content: answer.content.trim().slice(0, MAX_HISTORY_CHARS) },
      );
      i++;
    }
  }
  return history.slice(-MAX_HISTORY_MESSAGES);
}
