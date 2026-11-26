import type { MetadataRoute } from "next";

import { getSiteUrl } from "@/lib/config";
import { SITEMAP_PAGES } from "@/lib/metadata";

// /sitemap.xml (F8.2): the site's pages, with absolute URLs.
export default function sitemap(): MetadataRoute.Sitemap {
  const site = getSiteUrl();
  return SITEMAP_PAGES.map((path) => ({
    url: `${site}${path}`,
    changeFrequency: "monthly",
    priority: path === "/" ? 1 : 0.8,
  }));
}
