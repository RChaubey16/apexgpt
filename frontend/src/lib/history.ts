/**
 * Conversations kept in the browser (`localStorage`), with no login.
 *
 * - One key holds `{version: 1, conversations: [...]}`, newest first.
 * - Every write re-reads the key first and changes only the one conversation
 *   it is about, so two open tabs don't wipe out each other's chats.
 * - What is read back is validated: anything malformed is dropped (one bad
 *   conversation doesn't lose the rest), and a source link must be http(s).
 * - At most 50 conversations. If the browser's quota is full, the oldest
 *   others are dropped until the write fits; if it still doesn't, the write is
 *   reported as failed and the chat carries on unsaved.
 * - Storage may be missing or throw (private browsing, blocked cookies):
 *   every function takes the `Storage` to use, and `browserStorage()` returns
 *   null when there is none.
 */

import {
  isNumber,
  isObject,
  isString,
  type DoneInfo,
  type Source,
  type Table,
} from "./chat";
import type { AnswerStatus, AssistantMessage, Message } from "./conversation";

export const STORAGE_KEY = "apexgpt.conversations";
export const STORE_VERSION = 1;
export const MAX_CONVERSATIONS = 50;
export const MAX_TITLE_CHARS = 80;
const AUTO_TITLE_CHARS = 60;

export interface StoredConversation {
  id: string;
  title: string;
  /** Epoch milliseconds. */
  createdAt: number;
  updatedAt: number;
  messages: Message[];
}

export interface SaveResult {
  conversations: StoredConversation[];
  /** False when the browser wouldn't store it (quota or storage errors). */
  saved: boolean;
}

/** The browser's localStorage, or null when it is missing or blocked. */
export function browserStorage(): Storage | null {
  try {
    return typeof window === "undefined" ? null : window.localStorage;
  } catch {
    return null; // a SecurityError when site data is blocked
  }
}

// --- titles ---

const squash = (text: string) => text.replace(/\s+/g, " ").trim();

function clip(text: string, max: number): string {
  const chars = Array.from(text); // don't split a surrogate pair
  return chars.length <= max
    ? text
    : `${chars
        .slice(0, max - 1)
        .join("")
        .trimEnd()}…`;
}

/** A new conversation's title: its first question, on one line, shortened. */
export function titleFrom(messages: Message[]): string {
  const first = messages.find((m) => m.role === "user");
  return clip(squash(first?.content ?? ""), AUTO_TITLE_CHARS) || "New chat";
}

/** A title typed by the user, tidied; null if nothing is left. */
export function cleanTitle(input: string): string | null {
  const title = squash(input);
  return title ? clip(title, MAX_TITLE_CHARS) : null;
}

// --- validation ---

const STATUSES: readonly AnswerStatus[] = ["streaming", "done", "error", "stopped"];
const isOptionalString = (v: unknown) => v === undefined || isString(v);

function isSafeUrl(url: string): boolean {
  try {
    const { protocol } = new URL(url);
    return protocol === "https:" || protocol === "http:";
  } catch {
    return false;
  }
}

function toSource(v: unknown): Source | null {
  if (
    !isObject(v) ||
    !isString(v.id) ||
    !isString(v.title) ||
    !isString(v.url) ||
    !isSafeUrl(v.url) ||
    !(v.section === null || isString(v.section)) ||
    !(v.season === null || isNumber(v.season))
  ) {
    return null;
  }
  return { id: v.id, title: v.title, url: v.url, section: v.section, season: v.season };
}

function toTable(v: unknown): Table | null {
  if (
    !isObject(v) ||
    !Array.isArray(v.columns) ||
    !v.columns.every(isString) ||
    !Array.isArray(v.rows) ||
    !v.rows.every(Array.isArray) ||
    !isOptionalString(v.note)
  ) {
    return null;
  }
  const table: Table = { columns: v.columns, rows: v.rows as unknown[][] };
  if (isString(v.note)) table.note = v.note;
  return table;
}

function toDone(v: unknown): DoneInfo | undefined {
  if (
    isObject(v) &&
    isString(v.question) &&
    isString(v.provider) &&
    isString(v.model) &&
    Array.isArray(v.sources) &&
    v.sources.every(isString) &&
    Array.isArray(v.tools) &&
    v.tools.every((t) => isObject(t) && isString(t.name) && typeof t.ok === "boolean") &&
    isNumber(v.latencyMs) &&
    isNumber(v.promptTokens) &&
    isNumber(v.completionTokens) &&
    typeof v.cached === "boolean"
  ) {
    return v as unknown as DoneInfo;
  }
  return undefined; // only the answer's details are lost
}

function all<T>(items: unknown, parse: (v: unknown) => T | null): T[] | null {
  if (!Array.isArray(items)) return null;
  const parsed = items.map(parse);
  return parsed.every((p) => p !== null) ? (parsed as T[]) : null;
}

