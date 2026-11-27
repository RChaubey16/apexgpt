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

  it("keeps the season page off until F8.5 builds it", () => {
    expect(NAV_ITEMS.find((p) => p.id === "season")).toMatchObject({
      href: "/season",
      live: false,
    });
    expect(navigation()).toEqual([]);
  });
});
