import { describe, expect, it, vi } from "vitest";

import { ChatError, parseFrame, readFrames, streamChat, type ChatEvent } from "./chat";

const BASE = "http://backend.test";

const DONE = {
  question: "Explain Abu Dhabi 2021",
  provider: "groq",
  model: "openai/gpt-oss-120b",
  sources: ["S1"],
  tools: [{ name: "search_f1_knowledge", ok: true }],
  latency_ms: 5292,
  prompt_tokens: 6100,
  completion_tokens: 700,
  cached: false,
};
const CITATION = {
  id: "S1",
  title: "2021 Abu Dhabi Grand Prix",
  url: "https://en.wikipedia.org/wiki/2021_Abu_Dhabi_Grand_Prix",
  section: null,
  season: 2021,
};

export function sse(event: string, data: unknown): string {
  return `event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

const encoder = new TextEncoder();

/** A ReadableStream of `body` cut into byte chunks of `size`. */
export function byteStream(body: string, size = 1_000_000): ReadableStream<Uint8Array> {
  const bytes = encoder.encode(body);
  let offset = 0;
  return new ReadableStream({
    pull(controller) {
      if (offset >= bytes.length) {
        controller.close();
        return;
      }
      controller.enqueue(bytes.slice(offset, offset + size));
      offset += size;
    },
  });
}

export function sseResponse(
  body: string,
  size?: number,
  init: ResponseInit = {},
): Response {
  return new Response(byteStream(body, size), {
    status: 200,
    headers: { "Content-Type": "text/event-stream; charset=utf-8" },
    ...init,
  });
}

function fetchReturning(response: Response) {
  return vi.fn<typeof fetch>().mockResolvedValue(response);
}

async function collect(events: AsyncGenerator<ChatEvent>): Promise<ChatEvent[]> {
  const out: ChatEvent[] = [];
  for await (const e of events) out.push(e);
  return out;
}

async function failure(events: AsyncGenerator<ChatEvent>): Promise<ChatError> {
  try {
    await collect(events);
  } catch (error) {
    if (error instanceof ChatError) return error;
    throw error;
  }
  throw new Error("expected a ChatError");
}

const FULL_STREAM =
  sse("question", { text: "Who won the 2021 title?" }) +
  sse("tool", { name: "search_f1_knowledge", status: "started" }) +
  sse("tool", { name: "search_f1_knowledge", status: "finished", ok: true }) +
  sse("table", { columns: ["driver", "wins"], rows: [["Max Verstappen", 10]] }) +
  sse("token", { text: "Verstappen won — " }) +
  sse("token", { text: "on the last lap [S1]." }) +
  sse("citation", CITATION) +
  sse("done", DONE);

const EXPECTED: ChatEvent[] = [
  { type: "question", text: "Who won the 2021 title?" },
  { type: "tool", name: "search_f1_knowledge", status: "started", ok: undefined },
  { type: "tool", name: "search_f1_knowledge", status: "finished", ok: true },
  {
    type: "table",
    table: { columns: ["driver", "wins"], rows: [["Max Verstappen", 10]] },
  },
  { type: "token", text: "Verstappen won — " },
  { type: "token", text: "on the last lap [S1]." },
  { type: "citation", source: CITATION },
  {
    type: "done",
    info: {
      question: "Explain Abu Dhabi 2021",
      provider: "groq",
      model: "openai/gpt-oss-120b",
      sources: ["S1"],
      tools: [{ name: "search_f1_knowledge", ok: true }],
      latencyMs: 5292,
      promptTokens: 6100,
      completionTokens: 700,
      cached: false,
    },
  },
];

describe("streamChat", () => {
  it("posts the question and history and yields every event", async () => {
    const fetchImpl = fetchReturning(sseResponse(FULL_STREAM));
    const history = [
      { role: "user" as const, content: "Who won 2021?" },
      { role: "assistant" as const, content: "Max Verstappen." },
    ];

    const events = await collect(
      streamChat(BASE, { question: "How?", history }, { fetchImpl }),
    );

    expect(events).toEqual(EXPECTED);
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/api/chat`);
    expect(init?.method).toBe("POST");
    expect(init?.cache).toBe("no-store");
    expect(JSON.parse(init?.body as string)).toEqual({ question: "How?", history });
    expect(new Headers(init?.headers).get("Accept")).toBe("text/event-stream");
  });

  it.each([1, 2, 3, 7, 64])(
    "parses the same events whatever the chunk size (%i bytes)",
    async (size) => {
      // "—" is 3 bytes in UTF-8, so small chunks split it.
      const events = await collect(
        streamChat(
          BASE,
          { question: "q" },
          { fetchImpl: fetchReturning(sseResponse(FULL_STREAM, size)) },
        ),
      );

      expect(events).toEqual(EXPECTED);
    },
  );

  it("accepts CRLF line endings, split between chunks too", async () => {
    const body = FULL_STREAM.replace(/\n/g, "\r\n");

    for (const size of [1, 5, 1000]) {
      const events = await collect(
        streamChat(
          BASE,
          { question: "q" },
          { fetchImpl: fetchReturning(sseResponse(body, size)) },
        ),
      );
      expect(events).toEqual(EXPECTED);
    }
  });

  it("sends an empty history by default", async () => {
    const fetchImpl = fetchReturning(sseResponse(sse("done", DONE)));

    await collect(streamChat(BASE, { question: "q" }, { fetchImpl }));

    expect(JSON.parse(fetchImpl.mock.calls[0][1]?.body as string).history).toEqual([]);
  });

  it("skips unknown events and comments", async () => {
    const body = ": keep-alive\n\n" + sse("progress", { pct: 50 }) + sse("done", DONE);

    const events = await collect(
      streamChat(
        BASE,
        { question: "q" },
        { fetchImpl: fetchReturning(sseResponse(body)) },
      ),
    );

    expect(events.map((e) => e.type)).toEqual(["done"]);
  });

  it("reads a done event without the cached field as not cached", async () => {
    const { cached: _cached, ...older } = DONE; // eslint-disable-line @typescript-eslint/no-unused-vars
    const events = await collect(
      streamChat(
        BASE,
        { question: "q" },
        { fetchImpl: fetchReturning(sseResponse(sse("done", older))) },
      ),
    );

    expect(events[0]).toMatchObject({ type: "done", info: { cached: false } });
  });

  it("turns an error event into an answer_error with the backend's message", async () => {
    const body =
      sse("token", { text: "Partial" }) +
      sse("error", { message: "All providers failed" });
    const seen: ChatEvent[] = [];

    const error = await (async () => {
      try {
        for await (const e of streamChat(
          BASE,
          { question: "q" },
          { fetchImpl: fetchReturning(sseResponse(body)) },
        )) {
          seen.push(e);
        }
      } catch (e) {
        return e as ChatError;
      }
    })();

    expect(seen).toEqual([{ type: "token", text: "Partial" }]);
    expect(error).toBeInstanceOf(ChatError);
    expect(error?.kind).toBe("answer_error");
    expect(error?.message).toBe("All providers failed");
  });

  it("reports a stream that ends before done as interrupted", async () => {
    const error = await failure(
      streamChat(
        BASE,
        { question: "q" },
        {
          fetchImpl: fetchReturning(sseResponse(sse("token", { text: "Part" }))),
        },
      ),
    );

    expect(error.kind).toBe("interrupted");
  });

  it("reports a connection lost mid-stream as interrupted", async () => {
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(sse("token", { text: "Part" })));
        controller.error(new TypeError("network error"));
      },
    });
    const response = new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    });

    const error = await failure(
      streamChat(BASE, { question: "q" }, { fetchImpl: fetchReturning(response) }),
    );

    expect(error.kind).toBe("interrupted");
  });

  it.each([
    ["invalid JSON", "event: token\ndata: {nope\n\n"],
    ["a token without text", sse("token", { txt: "x" })],
    ["data that isn't an object", sse("token", ["x"])],
    ["a tool with a bad status", sse("tool", { name: "x", status: "running" })],
    ["a table with a bad row", sse("table", { columns: ["a"], rows: ["not a row"] })],
    [
      "a citation without a url",
      sse("citation", { id: "S1", title: "t", section: null, season: null }),
    ],
    ["a done without tokens", sse("done", { ...DONE, prompt_tokens: "900" })],
  ])("rejects %s as bad_response", async (_name, body) => {
    const error = await failure(
      streamChat(
        BASE,
        { question: "q" },
        { fetchImpl: fetchReturning(sseResponse(body)) },
      ),
    );

    expect(error.kind).toBe("bad_response");
  });

  it("reports 429 with the Retry-After seconds", async () => {
    const response = new Response(JSON.stringify({ detail: "Too many requests" }), {
      status: 429,
      headers: { "Retry-After": "57", "Content-Type": "application/json" },
    });

    const error = await failure(
      streamChat(BASE, { question: "q" }, { fetchImpl: fetchReturning(response) }),
    );

    expect(error.kind).toBe("rate_limited");
    expect(error.retryAfterSeconds).toBe(57);
    expect(error.message).toBe("Too many questions for now. Try again in 57 seconds.");
  });

  it("falls back to 60 seconds when Retry-After is missing or unreadable", async () => {
    for (const header of [null, "soon", "-5"]) {
      const headers = new Headers();
      if (header) headers.set("Retry-After", header);
      const error = await failure(
        streamChat(
          BASE,
          { question: "q" },
          { fetchImpl: fetchReturning(new Response(null, { status: 429, headers })) },
        ),
      );
      expect(error.retryAfterSeconds).toBe(60);
    }
  });

  it("reports 422 as invalid_request", async () => {
    const error = await failure(
      streamChat(
        BASE,
        { question: "q" },
        { fetchImpl: fetchReturning(new Response("{}", { status: 422 })) },
      ),
    );

    expect(error.kind).toBe("invalid_request");
  });

  it("shows the backend's detail for other statuses, or a generic message", async () => {
    const withDetail = new Response(JSON.stringify({ detail: "Internal server error" }), {
      status: 500,
    });
    const without = new Response("<html>bad gateway</html>", { status: 502 });

    const first = await failure(
      streamChat(BASE, { question: "q" }, { fetchImpl: fetchReturning(withDetail) }),
    );
    const second = await failure(
      streamChat(BASE, { question: "q" }, { fetchImpl: fetchReturning(without) }),
    );

    expect([first.kind, first.message]).toEqual(["http_error", "Internal server error"]);
    expect([second.kind, second.message]).toEqual([
      "http_error",
      "ApexGPT is having trouble (HTTP 502). Please try again.",
    ]);
  });

  it("rejects a 200 that isn't an event stream", async () => {
    const response = new Response("{}", {
      headers: { "Content-Type": "application/json" },
    });

    const error = await failure(
      streamChat(BASE, { question: "q" }, { fetchImpl: fetchReturning(response) }),
    );

    expect(error.kind).toBe("bad_response");
  });

  it("reports a network failure as unreachable", async () => {
    const fetchImpl = vi
      .fn<typeof fetch>()
      .mockRejectedValue(new TypeError("Failed to fetch"));

    const error = await failure(streamChat(BASE, { question: "q" }, { fetchImpl }));

    expect(error.kind).toBe("unreachable");
  });

  it("rethrows an abort instead of a ChatError", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(async () => {
      controller.abort();
      throw new DOMException("aborted", "AbortError");
    });

    await expect(
      collect(
        streamChat(BASE, { question: "q" }, { fetchImpl, signal: controller.signal }),
      ),
    ).rejects.toMatchObject({ name: "AbortError" });
  });

  it("rethrows an abort during the stream", async () => {
    const controller = new AbortController();
    // Like a real fetch: aborting errors the response body.
    const body = new ReadableStream<Uint8Array>({
      start(c) {
        c.enqueue(encoder.encode(sse("token", { text: "Part" })));
        controller.signal.addEventListener("abort", () =>
          c.error(new DOMException("aborted", "AbortError")),
        );
      },
    });
    const response = new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    });
    const stream = streamChat(
      BASE,
      { question: "q" },
      {
        fetchImpl: fetchReturning(response),
        signal: controller.signal,
      },
    );

    await stream.next();
    const pending = stream.next();
    controller.abort();

    const error = await pending.catch((e: unknown) => e);
    expect(error).not.toBeInstanceOf(ChatError);
    expect(error).toMatchObject({ name: "AbortError" });
  });
});

describe("parseFrame", () => {
  it("joins multi-line data and ignores ids", () => {
    expect(parseFrame('id: 4\nevent: token\ndata: {"text":\ndata: "a"}')).toEqual({
      type: "token",
      text: "a",
    });
  });

  it("returns null without data", () => {
    expect(parseFrame("event: token")).toBeNull();
    expect(parseFrame(": comment")).toBeNull();
  });
});

describe("readFrames", () => {
  it("yields a final frame without a trailing blank line", async () => {
    const frames: string[] = [];
    for await (const f of readFrames(
      byteStream("event: a\ndata: 1\n\nevent: b\ndata: 2", 3),
    )) {
      frames.push(f);
    }

    expect(frames).toEqual(["event: a\ndata: 1", "event: b\ndata: 2"]);
  });
});
