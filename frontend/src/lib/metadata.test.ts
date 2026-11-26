/**
 * Page metadata (F8.2): the site-wide defaults, each page's canonical
 * address, robots.txt and the sitemap.
 */

import { afterEach, describe, expect, it, vi } from "vitest";

import robots from "@/app/robots";
import sitemap from "@/app/sitemap";
import { APP_DESCRIPTION, APP_TITLE } from "@/lib/brand";

import { SITEMAP_PAGES, homeMetadata, pageMetadata, siteMetadata } from "./metadata";

const SITE = "https://apexgpt.example.com";

afterEach(() => {
  vi.unstubAllEnvs();
});

describe("siteMetadata", () => {
  const m = siteMetadata(SITE);

  it("makes relative URLs absolute against the site URL", () => {
    expect(m.metadataBase?.toString()).toBe(`${SITE}/`);
  });

  it("uses the agreed title and description", () => {
    expect(m.title).toEqual({ default: APP_TITLE, template: "%s · ApexGPT" });
    expect(m.description).toBe(APP_DESCRIPTION);
    expect(APP_TITLE).toBe("ApexGPT: Formula 1 chat assistant");
  });

  it("describes the site for share cards", () => {
    expect(m.openGraph).toMatchObject({
      type: "website",
      siteName: "ApexGPT",
      title: APP_TITLE,
      description: APP_DESCRIPTION,
      locale: "en_GB",
    });
    expect(m.twitter).toMatchObject({ card: "summary_large_image", title: APP_TITLE });
  });

  it("allows indexing", () => {
    expect(m.robots).toEqual({ index: true, follow: true });
  });

  it("leaves the canonical address to each page", () => {
    // In the layout it would make every page claim the home page's address.
    expect(m.alternates).toBeUndefined();
  });
});

describe("pageMetadata", () => {
  it("gives a page its canonical address", () => {
    expect(pageMetadata("/season").alternates).toEqual({ canonical: "/season" });
    expect(homeMetadata.alternates).toEqual({ canonical: "/" });
  });

  it("keeps the site's Open Graph fields, which Next.js would otherwise drop", () => {
    // Next.js merges metadata shallowly: a page's openGraph replaces the
    // layout's. Without the site fields here, og:type, og:site_name and
    // og:locale disappear from the page.
    const site = siteMetadata(SITE).openGraph;
    expect(pageMetadata("/season").openGraph).toEqual({ ...site, url: "/season" });
    expect(homeMetadata.openGraph).toMatchObject({ type: "website", url: "/" });
  });
});

describe("robots.txt and sitemap.xml", () => {
  it("point to the sitemap at the site's address", () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", SITE);
    expect(robots()).toEqual({
      rules: { userAgent: "*", allow: "/" },
      sitemap: `${SITE}/sitemap.xml`,
      host: SITE,
    });
  });

  it("list every page with an absolute URL", () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", `${SITE}/`);
    const entries = sitemap();
    expect(entries.map((e) => e.url)).toEqual(SITEMAP_PAGES.map((p) => `${SITE}${p}`));
    expect(entries[0]).toMatchObject({ url: `${SITE}/`, priority: 1 });
  });

  it("fall back to local development without the setting", () => {
    vi.stubEnv("NEXT_PUBLIC_SITE_URL", "");
    expect(robots().sitemap).toBe("http://localhost:3000/sitemap.xml");
  });
});
