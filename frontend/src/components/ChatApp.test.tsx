import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { STORAGE_KEY, loadConversations, saveConversation } from "@/lib/history";
import { notifyStored } from "@/lib/useStoredConversations";
import { MemoryStorage } from "@/test/storage";
import { FakeStream, INFO } from "@/test/stream";

import { ChatApp } from "./ChatApp";

const BASE = "http://backend.test";

function setup(storage: Storage | null = new MemoryStorage()) {
  const fake = new FakeStream();
  const user = userEvent.setup();
  const view = render(<ChatApp apiBaseUrl={BASE} storage={storage} stream={fake.fn} />);
  const chats = () => screen.getByRole("navigation", { name: "Chats" });
  return {
    fake,
    user,
    view,
    storage,
    chats,
    input: () => screen.getByLabelText("Your question"),
  };
}

function seed(storage: Storage, id: string, question: string, reply: string, at: number) {
  saveConversation(storage, {
    id,
    title: question,
    createdAt: at,
    updatedAt: at,
    messages: [
      { id: `${id}-q`, role: "user", content: question },
      {
        id: `${id}-a`,
        role: "assistant",
        status: "done",
        content: reply,
        tables: [],
        citations: [],
      },
    ],
  });
}

async function askAndFinish(
  { fake, user, input }: ReturnType<typeof setup>,
  question: string,
  reply: string,
) {
  await user.type(input(), `${question}{Enter}`);
  act(() => fake.push({ type: "token", text: reply }, { type: "done", info: INFO }));
  await screen.findByText(reply);
  await waitFor(() =>
    expect(screen.getByRole("button", { name: "Send" })).toBeInTheDocument(),
  );
}

