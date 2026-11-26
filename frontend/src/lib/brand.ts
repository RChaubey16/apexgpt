import type { MetadataRoute } from "next";

// Brand constants shared by the manifest and its tests (F8.1).

// Matches --color-background in globals.css (and the viewport's themeColor).
export const BACKGROUND = "#0b0b0f";

export const APP_NAME = "ApexGPT";

export const APP_DESCRIPTION =
  "Formula 1 chat assistant: drivers, constructors, circuits, seasons and rivalries from 1950 to 2025.";

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
