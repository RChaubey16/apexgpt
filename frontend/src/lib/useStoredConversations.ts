"use client";

/**
 * The saved conversations as React state, read with useSyncExternalStore:
 * - on the server (and during hydration) the list is empty, so the HTML
 *   matches and saved chats appear once the page is running;
 * - it re-reads after this tab writes (`notifyStored`) and when another tab
 *   changes the key (the `storage` event).
 */

import { useMemo, useSyncExternalStore } from "react";

import { STORAGE_KEY, parseStore, type StoredConversation } from "./history";

const listeners = new Set<() => void>();

/** Tell every reader that this tab changed the stored conversations. */
export function notifyStored(): void {
  for (const listener of listeners) listener();
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  const onStorage = (event: StorageEvent) => {
    if (event.key === STORAGE_KEY || event.key === null) listener();
  };
  window.addEventListener("storage", onStorage);
  return () => {
    listeners.delete(listener);
    window.removeEventListener("storage", onStorage);
  };
}

export function useStoredConversations(storage: Storage | null): StoredConversation[] {
  const raw = useSyncExternalStore(
    subscribe,
    () => {
      try {
        return storage?.getItem(STORAGE_KEY) ?? null;
      } catch {
        return null;
      }
    },
    () => null,
  );
  return useMemo(() => parseStore(raw), [raw]);
}

const noSubscription = () => () => {};

/** False on the server and during hydration, true once running in the browser. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noSubscription,
    () => true,
    () => false,
  );
}
