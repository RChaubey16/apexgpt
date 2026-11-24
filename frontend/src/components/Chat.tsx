"use client";

import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { AnswerContent } from "@/components/AnswerContent";
import { StarterQuestions } from "@/components/StarterQuestions";
import { ChatError, MAX_QUESTION_CHARS, streamChat } from "@/lib/chat";
import {
  conversationReducer,
  historyFor,
  initialConversation,
  isAnswering,
  type AssistantMessage,
  type Message,
} from "@/lib/conversation";

const TOOL_LABELS: Record<string, string> = {
  query_stats: "Checking the stats…",
  search_f1_knowledge: "Searching F1 history…",
};
const COUNTER_FROM = MAX_QUESTION_CHARS - 100;

let counter = 0;
const nextId = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${++counter}`;

interface ChatProps {
  /** Validated backend URL, or null if config is invalid. */
  apiBaseUrl: string | null;
  /** For tests: the streaming client. */
  stream?: typeof streamChat;
}

export function Chat({ apiBaseUrl, stream = streamChat }: ChatProps) {
  const [conversation, dispatch] = useReducer(conversationReducer, initialConversation);
  const [draft, setDraft] = useState("");
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const answering = isAnswering(conversation);

  // Stop a running answer when the page goes away.
  useEffect(() => () => controller.current?.abort(), []);

  // Re-enable sending once a rate limit has passed.
  useEffect(() => {
    if (blockedUntil === null) return;
    const timer = setTimeout(
      () => setBlockedUntil(null),
      Math.max(0, blockedUntil - Date.now()),
    );
    return () => clearTimeout(timer);
  }, [blockedUntil]);

  // Follow the answer as it streams.
  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [conversation]);

  const ask = useCallback(
    async (question: string) => {
      if (!apiBaseUrl) return;
      const history = historyFor(conversation.messages);
      const answerId = nextId("a");
      const abort = new AbortController();
      controller.current = abort;
      dispatch({ type: "ask", userId: nextId("q"), answerId, question });
      try {
        for await (const event of stream(
          apiBaseUrl,
          { question, history },
          { signal: abort.signal },
        )) {
          dispatch({ type: "event", answerId, event });
        }
      } catch (error) {
        if (abort.signal.aborted) {
          dispatch({ type: "stop", answerId });
        } else if (error instanceof ChatError) {
          dispatch({
            type: "fail",
            answerId,
            message: error.message,
            retryAfterSeconds: error.retryAfterSeconds,
          });
          if (error.retryAfterSeconds) {
            setBlockedUntil(Date.now() + error.retryAfterSeconds * 1000);
          }
        } else {
          dispatch({
            type: "fail",
            answerId,
            message: "Something went wrong. Please try again.",
          });
        }
      } finally {
        if (controller.current === abort) controller.current = null;
      }
    },
    [apiBaseUrl, conversation.messages, stream],
  );

  const question = draft.trim();
  const blocked = blockedUntil !== null;
  const ready = apiBaseUrl !== null && !answering && !blocked;
  const canSend = ready && question.length > 0 && question.length <= MAX_QUESTION_CHARS;

  const submit = () => {
    if (!canSend) return;
    setDraft("");
    void ask(question);
  };

  return (
    <div className="mx-auto flex w-full max-w-3xl flex-1 flex-col">
      <div
        className="flex flex-1 flex-col gap-6 px-4 py-6"
        role="log"
        aria-label="Conversation"
        aria-live="polite"
      >
        {conversation.messages.length === 0 ? (
          <div className="m-auto flex w-full max-w-2xl flex-col items-center gap-5">
            <p className="max-w-md text-center text-zinc-400">
              Ask about any driver, team, circuit, season or rivalry from 1950 to 2025.
            </p>
            {/* Shown only before the first question, so only `ready` can block it. */}
            <StarterQuestions onPick={(q) => void ask(q)} disabled={!ready} />
          </div>
        ) : (
          conversation.messages.map((m) => <MessageView key={m.id} message={m} />)
        )}
        <div ref={endRef} />
      </div>

      <form
        className="sticky bottom-0 border-t border-zinc-800 bg-background/95 px-4 py-3 backdrop-blur"
        onSubmit={(e) => {
          e.preventDefault();
          submit();
        }}
      >
        <div className="flex items-end gap-2">
          <label htmlFor="question" className="sr-only">
            Your question
          </label>
          <textarea
            id="question"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            rows={1}
            maxLength={MAX_QUESTION_CHARS + 50}
            placeholder={
              apiBaseUrl
                ? "Ask about Formula 1…"
                : "Chat is unavailable (frontend misconfigured)"
            }
            disabled={apiBaseUrl === null}
            className="max-h-40 min-h-11 flex-1 resize-none rounded-xl border border-zinc-700 bg-zinc-900 px-4 py-2.5 text-base text-zinc-100 placeholder:text-zinc-500 focus:border-red-500 focus:outline-none disabled:opacity-50"
          />
          {answering ? (
            <button
              type="button"
              onClick={() => controller.current?.abort()}
              className="h-11 rounded-xl border border-zinc-600 px-4 text-sm font-medium text-zinc-200 hover:border-zinc-400"
            >
              Stop
            </button>
          ) : (
            <button
              type="submit"
              disabled={!canSend}
              className="h-11 rounded-xl bg-red-600 px-4 text-sm font-semibold text-white hover:bg-red-500 disabled:cursor-not-allowed disabled:bg-zinc-800 disabled:text-zinc-500"
            >
              Send
            </button>
          )}
        </div>
        {question.length > COUNTER_FROM && (
          <p
            className={`mt-1 text-right text-xs ${question.length > MAX_QUESTION_CHARS ? "text-red-400" : "text-zinc-500"}`}
          >
            {question.length}/{MAX_QUESTION_CHARS}
          </p>
        )}
      </form>
    </div>
  );
}

function MessageView({ message }: { message: Message }) {
  if (message.role === "user") {
    return (
      <div className="ml-auto max-w-[85%] whitespace-pre-wrap rounded-2xl bg-zinc-800 px-4 py-2.5 text-zinc-100">
        {message.content}
      </div>
    );
  }
  return <AnswerView answer={message} />;
}

function statusLine(answer: AssistantMessage): string | null {
  if (answer.status !== "streaming") return null;
  if (answer.activeTool) return TOOL_LABELS[answer.activeTool] ?? "Working…";
  return answer.content ? null : "Thinking…";
}

function AnswerView({ answer }: { answer: AssistantMessage }) {
  const status = statusLine(answer);
  return (
    <article
      className="flex max-w-full flex-col gap-2"
      aria-busy={answer.status === "streaming"}
      data-status={answer.status}
    >
      {answer.standaloneQuestion && (
        <p className="text-xs text-zinc-500">Answering: {answer.standaloneQuestion}</p>
      )}
      <AnswerContent
        text={answer.content}
        citations={answer.citations}
        tables={answer.tables}
        complete={answer.status !== "streaming"}
      />
      {status && (
        <p className="flex items-center gap-2 text-sm text-zinc-400" role="status">
          <span
            className="h-2 w-2 animate-pulse rounded-full bg-red-500"
            aria-hidden="true"
          />
          {status}
        </p>
      )}
      {answer.status === "stopped" && <p className="text-sm text-zinc-500">Stopped.</p>}
      {answer.status === "error" && (
        <p
          className="rounded-lg border border-red-900 bg-red-950/40 px-3 py-2 text-sm text-red-300"
          role="alert"
        >
          {answer.error}
        </p>
      )}
      {answer.done?.cached && (
        <p className="text-xs text-zinc-600">Answered from cache</p>
      )}
    </article>
  );
}
