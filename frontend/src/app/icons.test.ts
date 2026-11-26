/**
 * App icons and the web manifest (F8.1): every generated file exists at the
 * size it claims, the favicon has its three frames, the backend serves the
 * same favicon, the manifest's colours match the theme, and the share-card
 * images are the right size. All are generated from brand/*.svg by
 * `npm run icons`.
 */

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { APP_NAME, BACKGROUND, MANIFEST_ICONS } from "@/lib/brand";

import manifest from "./manifest";

const FRONTEND = join(__dirname, "..", "..");
const APP = __dirname;
const PUBLIC = join(FRONTEND, "public");
const BACKEND_FAVICON = join(FRONTEND, "..", "backend", "app", "static", "favicon.ico");

const PNG_SIGNATURE = Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]);

/** Width and height from a PNG's IHDR chunk. */
function pngSize(data: Buffer): { width: number; height: number } {
  expect(data.subarray(0, 8).equals(PNG_SIGNATURE)).toBe(true);
  expect(data.subarray(12, 16).toString("ascii")).toBe("IHDR");
  return { width: data.readUInt32BE(16), height: data.readUInt32BE(20) };
}

/** The frames of an .ico: the size its directory claims, and the image bytes. */
function icoFrames(data: Buffer): { size: number; image: Buffer }[] {
  expect(data.readUInt16LE(0)).toBe(0); // reserved
  expect(data.readUInt16LE(2)).toBe(1); // type: icon
  const count = data.readUInt16LE(4);
  return Array.from({ length: count }, (_, i) => {
    const entry = 6 + 16 * i;
    const length = data.readUInt32LE(entry + 8);
    const offset = data.readUInt32LE(entry + 12);
    return {
      size: data.readUInt8(entry) || 256,
      image: data.subarray(offset, offset + length),
    };
  });
}

describe("favicon.ico", () => {
  const favicon = readFileSync(join(APP, "favicon.ico"));

  it("has 16, 32 and 48 px frames, each a PNG of the size it claims", () => {
    const frames = icoFrames(favicon);
    expect(frames.map((f) => f.size)).toEqual([16, 32, 48]);
    for (const { size, image } of frames) {
      expect(pngSize(image)).toEqual({ width: size, height: size });
    }
  });

  it("is the same file the backend serves on the API domain", () => {
    expect(existsSync(BACKEND_FAVICON)).toBe(true);
    expect(readFileSync(BACKEND_FAVICON).equals(favicon)).toBe(true);
  });
});

describe("other icons", () => {
  it("serves the brand SVG unchanged as icon.svg", () => {
    const served = readFileSync(join(APP, "icon.svg"), "utf8");
    expect(served).toBe(readFileSync(join(FRONTEND, "brand", "icon.svg"), "utf8"));
  });

  it("has a 180 px Apple touch icon", () => {
    expect(pngSize(readFileSync(join(APP, "apple-icon.png")))).toEqual({
      width: 180,
      height: 180,
    });
  });

  it.each(["icon.svg", "icon-small.svg", "icon-square.svg"])(
    "brand/%s is a self-contained 64×64 SVG",
    (name) => {
      const svg = readFileSync(join(FRONTEND, "brand", name), "utf8");
      expect(svg).toContain('viewBox="0 0 64 64"');
      expect(svg).toContain(BACKGROUND);
      // No scripts, external images or fonts: it is served as-is.
      expect(svg).not.toMatch(/<script|href=|@import|<image/i);
    },
  );
});

describe("share-card images (F8.2)", () => {
  const og = readFileSync(join(APP, "opengraph-image.png"));

  it("is 1200x630, the size Open Graph and X expect", () => {
    expect(pngSize(og)).toEqual({ width: 1200, height: 630 });
  });

  it("is the same image for X, with the same alt text", () => {
    expect(readFileSync(join(APP, "twitter-image.png")).equals(og)).toBe(true);
    const alt = readFileSync(join(APP, "opengraph-image.alt.txt"), "utf8");
    expect(alt).toMatch(/^ApexGPT: Formula 1 chat assistant\./);
    expect(readFileSync(join(APP, "twitter-image.alt.txt"), "utf8")).toBe(alt);
    // Next.js emits the file verbatim: a trailing newline would end up in
    // og:image:alt (pre-commit's end-of-file-fixer skips these files).
    expect(alt).toBe(alt.trim());
  });

  it("comes from a self-contained 1200x630 SVG", () => {
    const svg = readFileSync(join(FRONTEND, "brand", "og.svg"), "utf8");
    expect(svg).toContain('viewBox="0 0 1200 630"');
    expect(svg).not.toMatch(/<script|href=|@import|<image/i);
  });
});

describe("manifest", () => {
  const m = manifest();

  it("names the app and uses the theme's background", () => {
    expect(m.name).toBe(APP_NAME);
    expect(m.short_name).toBe(APP_NAME);
    expect(m.start_url).toBe("/");
    expect(m.display).toBe("standalone");
    expect(m.background_color).toBe(BACKGROUND);
    expect(m.theme_color).toBe(BACKGROUND);

    const css = readFileSync(join(APP, "globals.css"), "utf8");
    expect(css).toMatch(new RegExp(`--color-background:\\s*${BACKGROUND};`, "i"));
  });

  it("has 192 and 512 px icons and a maskable one", () => {
    const icons = m.icons ?? [];
    expect(icons).toEqual(MANIFEST_ICONS);
    expect(icons.map((i) => `${i.sizes} ${i.purpose}`)).toEqual([
      "192x192 any",
      "512x512 any",
      "512x512 maskable",
    ]);
  });

  it.each(MANIFEST_ICONS)("$src exists at $sizes", ({ src, sizes }) => {
    const [width, height] = (sizes ?? "").split("x").map(Number);
    expect(pngSize(readFileSync(join(PUBLIC, src)))).toEqual({ width, height });
  });
});
