/**
 * The theme's promises (see globals.css): readable colours, and components
 * that use the theme's tokens rather than Tailwind's default palette.
 */

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");
const css = readFileSync(join(__dirname, "globals.css"), "utf8");

/** `--color-name: #rrggbb;` from the @theme block. */
const tokens = new Map(
  [...css.matchAll(/--color-([a-z-]+):\s*(#[0-9a-f]{6});/gi)].map((m) => [m[1], m[2]]),
);

function color(name: string): string {
  const value = tokens.get(name);
  if (!value) throw new Error(`no --color-${name} in globals.css`);
  return value;
}

/** WCAG 2 relative luminance of "#rrggbb". */
function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

const SURFACES = ["background", "surface", "raised", "hover"];

describe("contrast", () => {
  it("is computed as WCAG defines it", () => {
    expect(contrast("#000000", "#ffffff")).toBeCloseTo(21);
    expect(contrast("#777777", "#ffffff")).toBeCloseTo(4.48, 2);
  });
});

describe("theme colours", () => {
  it.each(
    [
      "foreground",
      "soft",
      "muted",
      "accent-text",
      "danger-text",
      "warning-text",
      "success-text",
      "info-text",
    ].flatMap((text) => SURFACES.map((surface) => [text, surface])),
  )("%s text on %s meets WCAG AA (4.5:1)", (text, surface) => {
    expect(contrast(color(text), color(surface))).toBeGreaterThanOrEqual(4.5);
  });

  it.each([
    ["danger-text", "danger-bg"],
    ["warning-text", "warning-bg"],
    ["on-accent", "accent"],
    ["on-accent", "accent-strong"],
  ])("%s on %s meets WCAG AA (4.5:1)", (text, background) => {
    expect(contrast(color(text), color(background))).toBeGreaterThanOrEqual(4.5);
  });

  it.each([
    ["accent", "background"],
    ["accent", "surface"],
    ["control", "background"],
    ["control", "surface"],
    ["control", "raised"],
    // Status colours (tyre compounds) used as dots, rings and bars.
    ["success", "surface"],
    ["warning", "surface"],
    ["info", "surface"],
  ])("%s is visible on %s (3:1, for focus rings and control borders)", (ui, surface) => {
    expect(contrast(color(ui), color(surface))).toBeGreaterThanOrEqual(3);
  });

  it("gives the browser bar the page's background", () => {
    const layout = readFileSync(join(__dirname, "layout.tsx"), "utf8");

    expect(layout).toContain(`themeColor: "${color("background")}"`);
  });
});

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(path);
    return /\.tsx$/.test(entry.name) && !/\.test\./.test(entry.name) ? [path] : [];
  });
}

describe("components", () => {
  // Tailwind's default palettes; `black`/`white` scrims are fine.
  const DEFAULT_PALETTE =
    /\b[a-z-]+-(?:slate|gray|zinc|neutral|stone|red|orange|amber|yellow|lime|green|emerald|teal|cyan|sky|blue|indigo|violet|purple|fuchsia|pink|rose)-\d{2,3}\b/g;

  it("use the theme's colours, not Tailwind's default palette", () => {
    const files = sourceFiles(SRC);
    expect(files.length).toBeGreaterThan(5);

    const offenders = files.flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(DEFAULT_PALETTE)].map(
        (m) => `${file.slice(SRC.length + 1)}: ${m[0]}`,
      ),
    );
    expect(offenders).toEqual([]);
  });
});

describe("type (F8.6)", () => {
  // Compact F1-app style: caps are fine for small labels and surnames, but
  // no italic display type or skewed buttons (dropped in F8.4).
  it("sets no text in italics or skew", () => {
    const offenders = sourceFiles(SRC).flatMap((file) =>
      [...readFileSync(file, "utf8").matchAll(/\b(italic|skew-x-6)\b/g)].map(
        (m) => `${file.slice(SRC.length + 1)}: ${m[0]}`,
      ),
    );
    expect(offenders).toEqual([]);
  });

  it("uses a compact 14px base size", () => {
    expect(css).toMatch(/html\s*{[^}]*font-size:\s*87\.5%/);
  });
});
