import type { MetadataRoute } from "next";

import { APP_DESCRIPTION, APP_NAME, BACKGROUND, MANIFEST_ICONS } from "@/lib/brand";

// The web app manifest (F8.1), served at /manifest.webmanifest: the name and
// icons used when ApexGPT is installed or added to a home screen.
export default function manifest(): MetadataRoute.Manifest {
  return {
    name: APP_NAME,
    short_name: APP_NAME,
    description: APP_DESCRIPTION,
    start_url: "/",
    scope: "/",
    display: "standalone",
    background_color: BACKGROUND,
    theme_color: BACKGROUND,
    icons: MANIFEST_ICONS,
  };
}
