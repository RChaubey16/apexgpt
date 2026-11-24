/**
 * Streaming client for `POST /api/chat` (backend F4.1–F4.4).
 *
 * The answer arrives as Server-Sent Events over a POST, so `EventSource` (GET
 * only) can't be used: the body is read with `fetch` and parsed here. Frames
 * are `event: <type>` + one `data: <json>` line, separated by a blank line,
 * and may be split anywhere across network chunks.
 *
 * Every event is validated against the backend contract; anything that doesn't
 * match is a ChatError("bad_response"), and unknown event types are skipped
 * (forward compatible). The stream always ends with `done` or `error`; if it
 * stops before either, that is ChatError("interrupted").
 */

export const MAX_QUESTION_CHARS = 500;
export const MAX_HISTORY_MESSAGES = 20;
export const MAX_HISTORY_CHARS = 8000;

export interface HistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export interface Source {
  id: string;
  title: string;
  url: string;
  section: string | null;
  season: number | null;
}

export interface Table {
  columns: string[];
  rows: unknown[][];
  note?: string;
}

export interface DoneInfo {
  question: string;
  provider: string;
  model: string;
  sources: string[];
  tools: { name: string; ok: boolean }[];
  latencyMs: number;
  promptTokens: number;
  completionTokens: number;
  cached: boolean;
}

export type ChatEvent =
  | { type: "question"; text: string }
  | { type: "tool"; name: string; status: "started" | "finished"; ok?: boolean }
  | { type: "table"; table: Table }
  | { type: "token"; text: string }
  | { type: "citation"; source: Source }
  | { type: "done"; info: DoneInfo }
  | { type: "error"; message: string };

export type ChatErrorKind =
  | "rate_limited" // 429; retryAfterSeconds says when to try again
  | "invalid_request" // 422: the backend rejected the question or history
  | "unreachable" // network error or CORS failure
  | "http_error" // any other status
  | "bad_response" // not the SSE contract
  | "interrupted" // the stream ended before done/error
  | "answer_error"; // an `error` event: the backend's message, safe to show

export class ChatError extends Error {
  constructor(
    readonly kind: ChatErrorKind,
    message: string,
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "ChatError";
  }
}

// --- validation ---

type Json = Record<string, unknown>;

export const isObject = (v: unknown): v is Json =>
  typeof v === "object" && v !== null && !Array.isArray(v);
export const isString = (v: unknown): v is string => typeof v === "string";
export const isNumber = (v: unknown): v is number =>
  typeof v === "number" && Number.isFinite(v);
const isNullableString = (v: unknown) => v === null || v === undefined || isString(v);
const isNullableNumber = (v: unknown) => v === null || v === undefined || isNumber(v);

function toEvent(type: string, data: unknown): ChatEvent | null {
  if (!isObject(data)) throw new Error("data is not an object");
  switch (type) {
    case "question":
      if (isString(data.text)) return { type, text: data.text };
      break;
    case "token":
      if (isString(data.text)) return { type, text: data.text };
      break;
    case "tool":
      if (
        isString(data.name) &&
        (data.status === "started" || data.status === "finished") &&
        (data.ok === undefined || typeof data.ok === "boolean")
      ) {
        return {
          type,
          name: data.name,
          status: data.status,
          ok: data.ok as boolean | undefined,
        };
      }
      break;
    case "table":
      if (
        Array.isArray(data.columns) &&
        data.columns.every(isString) &&
        Array.isArray(data.rows) &&
        data.rows.every(Array.isArray) &&
        (data.note === undefined || isString(data.note))
      ) {
        const table: Table = { columns: data.columns, rows: data.rows as unknown[][] };
        if (isString(data.note)) table.note = data.note;
        return { type, table };
      }
      break;
    case "citation":
      if (
        isString(data.id) &&
        isString(data.title) &&
        isString(data.url) &&
        isNullableString(data.section) &&
        isNullableNumber(data.season)
      ) {
        return {
          type,
          source: {
            id: data.id,
            title: data.title,
            url: data.url,
            section: (data.section as string | null | undefined) ?? null,
            season: (data.season as number | null | undefined) ?? null,
          },
        };
      }
      break;
    case "done":
      if (
        isString(data.question) &&
        isString(data.provider) &&
        isString(data.model) &&
        Array.isArray(data.sources) &&
        data.sources.every(isString) &&
        Array.isArray(data.tools) &&
        data.tools.every(
          (t) => isObject(t) && isString(t.name) && typeof t.ok === "boolean",
        ) &&
        isNumber(data.latency_ms) &&
        isNumber(data.prompt_tokens) &&
        isNumber(data.completion_tokens)
      ) {
        return {
          type,
          info: {
            question: data.question,
            provider: data.provider,
            model: data.model,
            sources: data.sources,
            tools: data.tools as { name: string; ok: boolean }[],
            latencyMs: data.latency_ms,
            promptTokens: data.prompt_tokens,
            completionTokens: data.completion_tokens,
            cached: data.cached === true,
          },
        };
      }
      break;
    case "error":
      if (isString(data.message)) return { type, message: data.message };
      break;
    default:
      return null; // an event this client doesn't know: skip it
  }
  throw new Error(`invalid ${type} event`);
}

