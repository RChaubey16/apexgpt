import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SiteHeader } from "@/components/SiteHeader";
import type { NavItem } from "@/lib/nav";

const BOTH: NavItem[] = [
  { id: "chat", href: "/", label: "Chat", live: true },
  { id: "season", href: "/season", label: "Current season", live: true },
];

afterEach(() => vi.unstubAllGlobals());

describe("SiteHeader", () => {
  it("links the wordmark home, with the logo hidden from screen readers", () => {
    const { container } = render(<SiteHeader current="chat" apiBaseUrl={null} />);

    const home = screen.getByRole("link", { name: "ApexGPT, home" });
    expect(home).toHaveAttribute("href", "/");
    expect(container.querySelector(".speed-stripes")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
  });

  it("shows no navigation while the chat is the only page", () => {
    const chatOnly = BOTH.map((p) => ({ ...p, live: p.id === "chat" }));
    render(<SiteHeader current="chat" apiBaseUrl={null} items={chatOnly} />);

    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });

  it("marks the current page in the navigation", () => {
    render(<SiteHeader current="season" apiBaseUrl={null} items={BOTH} />);

    const nav = screen.getByRole("navigation", { name: "Pages" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Current season" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Chat" })).not.toHaveAttribute(
      "aria-current",
    );
  });

  it("links both pages by default, the chat current on the home page", () => {
    render(<SiteHeader current="chat" apiBaseUrl={null} />);

    expect(screen.getByRole("link", { name: "Chat" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(screen.getByRole("link", { name: "Current season" })).toHaveAttribute(
      "href",
      "/season",
    );
  });

  it("includes the backend status", () => {
    render(<SiteHeader current="chat" apiBaseUrl={null} />);

    expect(screen.getByTestId("backend-status")).toHaveAttribute(
      "data-state",
      "misconfigured",
    );
  });

  it("writes the tagline in sentence case, without caps or dot separators", () => {
    render(<SiteHeader current="chat" apiBaseUrl={null} />);

    const tagline = screen.getByText("Formula 1, 1950 to 2025");
    expect(tagline.className).not.toMatch(/uppercase/);
  });
});
