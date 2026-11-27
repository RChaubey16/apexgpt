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
        className="min-h-9 rounded-md bg-accent px-3 text-left text-sm font-bold text-on-accent hover:bg-accent-strong"
      >
        New chat
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
      <p className="px-1 text-xs text-muted">
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
  "min-h-8 rounded px-1.5 text-xs text-muted hover:bg-hover hover:text-foreground";

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
          className="w-full rounded-md border border-foreground bg-raised px-3 py-1.5 text-base text-foreground focus-visible:outline-none md:text-sm"
        />
      </li>
    );
  }

  if (mode === "confirm-delete") {
    return (
      <li className="flex items-center gap-1 rounded-md bg-raised px-3 py-1 text-sm">
        <span className="min-w-0 flex-1 truncate text-soft">
          Delete “{conversation.title}”?
        </span>
        <button
          type="button"
          onClick={() => onDelete(id)}
          className="min-h-8 rounded px-2 text-xs font-semibold text-danger-text hover:bg-danger-bg"
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
      className={`group flex items-center gap-1 rounded-md pr-1 ${active ? "bg-raised shadow-[inset_2px_0_0_var(--color-accent)]" : "hover:bg-raised"}`}
    >
      <button
        type="button"
        onClick={() => onSelect(id)}
        aria-current={active ? "page" : undefined}
        title={conversation.title}
        className={`min-h-9 min-w-0 flex-1 truncate px-3 text-left text-sm ${active ? "font-medium text-foreground" : "text-soft"}`}
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
