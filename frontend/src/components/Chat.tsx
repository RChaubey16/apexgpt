"use client";

import {
  useCallback,
  useEffect,
  useReducer,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { AnswerActions } from "@/components/AnswerActions";
import { AnswerContent } from "@/components/AnswerContent";
import { StarterQuestions } from "@/components/StarterQuestions";
import { ChatError, MAX_QUESTION_CHARS, streamChat } from "@/lib/chat";
import type { sendFeedback } from "@/lib/feedback";
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
  /** A saved conversation to continue (read once, on mount). */
  initialMessages?: Message[];
  /**
   * Called when the messages change: on each question, when an answer ends,
   * and once on unmount if anything changed since (a part-streamed answer).
   * Not on every streamed token.
   */
  onMessagesChange?: (messages: Message[]) => void;
  /** For tests: the streaming client. */
  stream?: typeof streamChat;
  /** For tests: the feedback client. */
  feedback?: typeof sendFeedback;
}

export function Chat({
  apiBaseUrl,
  initialMessages,
  onMessagesChange,
  stream = streamChat,
  feedback,
}: ChatProps) {
  const [conversation, dispatch] = useReducer(
    conversationReducer,
    initialMessages,
    (messages) => (messages ? { messages } : initialConversation),
  );
  const [draft, setDraft] = useState("");
  const [blockedUntil, setBlockedUntil] = useState<number | null>(null);
  const controller = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const answering = isAnswering(conversation);

  // Report changes, skipping the tokens of an answer still streaming.
  const reported = useRef(conversation.messages);
  const latest = useRef(conversation.messages);
  const onChange = useRef(onMessagesChange);
  useEffect(() => {
    onChange.current = onMessagesChange;
    latest.current = conversation.messages;
    const messages = conversation.messages;
    if (messages === reported.current) return;
    if (answering && messages.length === reported.current.length) return;
    reported.current = messages;
    onChange.current?.(messages);
  }, [conversation.messages, answering, onMessagesChange]);

  // Stop a running answer when the chat goes away, keeping what has arrived.
  useEffect(
    () => () => {
      controller.current?.abort();
      if (latest.current !== reported.current) {
        reported.current = latest.current;
        onChange.current?.(latest.current);
      }
    },
    [],
  );

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
    <div className="flex min-h-0 w-full flex-1 flex-col">
      <div
        className="flex-1 overflow-y-auto"
        role="log"
        aria-label="Conversation"
        aria-live="polite"
      >
        <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col gap-6 px-4 py-6">
          {conversation.messages.length === 0 ? (
            <div className="m-auto flex w-full max-w-2xl flex-col items-center gap-6 py-4">
              <div className="flex flex-col items-center gap-2 text-center">
                <p className="text-xs font-semibold tracking-[0.25em] text-accent-text uppercase">
                  Lights out
                </p>
                <h2 className="text-2xl font-black italic tracking-tight sm:text-3xl">
                  What do you want to know?
                </h2>
                <p className="max-w-md text-soft">
                  Ask about any driver, team, circuit, season or rivalry from 1950 to
                  2025.
                </p>
              </div>
              {/* Shown only before the first question, so only `ready` can block it. */}
              <StarterQuestions onPick={(q) => void ask(q)} disabled={!ready} />
            </div>
          ) : (
            conversation.messages.map((m, i) =>
              m.role === "user" ? (
                <UserMessageView key={m.id} content={m.content} />
              ) : (
                <AnswerView key={m.id} answer={m}>
                  <AnswerActions
                    answer={m}
                    question={questionBefore(conversation.messages, i)}
                    apiBaseUrl={apiBaseUrl}
                    onRated={(rating) =>
                      dispatch({ type: "rate", answerId: m.id, rating })
                    }
                    send={feedback}
                  />
                </AnswerView>
              ),
            )
          )}
          <div ref={endRef} />
        </div>
      </div>

      <div className="border-t border-line bg-surface pb-[env(safe-area-inset-bottom)]">
        <form
          className="mx-auto w-full max-w-3xl px-3 py-3 sm:px-4"
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
              className="max-h-40 min-h-11 min-w-0 flex-1 resize-none rounded-xl border border-control bg-raised px-4 py-2.5 text-base text-foreground placeholder:text-muted focus:border-accent disabled:cursor-not-allowed disabled:opacity-50"
            />
            {answering ? (
              <button
                type="button"
                onClick={() => controller.current?.abort()}
                className="h-11 shrink-0 rounded-xl border border-control px-4 text-sm font-medium text-soft hover:border-foreground hover:text-foreground"
              >
                Stop
              </button>
            ) : (
              <button
                type="submit"
                disabled={!canSend}
                className="h-11 shrink-0 -skew-x-6 rounded-lg bg-accent px-5 text-sm font-bold tracking-wide text-on-accent uppercase hover:bg-accent-strong disabled:cursor-not-allowed disabled:bg-raised disabled:text-muted"
              >
                Send
              </button>
            )}
          </div>
          {question.length > COUNTER_FROM && (
            <p
              className={`mt-1 text-right text-xs ${question.length > MAX_QUESTION_CHARS ? "text-danger-text" : "text-muted"}`}
            >
              {question.length}/{MAX_QUESTION_CHARS}
            </p>
          )}
        </form>
      </div>
    </div>
  );
}

function questionBefore(messages: Message[], index: number): string {
  const previous = messages[index - 1];
  return previous?.role === "user" ? previous.content : "";
}

function UserMessageView({ content }: { content: string }) {
  return (
    <div className="ml-auto max-w-[85%] whitespace-pre-wrap break-words rounded-2xl rounded-r-sm border-r-2 border-accent bg-raised px-4 py-2.5 text-foreground">
      {content}
    </div>
  );
}

function statusLine(answer: AssistantMessage): string | null {
  if (answer.status !== "streaming") return null;
  if (answer.activeTool) return TOOL_LABELS[answer.activeTool] ?? "Working…";
  return answer.content ? null : "Thinking…";
}

function AnswerView({
  answer,
  children,
}: {
  answer: AssistantMessage;
  /** The actions under the answer. */
  children: ReactNode;
}) {
  const status = statusLine(answer);
  return (
    <article
      className="flex max-w-full min-w-0 flex-col gap-2 border-l-2 border-line pl-3 sm:pl-4 data-[status=streaming]:border-accent"
      aria-busy={answer.status === "streaming"}
      data-status={answer.status}
    >
      {answer.standaloneQuestion && (
        <p className="text-xs text-muted">Answering: {answer.standaloneQuestion}</p>
      )}
      <AnswerContent
        text={answer.content}
        citations={answer.citations}
        tables={answer.tables}
        complete={answer.status !== "streaming"}
      />
      {status && (
        <p className="flex items-center gap-2 text-sm text-soft" role="status">
          <span
            className="h-2 w-2 animate-pulse rounded-full bg-accent"
            aria-hidden="true"
          />
          {status}
        </p>
      )}
      {answer.status === "stopped" && <p className="text-sm text-muted">Stopped.</p>}
      {answer.status === "error" && (
        <p
          className="rounded-lg border border-danger-line bg-danger-bg px-3 py-2 text-sm text-danger-text"
          role="alert"
        >
          {answer.error}
        </p>
      )}
      {answer.done?.cached && <p className="text-xs text-muted">Answered from cache</p>}
      {children}
    </article>
  );
}