describe("ChatApp", () => {
  it("opens on a new chat and saves it, titled by its first question", async () => {
    const app = setup();
    expect(screen.getByRole("list", { name: "Starter questions" })).toBeInTheDocument();

    await askAndFinish(app, "Who won the 1976 title?", "James Hunt.");

    const [saved] = loadConversations(app.storage!);
    expect(saved.title).toBe("Who won the 1976 title?");
    expect(saved.messages.map((m) => m.content)).toEqual([
      "Who won the 1976 title?",
      "James Hunt.",
    ]);
    expect(saved.messages[1]).toMatchObject({ status: "done" });
    const row = within(app.chats()).getByRole("button", {
      name: "Who won the 1976 title?",
    });
    expect(row).toHaveAttribute("aria-current", "page");
  });

  it("lists saved chats newest first and opens one where it left off", async () => {
    const storage = new MemoryStorage();
    seed(storage, "old", "Who won 1976?", "James Hunt.", 1);
    seed(storage, "new", "Who won 1988?", "Ayrton Senna.", 2);
    const app = setup(storage);

    const rows = within(app.chats()).getAllByRole("button", { name: /^Who won/ });
    expect(rows.map((r) => r.textContent)).toEqual(["Who won 1988?", "Who won 1976?"]);
    expect(screen.queryByText("James Hunt.")).not.toBeInTheDocument(); // a new chat first

    await app.user.click(rows[1]);

    expect(screen.getByText("James Hunt.")).toBeInTheDocument();
    await app.user.type(app.input(), "By how much?{Enter}");
    expect(app.fake.requests[0].history).toEqual([
      { role: "user", content: "Who won 1976?" },
      { role: "assistant", content: "James Hunt." },
    ]);
  });

  it("starts a new chat, and doesn't save an empty one", async () => {
    const app = setup();
    await askAndFinish(app, "Who won 1976?", "James Hunt.");

    await app.user.click(within(app.chats()).getByRole("button", { name: "+ New chat" }));

    expect(screen.getByRole("list", { name: "Starter questions" })).toBeInTheDocument();
    expect(loadConversations(app.storage!)).toHaveLength(1);

    await askAndFinish(app, "Who won 1988?", "Ayrton Senna.");
    expect(loadConversations(app.storage!).map((c) => c.title)).toEqual([
      "Who won 1988?",
      "Who won 1976?",
    ]);
  });

  it("keeps a typed draft when New chat is pressed on an empty chat", async () => {
    const app = setup();
    await app.user.type(app.input(), "half a question");

    await app.user.click(within(app.chats()).getByRole("button", { name: "+ New chat" }));

    expect(app.input()).toHaveValue("half a question");
  });

  it("keeps a part-streamed answer, as stopped, when another chat is opened", async () => {
    const storage = new MemoryStorage();
    seed(storage, "old", "Who won 1976?", "James Hunt.", 1);
    const app = setup(storage);
    await app.user.type(app.input(), "Tell me about Senna{Enter}");
    act(() => app.fake.push({ type: "token", text: "Ayrton Senna was" }));
    await screen.findByText("Ayrton Senna was");

    await app.user.click(
      within(app.chats()).getByRole("button", { name: "Who won 1976?" }),
    );

    expect(app.fake.signals[0].aborted).toBe(true);
    const senna = loadConversations(storage).find(
      (c) => c.title === "Tell me about Senna",
    )!;
    expect(senna.messages[1]).toMatchObject({
      status: "stopped",
      content: "Ayrton Senna was",
    });

    await app.user.click(
      within(app.chats()).getByRole("button", { name: "Tell me about Senna" }),
    );
    expect(screen.getByText("Ayrton Senna was")).toBeInTheDocument();
    expect(screen.getByText("Stopped.")).toBeInTheDocument();
  });

  it("renames a chat with Enter, and Escape cancels", async () => {
    const storage = new MemoryStorage();
    seed(storage, "a", "Who won 1976?", "James Hunt.", 1);
    const app = setup(storage);

    await app.user.click(screen.getByRole("button", { name: "Rename “Who won 1976?”" }));
    const field = screen.getByRole("textbox", { name: "Chat title" });
    expect(field).toHaveFocus();
    await app.user.clear(field);
    await app.user.type(field, "Hunt's title{Enter}");

    expect(loadConversations(storage)[0].title).toBe("Hunt's title");
    expect(
      within(app.chats()).getByRole("button", { name: "Hunt's title" }),
    ).toBeInTheDocument();

    await app.user.click(screen.getByRole("button", { name: "Rename “Hunt's title”" }));
    await app.user.type(
      screen.getByRole("textbox", { name: "Chat title" }),
      " nope{Escape}",
    );

    expect(loadConversations(storage)[0].title).toBe("Hunt's title");
    expect(screen.queryByRole("textbox", { name: "Chat title" })).not.toBeInTheDocument();
  });

  it("keeps a renamed title as the chat goes on", async () => {
    const storage = new MemoryStorage();
    seed(storage, "a", "Who won 1976?", "James Hunt.", 1);
    const app = setup(storage);
    await app.user.click(screen.getByRole("button", { name: "Rename “Who won 1976?”" }));
    const field = screen.getByRole("textbox", { name: "Chat title" });
    await app.user.clear(field);
    await app.user.type(field, "Hunt 1976{Enter}");
    await app.user.click(within(app.chats()).getByRole("button", { name: "Hunt 1976" }));

    await askAndFinish(app, "By how much?", "One point.");

    expect(loadConversations(storage)[0]).toMatchObject({ id: "a", title: "Hunt 1976" });
  });

  it("ignores the blur as the field closes after Escape", () => {
    const storage = new MemoryStorage();
    seed(storage, "a", "Who won 1976?", "James Hunt.", 1);
    setup(storage);
    fireEvent.click(screen.getByRole("button", { name: "Rename “Who won 1976?”" }));
    const field = screen.getByRole("textbox", { name: "Chat title" });
    fireEvent.change(field, { target: { value: "Changed" } });

    act(() => {
      fireEvent.keyDown(field, { key: "Escape" });
      fireEvent.blur(field); // some browsers blur an input as it is removed
    });

    expect(loadConversations(storage)[0].title).toBe("Who won 1976?");
  });

  it("keeps the old title when the new one is blank", async () => {
    const storage = new MemoryStorage();
    seed(storage, "a", "Who won 1976?", "James Hunt.", 1);
    const app = setup(storage);

    await app.user.click(screen.getByRole("button", { name: "Rename “Who won 1976?”" }));
    await app.user.clear(screen.getByRole("textbox", { name: "Chat title" }));
    await app.user.keyboard("{Enter}");

    expect(loadConversations(storage)[0].title).toBe("Who won 1976?");
  });

  it("deletes a chat after confirming, and a deleted open chat becomes a new one", async () => {
    const storage = new MemoryStorage();
    seed(storage, "a", "Who won 1976?", "James Hunt.", 1);
    seed(storage, "b", "Who won 1988?", "Ayrton Senna.", 2);
    const app = setup(storage);
    await app.user.click(
      within(app.chats()).getByRole("button", { name: "Who won 1976?" }),
    );

    await app.user.click(screen.getByRole("button", { name: "Delete “Who won 1976?”" }));
    await app.user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(loadConversations(storage)).toHaveLength(2);

    await app.user.click(screen.getByRole("button", { name: "Delete “Who won 1976?”" }));
    await app.user.click(screen.getByRole("button", { name: "Delete" }));

    expect(loadConversations(storage).map((c) => c.id)).toEqual(["b"]);
    expect(screen.queryByText("James Hunt.")).not.toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Starter questions" })).toBeInTheDocument();
  });

  it("doesn't bring back a chat deleted while it was answering", async () => {
    const app = setup();
    await app.user.type(app.input(), "Tell me about Senna{Enter}");
    act(() => app.fake.push({ type: "token", text: "Ayrton" }));
    await screen.findByText("Ayrton");

    await app.user.click(
      screen.getByRole("button", { name: "Delete “Tell me about Senna”" }),
    );
    await app.user.click(screen.getByRole("button", { name: "Delete" }));

    expect(app.fake.signals[0].aborted).toBe(true);
    expect(loadConversations(app.storage!)).toEqual([]);
  });

  it("picks up chats another tab saved", async () => {
    const app = setup();
    expect(within(app.chats()).queryAllByRole("listitem")).toHaveLength(0);

    act(() => {
      seed(app.storage!, "x", "Who won 2021?", "Max Verstappen.", 5);
      window.dispatchEvent(new StorageEvent("storage", { key: STORAGE_KEY }));
    });

    expect(
      within(app.chats()).getByRole("button", { name: "Who won 2021?" }),
    ).toBeInTheDocument();
  });

  it("says when a chat couldn't be saved, and carries on", async () => {
    const app = setup(new MemoryStorage(100));

    await askAndFinish(app, "Who won the 1976 title?", "James Hunt.");

    expect(screen.getByText(/This chat couldn't be saved/)).toHaveAttribute(
      "role",
      "status",
    );
    expect(screen.getByText("James Hunt.")).toBeInTheDocument();
  });

  it("works without storage, and says chats aren't kept", async () => {
    const app = setup(null);

    await askAndFinish(app, "Who won 1976?", "James Hunt.");

    expect(app.chats()).toHaveTextContent("This browser can't save chats");
    expect(within(app.chats()).queryAllByRole("listitem")).toHaveLength(0);
  });

  it("opens the chats drawer on phones and closes it with Escape or on picking", async () => {
    const storage = new MemoryStorage();
    seed(storage, "a", "Who won 1976?", "James Hunt.", 1);
    const app = setup(storage);

    await app.user.click(screen.getByRole("button", { name: "☰ Chats (1)" }));
    const drawer = screen.getByRole("dialog", { name: "Saved chats" });
    await app.user.keyboard("{Escape}");
    expect(drawer).not.toBeInTheDocument();

    await app.user.click(screen.getByRole("button", { name: "☰ Chats (1)" }));
    const inDrawer = within(screen.getByRole("dialog", { name: "Saved chats" }));
    await app.user.click(inDrawer.getByRole("button", { name: "Who won 1976?" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByText("James Hunt.")).toBeInTheDocument();
  });

  it("re-reads when this tab saves elsewhere", () => {
    const app = setup();

    act(() => {
      seed(app.storage!, "y", "Who won 1950?", "Nino Farina.", 1);
      notifyStored();
    });

    expect(
      within(app.chats()).getByRole("button", { name: "Who won 1950?" }),
    ).toBeInTheDocument();
  });
});
