import { afterEach, describe, expect, it, vi } from "vitest";

import type { AssistantMessage, Message } from "./conversation";
import {
  MAX_CONVERSATIONS,
  STORAGE_KEY,
  browserStorage,
  cleanTitle,
  deleteConversation,
  loadConversations,
  parseStore,
  renameConversation,
  saveConversation,
  storedMessages,
  titleFrom,
  type StoredConversation,
} from "./history";
import { MemoryStorage } from "@/test/storage";

const SOURCE = {
  id: "S1",
  title: "1976 Japanese Grand Prix",
  url: "https://en.wikipedia.org/wiki/1976_Japanese_Grand_Prix",
  section: "Race",
  season: 1976,
};
const DONE = {
  question: "Who won 1976?",
  provider: "groq",
  model: "m",
  sources: ["S1"],
  tools: [{ name: "query_stats", ok: true }],
  latencyMs: 10,
  promptTokens: 1,
  completionTokens: 2,
  cached: false,
};

function answer(overrides: Partial<AssistantMessage> = {}): AssistantMessage {
  return {
    id: "a1",
    role: "assistant",
    status: "done",
    content: "James Hunt [S1].",
    tables: [{ columns: ["champion"], rows: [["James Hunt"]], note: "1 row" }],
    citations: [SOURCE],
    done: DONE,
    ...overrides,
  };
}

function chat(id: string, updatedAt: number, extra: Partial<StoredConversation> = {}) {
  return {
    id,
    title: `Chat ${id}`,
    createdAt: updatedAt,
    updatedAt,
    messages: [
      { id: `q-${id}`, role: "user", content: "Who won 1976?" },
      answer(),
    ] as Message[],
    ...extra,
  };
}

const store = (conversations: unknown[]) => JSON.stringify({ version: 1, conversations });

afterEach(() => vi.unstubAllGlobals());

describe("titles", () => {
  it("titles a chat by its first question, on one line and shortened", () => {
    expect(titleFrom([{ id: "1", role: "user", content: "  Who won\n 1976? " }])).toBe(
      "Who won 1976?",
    );
    const long = titleFrom([{ id: "1", role: "user", content: "a".repeat(100) }]);
    expect(Array.from(long)).toHaveLength(60);
    expect(long.endsWith("…")).toBe(true);
    expect(titleFrom([])).toBe("New chat");
  });

  it("never splits an emoji when shortening", () => {
    const title = titleFrom([{ id: "1", role: "user", content: "🏎️".repeat(40) }]);
    expect(title).not.toMatch(/[\uD800-\uDBFF](?![\uDC00-\uDFFF])/);
  });

  it("tidies a typed title, and rejects a blank one", () => {
    expect(cleanTitle("  Hunt \t vs  Lauda ")).toBe("Hunt vs Lauda");
    expect(Array.from(cleanTitle("x".repeat(200))!)).toHaveLength(80);
    expect(cleanTitle(" \n ")).toBeNull();
  });
});

describe("parseStore", () => {
  it("reads stored conversations, newest first", () => {
    const list = parseStore(store([chat("old", 1), chat("new", 2)]));

    expect(list.map((c) => c.id)).toEqual(["new", "old"]);
    expect(list[0].messages[1]).toEqual(answer());
  });

  it.each([
    ["nothing", null],
    ["broken JSON", "{nope"],
    ["another version", JSON.stringify({ version: 2, conversations: [chat("a", 1)] })],
    ["a non-list", JSON.stringify({ version: 1, conversations: {} })],
  ])("is empty for %s", (_, raw) => {
    expect(parseStore(raw)).toEqual([]);
  });

  it("drops a malformed conversation and keeps the rest", () => {
    const bad = [
      { ...chat("no-title", 1), title: 5 },
      { ...chat("no-messages", 1), messages: [] },
      { ...chat("bad-role", 1), messages: [{ id: "x", role: "system", content: "hi" }] },
      { ...chat("bad-status", 1), messages: [answer({ status: "weird" as never })] },
      {
        ...chat("bad-table", 1),
        messages: [answer({ tables: [{ columns: "x" }] as never })],
      },
      chat("", 1),
      "junk",
    ];

    expect(parseStore(store([...bad, chat("good", 1)])).map((c) => c.id)).toEqual([
      "good",
    ]);
  });

  it("drops a conversation whose source link isn't http(s)", () => {
    const evil = answer({ citations: [{ ...SOURCE, url: "javascript:alert(1)" }] });

    expect(parseStore(store([{ ...chat("x", 1), messages: [evil] }]))).toEqual([]);
  });

  it("keeps an answer whose details are malformed, without them", () => {
    const list = parseStore(
      store([{ ...chat("x", 1), messages: [{ ...answer(), done: { cached: "no" } }] }]),
    );

    expect((list[0].messages[0] as AssistantMessage).done).toBeUndefined();
  });

  it("keeps one copy of a repeated id, a title for a blank one, and 50 at most", () => {
    const many = Array.from({ length: 60 }, (_, i) => chat(`c${i}`, i));
    const list = parseStore(store([chat("c59", 100, { title: "  " }), ...many]));

    expect(list).toHaveLength(MAX_CONVERSATIONS);
    expect(list[0]).toMatchObject({ id: "c59", title: "Who won 1976?" });
    expect(list.filter((c) => c.id === "c59")).toHaveLength(1);
  });

  it("restores an answer that was still streaming as stopped", () => {
    const list = parseStore(
      store([{ ...chat("x", 1), messages: [answer({ status: "streaming" })] }]),
    );

    expect(list[0].messages[0]).toMatchObject({ status: "stopped" });
  });
});

