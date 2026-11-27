import type { Metadata } from "next";

import { APP_DESCRIPTION, APP_NAME, APP_TITLE } from "@/lib/brand";

/**
 * Site-wide metadata (F8.2), used by the root layout. Pages add their own
 * title (filled into the template) and canonical URL; setting the canonical
 * here would make every page claim the home page's address.
 *
 * Share-card images come from the opengraph-image.png and twitter-image.png
 * files in src/app; Next.js makes their URLs absolute with `metadataBase`.
 */
const OPEN_GRAPH = {
  type: "website",
  siteName: APP_NAME,
  title: APP_TITLE,
  description: APP_DESCRIPTION,
  locale: "en_GB",
} as const satisfies NonNullable<Metadata["openGraph"]>;

export function siteMetadata(siteUrl: string): Metadata {
  return {
    metadataBase: new URL(siteUrl),
    title: { default: APP_TITLE, template: `%s · ${APP_NAME}` },
    description: APP_DESCRIPTION,
    applicationName: APP_NAME,
    openGraph: OPEN_GRAPH,
    twitter: {
      card: "summary_large_image",
      title: APP_TITLE,
      description: APP_DESCRIPTION,
    },
    robots: { index: true, follow: true },
  };
}

/**
 * A page's own metadata: its canonical address. Next.js merges metadata
 * shallowly, so a page's `openGraph` replaces the layout's whole object; the
 * site's Open Graph fields are repeated here, or the page would lose og:type,
 * og:site_name and og:locale.
 */
export function pageMetadata(path: string): Metadata {
  return {
    alternates: { canonical: path },
    openGraph: { ...OPEN_GRAPH, url: path },
  };
}

export const homeMetadata: Metadata = pageMetadata("/");

/** The current season page (F8.5): "Current season · ApexGPT". */
export const seasonMetadata: Metadata = {
  ...pageMetadata("/season"),
  title: "Current season",
  description:
    "The current Formula 1 season: the drivers' and constructors' standings, and the next race with a countdown and its sessions in your time zone.",
};

/** The pages listed in /sitemap.xml. Add new pages here. */
export const SITEMAP_PAGES: readonly string[] = ["/", "/season"];
