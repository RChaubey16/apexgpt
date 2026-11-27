"use client";

/**
 * The chat page body: the saved chats beside the open one.
 *
 * - A visit opens on a new, empty chat; saved ones are listed beside it (a
 *   drawer on phones) and open where they left off.
 * - A new chat is saved with its first question, and again as answers end.
 *   Leaving a chat mid-answer stops the answer and keeps what had arrived.
 * - Opening another chat mounts a fresh <Chat> (a new `key`).
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { Chat } from "@/components/Chat";
import { ConversationList } from "@/components/ConversationList";
import type { streamChat } from "@/lib/chat";
import type { Message } from "@/lib/conversation";
import {
  browserStorage,
  deleteConversation,
  loadConversations,
  renameConversation,
  saveConversation,
  titleFrom,
} from "@/lib/history";
import {
  notifyStored,
  useHydrated,
  useStoredConversations,
} from "@/lib/useStoredConversations";

let counter = 0;
const newChatId = () => `c-${Date.now().toString(36)}-${++counter}`;

interface ChatAppProps {
  /** Validated backend URL, or null if config is invalid. */
  apiBaseUrl: string | null;
  /** For tests: where chats are kept (null: nowhere). Defaults to localStorage. */
  storage?: Storage | null;
  /** For tests: the streaming client. */
  stream?: typeof streamChat;
}

export function ChatApp({ apiBaseUrl, storage: storageOverride, stream }: ChatAppProps) {
  const hydrated = useHydrated();
  const storage =
    storageOverride !== undefined ? storageOverride : hydrated ? browserStorage() : null;
  const conversations = useStoredConversations(storage);
  // The open chat: `key` mounts a fresh <Chat>; `id` is null for a new chat
  // until its first save gives it one (the clock can't be read while rendering).
  const [view, setView] = useState<{ key: number; id: string | null }>({
    key: 0,
    id: null,
  });
  const activeId = view.id;
  const [saveFailed, setSaveFailed] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const active = conversations.find((c) => c.id === activeId);
  // A deleted chat still answering reports once more as it unmounts: ignore it.
  const deleted = useRef(new Set<string>());

  const persist = useCallback(
    (key: number, knownId: string | null, messages: Message[]) => {
      if (!storage || messages.length === 0) return;
      // A new chat's first save (its question) gives it an id; the re-render
      // passes that id to its later saves.
      const id = knownId ?? newChatId();
      if (!knownId) setView((v) => (v.key === key ? { key, id } : v));
      if (deleted.current.has(id)) return;
      const existing = loadConversations(storage).find((c) => c.id === id);
      const now = Date.now();
      const result = saveConversation(storage, {
        id,
        title: existing?.title ?? titleFrom(messages),
        createdAt: existing?.createdAt ?? now,
        updatedAt: now,
        messages,
      });
      setSaveFailed(!result.saved);
      notifyStored();
    },
    [storage],
  );

  const open = (id: string) => {
    setDrawerOpen(false);
    if (id === activeId) return;
    setSaveFailed(false);
    setView((v) => ({ key: v.key + 1, id }));
  };

  const startNew = () => {
    setDrawerOpen(false);
    if (!active) return; // already on a new, empty chat
    setSaveFailed(false);
    setView((v) => ({ key: v.key + 1, id: null }));
  };

  const rename = (id: string, title: string) => {
    if (!storage) return;
    renameConversation(storage, id, title);
    notifyStored();
  };

  const remove = (id: string) => {
    if (!storage) return;
    deleted.current.add(id);
    deleteConversation(storage, id);
    notifyStored();
    if (id === activeId) {
      setSaveFailed(false);
      setView((v) => ({ key: v.key + 1, id: null }));
    }
  };

  // Escape closes the drawer.
  useEffect(() => {
    if (!drawerOpen) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setDrawerOpen(false);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [drawerOpen]);

  const list = (
    <ConversationList
      conversations={conversations}
      activeId={activeId}
      available={!hydrated || storage !== null}
      onSelect={open}
      onNew={startNew}
      onRename={rename}
      onDelete={remove}
    />
  );

  return (
    <div className="flex min-h-0 flex-1">
      <aside className="hidden w-60 shrink-0 overflow-y-auto border-r border-line bg-background p-3 md:block lg:w-64">
        {list}
      </aside>

      {drawerOpen && (
        <div
          className="fixed inset-0 z-20 md:hidden"
          role="dialog"
          aria-modal="true"
          aria-label="Saved chats"
        >
          <button
            type="button"
            aria-label="Close chats"
            onClick={() => setDrawerOpen(false)}
            className="absolute inset-0 bg-black/70"
          />
          <div className="absolute inset-y-0 left-0 w-72 max-w-[85%] overflow-y-auto border-r border-line bg-surface p-3 pt-[max(0.75rem,env(safe-area-inset-top))] pb-[max(0.75rem,env(safe-area-inset-bottom))] pl-[max(0.75rem,env(safe-area-inset-left))]">
            {list}
          </div>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-center justify-between gap-2 border-b border-line px-2 py-1 md:hidden">
          <button
            type="button"
            onClick={() => setDrawerOpen(true)}
            aria-expanded={drawerOpen}
            className="min-h-10 rounded-md px-3 text-sm text-soft hover:bg-raised hover:text-foreground"
          >
            <span aria-hidden="true">☰ </span>
            Chats{conversations.length > 0 && ` (${conversations.length})`}
          </button>
          {active && (
            <button
              type="button"
              onClick={startNew}
              className="min-h-10 rounded-md px-3 text-sm text-soft hover:bg-raised hover:text-foreground"
            >
              New chat
            </button>
          )}
        </div>
        {saveFailed && (
          <p
            role="status"
            className="border-b border-warning/40 bg-warning-bg px-4 py-1.5 text-center text-xs text-warning-text"
          >
            This chat couldn&apos;t be saved in the browser (its storage may be full).
          </p>
        )}
        <Chat
          key={view.key}
          apiBaseUrl={apiBaseUrl}
          initialMessages={active?.messages}
          onMessagesChange={(messages) => persist(view.key, view.id, messages)}
          stream={stream}
        />
      </div>
    </div>
  );
}
