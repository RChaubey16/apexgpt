import type { MetadataRoute } from "next";

// Brand constants shared by the manifest, the page metadata and their tests
// (F8.1, F8.2).

// Matches --color-background in globals.css (and the viewport's themeColor).
export const BACKGROUND = "#0b0b0f";

export const APP_NAME = "ApexGPT";

/** The site's title: browser tab, search results and share cards (F8.2). */
export const APP_TITLE = "ApexGPT: Formula 1 chat assistant";

export const APP_DESCRIPTION =
  "Ask anything about Formula 1 from 1950 to 2025: drivers, teams, seasons, races and rivalries. Answers come from real race data and cited sources.";

// Generated from brand/*.svg by `npm run icons`, served from public/icons.
export const MANIFEST_ICONS: NonNullable<MetadataRoute.Manifest["icons"]> = [
  { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
  { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
  {
    src: "/icons/icon-maskable-512.png",
    sizes: "512x512",
    type: "image/png",
    purpose: "maskable",
  },
];
