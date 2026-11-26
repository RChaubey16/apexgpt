import type { MetadataRoute } from "next";

import { getSiteUrl } from "@/lib/config";

// /robots.txt (F8.2): everything may be indexed; points to the sitemap.
export default function robots(): MetadataRoute.Robots {
  const site = getSiteUrl();
  return {
    rules: { userAgent: "*", allow: "/" },
    sitemap: `${site}/sitemap.xml`,
    host: site,
  };
}