describe("ratings", () => {
  it("keeps an answer's rating through a save", () => {
    const storage = new MemoryStorage();
    const rated = chat("a", 1, {
      messages: [{ id: "q", role: "user", content: "q" }, answer({ feedback: "up" })],
    });

    saveConversation(storage, rated);

    expect((loadConversations(storage)[0].messages[1] as AssistantMessage).feedback).toBe(
      "up",
    );
  });

  it("drops a conversation with an unknown rating", () => {
    const bad = { ...chat("x", 1), messages: [{ ...answer(), feedback: "meh" }] };

    expect(parseStore(store([bad, chat("ok", 1)])).map((c) => c.id)).toEqual(["ok"]);
  });
});

describe("storedMessages", () => {
  it("keeps a streaming answer as stopped, without live-only fields", () => {
    const [m] = storedMessages([
      answer({ status: "streaming", activeTool: "query_stats", retryAfterSeconds: 30 }),
    ]);

    expect(m).toEqual(answer({ status: "stopped" }));
  });
});

describe("saving", () => {
  it("adds a conversation and reads it back", () => {
    const storage = new MemoryStorage();

    const result = saveConversation(storage, chat("a", 1));

    expect(result.saved).toBe(true);
    expect(loadConversations(storage)).toEqual([chat("a", 1)]);
  });

  it("puts the saved conversation on top and replaces its old copy", () => {
    const storage = new MemoryStorage();
    saveConversation(storage, chat("a", 1));
    saveConversation(storage, chat("b", 2));

    const { conversations } = saveConversation(storage, chat("a", 3, { title: "A2" }));

    expect(conversations.map((c) => [c.id, c.title])).toEqual([
      ["a", "A2"],
      ["b", "Chat b"],
    ]);
    expect(loadConversations(storage)).toEqual(conversations);
  });

  it("keeps a conversation another tab saved in the meantime", () => {
    const storage = new MemoryStorage();
    saveConversation(storage, chat("mine", 1));
    storage.setItem(STORAGE_KEY, store([chat("mine", 1), chat("other-tab", 2)]));

    saveConversation(storage, chat("mine", 3));

    expect(loadConversations(storage).map((c) => c.id)).toEqual(["mine", "other-tab"]);
  });

  it("keeps the newest 50", () => {
    const storage = new MemoryStorage();
    for (let i = 0; i < 55; i++) saveConversation(storage, chat(`c${i}`, i));

    const list = loadConversations(storage);
    expect(list).toHaveLength(50);
    expect(list[0].id).toBe("c54");
    expect(list.at(-1)!.id).toBe("c5");
    expect(JSON.parse(storage.getItem(STORAGE_KEY)!).conversations).toHaveLength(50);
  });

  it("drops the oldest others when the quota is full", () => {
    const one = store([chat("a", 1)]).length;
    const storage = new MemoryStorage(Math.floor(one * 2.5));
    saveConversation(storage, chat("a", 1));
    saveConversation(storage, chat("b", 2));

    const result = saveConversation(storage, chat("c", 3));

    expect(result.saved).toBe(true);
    expect(loadConversations(storage).map((c) => c.id)).toEqual(["c", "b"]);
  });

  it("reports failure when even the one conversation doesn't fit", () => {
    const storage = new MemoryStorage(50);

    expect(saveConversation(storage, chat("a", 1)).saved).toBe(false);
    expect(loadConversations(storage)).toEqual([]);
  });

  it("survives storage that throws on every call", () => {
    const broken = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("blocked");
      },
    } as unknown as Storage;

    expect(loadConversations(broken)).toEqual([]);
    expect(saveConversation(broken, chat("a", 1)).saved).toBe(false);
    expect(deleteConversation(broken, "a").saved).toBe(false);
  });
});

describe("rename and delete", () => {
  it("renames in place, tidying the title", () => {
    const storage = new MemoryStorage();
    saveConversation(storage, chat("a", 1));
    saveConversation(storage, chat("b", 2));

    const result = renameConversation(storage, "a", "  Hunt   1976 ");

    expect(result.saved).toBe(true);
    expect(loadConversations(storage).map((c) => [c.id, c.title])).toEqual([
      ["b", "Chat b"],
      ["a", "Hunt 1976"],
    ]);
  });

  it("refuses a blank title or an unknown chat", () => {
    const storage = new MemoryStorage();
    saveConversation(storage, chat("a", 1));
    const writes = storage.writes;

    expect(renameConversation(storage, "a", "   ").saved).toBe(false);
    expect(renameConversation(storage, "zzz", "Title").saved).toBe(false);
    expect(storage.writes).toBe(writes);
    expect(loadConversations(storage)[0].title).toBe("Chat a");
  });

  it("deletes one conversation", () => {
    const storage = new MemoryStorage();
    saveConversation(storage, chat("a", 1));
    saveConversation(storage, chat("b", 2));

    expect(deleteConversation(storage, "a")).toMatchObject({ saved: true });
    expect(loadConversations(storage).map((c) => c.id)).toEqual(["b"]);
  });
});

describe("browserStorage", () => {
  it("is localStorage when there is one", () => {
    expect(browserStorage()).toBe(window.localStorage);
  });

  it("is null when the browser blocks it", () => {
    vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
      throw new DOMException("blocked", "SecurityError");
    });

    expect(browserStorage()).toBeNull();
  });
});
