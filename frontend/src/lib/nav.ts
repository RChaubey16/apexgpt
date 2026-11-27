/**
 * The site's pages, for the header navigation (F8.4a).
 *
 * A page is listed only once it exists (`live`): the current season page
 * arrives in F8.5, which turns its entry on. With a single live page there is
 * nothing to navigate between, so the header shows no navigation at all.
 */

export type PageId = "chat" | "season";

export interface NavItem {
  id: PageId;
  href: string;
  label: string;
  live: boolean;
}

export const NAV_ITEMS: readonly NavItem[] = [
  { id: "chat", href: "/", label: "Chat", live: true },
  { id: "season", href: "/season", label: "Current season", live: false },
];

/** The entries the header shows: the live ones, or none if only one is. */
export function navigation(items: readonly NavItem[] = NAV_ITEMS): NavItem[] {
  const live = items.filter((item) => item.live);
  return live.length > 1 ? live : [];
}
