"use client";

/**
 * The saved chats: "New chat", then one row per conversation (newest first)
 * that opens it, with rename (inline, Enter saves and Escape cancels) and
 * delete (asks to confirm inline, never with a browser dialog).
 */

import { useRef, useState } from "react";

import { MAX_TITLE_CHARS, type StoredConversation } from "@/lib/history";

interface ConversationListProps {
  conversations: StoredConversation[];
  /** The open chat, or null for a new one not yet saved. */
  activeId: string | null;
  /** False when the browser can't store chats. */
  available: boolean;
  onSelect: (id: string) => void;
  onNew: () => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

export function ConversationList({
  conversations,
  activeId,
  available,
  onSelect,
  onNew,
  onRename,
  onDelete,
}: ConversationListProps) {
  return (
    <nav aria-label="Chats" className="flex flex-col gap-3">
      <button
        type="button"
        onClick={onNew}
        className="rounded-lg border border-zinc-700 px-3 py-2 text-left text-sm font-medium text-zinc-200 hover:border-red-600/70 hover:bg-zinc-900"
      >
        + New chat
      </button>
      {conversations.length > 0 && (
        <ul className="flex flex-col gap-0.5">
          {conversations.map((c) => (
            <ConversationRow
              key={c.id}
              conversation={c}
              active={c.id === activeId}
              onSelect={onSelect}
              onRename={onRename}
              onDelete={onDelete}
            />
          ))}
        </ul>
      )}
      <p className="px-1 text-xs text-zinc-600">
        {available
          ? "Chats are saved in this browser only."
          : "This browser can't save chats, so they're lost when you leave or start a new one."}
      </p>
    </nav>
  );
}

interface RowProps {
  conversation: StoredConversation;
  active: boolean;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
}

const iconButton =
  "rounded px-1.5 py-1 text-xs text-zinc-500 hover:bg-zinc-800 hover:text-zinc-200";

function ConversationRow({
  conversation,
  active,
  onSelect,
  onRename,
  onDelete,
}: RowProps) {
  const [mode, setMode] = useState<"view" | "rename" | "confirm-delete">("view");
  const [title, setTitle] = useState(conversation.title);
  // Once Enter/Escape has ended the edit, the blur as the input goes away is ignored.
  const editing = useRef(false);
  const { id } = conversation;

  if (mode === "rename") {
    const finish = (save: boolean) => {
      if (!editing.current) return;
      editing.current = false;
      if (save && title.trim() && title !== conversation.title) onRename(id, title);
      setMode("view");
    };
    return (
      <li>
        <input
          aria-label="Chat title"
          value={title}
          maxLength={MAX_TITLE_CHARS}
          autoFocus
          onChange={(e) => setTitle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") finish(true);
            if (e.key === "Escape") finish(false);
          }}
          onBlur={() => finish(true)}
          className="w-full rounded-lg border border-red-600 bg-zinc-900 px-3 py-1.5 text-sm text-zinc-100 focus:outline-none"
        />
      </li>
    );
  }

  if (mode === "confirm-delete") {
    return (
      <li className="flex items-center gap-1 rounded-lg bg-zinc-900 px-3 py-1.5 text-sm">
        <span className="min-w-0 flex-1 truncate text-zinc-300">
          Delete “{conversation.title}”?
        </span>
        <button
          type="button"
          onClick={() => onDelete(id)}
          className="rounded px-2 py-1 text-xs font-semibold text-red-300 hover:bg-red-950"
        >
          Delete
        </button>
        <button type="button" onClick={() => setMode("view")} className={iconButton}>
          Cancel
        </button>
      </li>
    );
  }

  return (
    <li
      className={`group flex items-center gap-1 rounded-lg pr-1 ${active ? "bg-zinc-800" : "hover:bg-zinc-900"}`}
    >
      <button
        type="button"
        onClick={() => onSelect(id)}
        aria-current={active ? "page" : undefined}
        title={conversation.title}
        className={`min-w-0 flex-1 truncate px-3 py-1.5 text-left text-sm ${active ? "text-white" : "text-zinc-300"}`}
      >
        {conversation.title}
      </button>
      <button
        type="button"
        onClick={() => {
          editing.current = true;
          setTitle(conversation.title);
          setMode("rename");
        }}
        aria-label={`Rename “${conversation.title}”`}
        className={iconButton}
      >
        Rename
      </button>
      <button
        type="button"
        onClick={() => setMode("confirm-delete")}
        aria-label={`Delete “${conversation.title}”`}
        className={iconButton}
      >
        Delete
      </button>
    </li>
  );
}
