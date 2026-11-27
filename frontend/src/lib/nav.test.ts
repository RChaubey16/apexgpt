import { describe, expect, it } from "vitest";

import { NAV_ITEMS, navigation, type NavItem } from "@/lib/nav";

const page = (id: NavItem["id"], live: boolean): NavItem => ({
  id,
  href: id === "chat" ? "/" : `/${id}`,
  label: id,
  live,
});

describe("navigation", () => {
  it("lists only live pages", () => {
    expect(
      navigation([page("chat", true), page("season", true)]).map((p) => p.id),
    ).toEqual(["chat", "season"]);
  });

  it("is empty with a single live page: nothing to navigate between", () => {
    expect(navigation([page("chat", true), page("season", false)])).toEqual([]);
  });

  it("lists the chat and the current season page (live since F8.5)", () => {
    expect(navigation().map((p) => [p.label, p.href])).toEqual([
      ["Chat", "/"],
      ["Current season", "/season"],
    ]);
    expect(NAV_ITEMS.every((p) => p.live)).toBe(true);
  });
});