function toMessage(v: unknown): Message | null {
  if (!isObject(v) || !isString(v.id) || !isString(v.content)) return null;
  if (v.role === "user") return { id: v.id, role: "user", content: v.content };
  if (v.role !== "assistant" || !STATUSES.includes(v.status as AnswerStatus)) return null;
  if (!isOptionalString(v.standaloneQuestion) || !isOptionalString(v.error)) return null;
  const tables = all(v.tables, toTable);
  const citations = all(v.citations, toSource);
  if (!tables || !citations) return null;
  return sanitise({
    id: v.id,
    role: "assistant",
    status: v.status as AnswerStatus,
    content: v.content,
    standaloneQuestion: v.standaloneQuestion as string | undefined,
    tables,
    citations,
    done: toDone(v.done),
    error: v.error as string | undefined,
  });
}

function toConversation(v: unknown): StoredConversation | null {
  if (
    !isObject(v) ||
    !isString(v.id) ||
    !v.id ||
    !isString(v.title) ||
    !isNumber(v.createdAt) ||
    !isNumber(v.updatedAt)
  ) {
    return null;
  }
  const messages = all(v.messages, toMessage);
  if (!messages || messages.length === 0) return null;
  return {
    id: v.id,
    title: cleanTitle(v.title) ?? titleFrom(messages),
    createdAt: v.createdAt,
    updatedAt: v.updatedAt,
    messages,
  };
}

/** The stored conversations, newest first; [] for missing or unreadable data. */
export function parseStore(raw: string | null): StoredConversation[] {
  if (!raw) return [];
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return [];
  }
  if (
    !isObject(data) ||
    data.version !== STORE_VERSION ||
    !Array.isArray(data.conversations)
  ) {
    return [];
  }
  const seen = new Set<string>();
  const conversations: StoredConversation[] = [];
  for (const item of data.conversations) {
    const c = toConversation(item);
    if (c && !seen.has(c.id)) {
      seen.add(c.id);
      conversations.push(c);
    }
  }
  return sortNewest(conversations).slice(0, MAX_CONVERSATIONS);
}

// --- what is stored ---

/**
 * A message as it is stored: no live tool status or retry delay, and an
 * answer that was still streaming (the page closed, or the chat was left)
 * is kept as stopped, with whatever text had arrived.
 */
function sanitise(m: AssistantMessage): AssistantMessage {
  const stored: AssistantMessage = {
    id: m.id,
    role: "assistant",
    status: m.status === "streaming" ? "stopped" : m.status,
    content: m.content,
    tables: m.tables,
    citations: m.citations,
  };
  if (m.standaloneQuestion !== undefined)
    stored.standaloneQuestion = m.standaloneQuestion;
  if (m.done !== undefined) stored.done = m.done;
  if (m.error !== undefined) stored.error = m.error;
  return stored;
}

export function storedMessages(messages: Message[]): Message[] {
  return messages.map((m) => (m.role === "user" ? { ...m } : sanitise(m)));
}

const sortNewest = (list: StoredConversation[]) =>
  [...list].sort((a, b) => b.updatedAt - a.updatedAt);

export function loadConversations(storage: Storage): StoredConversation[] {
  try {
    return parseStore(storage.getItem(STORAGE_KEY));
  } catch {
    return [];
  }
}

function write(storage: Storage, conversations: StoredConversation[]): boolean {
  try {
    storage.setItem(
      STORAGE_KEY,
      JSON.stringify({ version: STORE_VERSION, conversations }),
    );
    return true;
  } catch {
    return false; // QuotaExceededError, or storage disabled
  }
}

/**
 * Write `conversations` (newest first, `keep` among the first 50), dropping
 * the oldest ones other than `keep` until it fits.
 */
function writeFitting(
  storage: Storage,
  conversations: StoredConversation[],
  keep: string,
): SaveResult {
  let list = conversations.slice(0, MAX_CONVERSATIONS);
  while (!write(storage, list)) {
    const oldest = list.findLastIndex((c) => c.id !== keep);
    if (oldest === -1) return { conversations: list, saved: false };
    list = list.filter((_, i) => i !== oldest);
  }
  return { conversations: list, saved: true };
}

/** Add or replace one conversation, moving it to the top (give it `updatedAt: now`). */
export function saveConversation(
  storage: Storage,
  conversation: StoredConversation,
): SaveResult {
  const stored = { ...conversation, messages: storedMessages(conversation.messages) };
  const others = loadConversations(storage).filter((c) => c.id !== conversation.id);
  return writeFitting(storage, [stored, ...others], conversation.id);
}

/** Rename one conversation; its place in the list doesn't change. */
export function renameConversation(
  storage: Storage,
  id: string,
  title: string,
): SaveResult {
  const clean = cleanTitle(title);
  const current = loadConversations(storage);
  if (!clean || !current.some((c) => c.id === id)) {
    return { conversations: current, saved: false };
  }
  const renamed = current.map((c) => (c.id === id ? { ...c, title: clean } : c));
  return writeFitting(storage, renamed, id);
}

export function deleteConversation(storage: Storage, id: string): SaveResult {
  const remaining = loadConversations(storage).filter((c) => c.id !== id);
  return { conversations: remaining, saved: write(storage, remaining) };
}
