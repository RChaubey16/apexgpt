/** For tests: a controllable fake of `streamChat`, and a `done` payload. */

import type { ChatEvent, ChatRequest, DoneInfo, streamChat } from "@/lib/chat";

export const INFO: DoneInfo = {
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
export class FakeStream {
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