// --- SSE parsing ---

/** Parse one frame (the lines between blank lines); null for comments/no data. */
export function parseFrame(frame: string): ChatEvent | null {
  let type = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (line === "" || line.startsWith(":")) continue;
    const colon = line.indexOf(":");
    const field = colon < 0 ? line : line.slice(0, colon);
    let value = colon < 0 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") type = value;
    else if (field === "data") data.push(value);
  }
  if (data.length === 0) return null;
  let parsed: unknown;
  try {
    parsed = JSON.parse(data.join("\n"));
  } catch {
    throw new Error(`invalid JSON in ${type} event`);
  }
  return toEvent(type, parsed);
}

/** Yield SSE frames from a byte stream, however it is chunked. */
export async function* readFrames(
  body: ReadableStream<Uint8Array>,
): AsyncGenerator<string> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let pendingCR = ""; // a "\r" at a chunk's end may start a "\r\n"
  try {
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      let text = pendingCR + decoder.decode(value, { stream: true });
      pendingCR = text.endsWith("\r") ? "\r" : "";
      if (pendingCR) text = text.slice(0, -1);
      buffer += text.replace(/\r\n?/g, "\n");
      let end: number;
      while ((end = buffer.indexOf("\n\n")) >= 0) {
        yield buffer.slice(0, end);
        buffer = buffer.slice(end + 2);
      }
    }
    buffer += (pendingCR + decoder.decode()).replace(/\r\n?/g, "\n");
    if (buffer.trim()) yield buffer;
  } finally {
    reader.releaseLock();
  }
}

// --- the request ---

export interface ChatRequest {
  question: string;
  history?: HistoryMessage[];
}

interface StreamOptions {
  signal?: AbortSignal;
  fetchImpl?: typeof fetch;
}

/** Seconds from a 429's Retry-After header (60 when it is missing or odd). */
export function retryAfter(response: Response): number {
  const seconds = Number(response.headers.get("Retry-After"));
  return Number.isFinite(seconds) && seconds > 0 ? Math.ceil(seconds) : 60;
}

/** A FastAPI error body's `detail` message, if there is one. */
export async function detail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    return isObject(body) && isString(body.detail) ? body.detail : null;
  } catch {
    return null;
  }
}

/**
 * Ask a question and yield its events until `done`. Throws ChatError for
 * every failure (an `error` event included); an abort via `signal` rethrows
 * the AbortError so callers can tell "stopped" from "failed".
 */
export async function* streamChat(
  baseUrl: string,
  request: ChatRequest,
  { signal, fetchImpl = fetch }: StreamOptions = {},
): AsyncGenerator<ChatEvent> {
  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify({
        question: request.question,
        history: request.history ?? [],
      }),
      cache: "no-store",
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new ChatError(
      "unreachable",
      "Can't reach ApexGPT. Check your connection and try again.",
    );
  }

  if (response.status === 429) {
    const seconds = retryAfter(response);
    throw new ChatError(
      "rate_limited",
      `Too many questions for now. Try again in ${seconds} seconds.`,
      seconds,
    );
  }
  if (response.status === 422) {
    throw new ChatError(
      "invalid_request",
      "That question couldn't be sent. Try rephrasing it.",
    );
  }
  if (!response.ok) {
    throw new ChatError(
      "http_error",
      (await detail(response)) ??
        `ApexGPT is having trouble (HTTP ${response.status}). Please try again.`,
    );
  }
  if (
    !response.body ||
    !response.headers.get("Content-Type")?.startsWith("text/event-stream")
  ) {
    throw new ChatError(
      "bad_response",
      "ApexGPT sent an unexpected response. Please try again.",
    );
  }

  try {
    for await (const frame of readFrames(response.body)) {
      let event: ChatEvent | null;
      try {
        event = parseFrame(frame);
      } catch {
        throw new ChatError(
          "bad_response",
          "ApexGPT sent an unexpected response. Please try again.",
        );
      }
      if (event === null) continue;
      if (event.type === "error") throw new ChatError("answer_error", event.message);
      yield event;
      if (event.type === "done") return;
    }
  } catch (error) {
    if (error instanceof ChatError || signal?.aborted) throw error;
    throw new ChatError("interrupted", "The answer was interrupted. Please try again.");
  }
  throw new ChatError("interrupted", "The answer was interrupted. Please try again.");
}
