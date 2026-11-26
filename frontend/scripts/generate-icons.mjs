// Generate every icon file (F8.1) and the social preview image (F8.2) from
// the brand SVGs. Run from frontend/:
//
//   npm run icons
//
// Sources: brand/icon.svg (the master), brand/icon-small.svg (the 16 px
// favicon frame), brand/icon-square.svg (full-bleed, for platforms that
// mask icons themselves) and brand/og.svg (the 1200x630 share-card image; its
// text uses the machine's fonts). See brand/README.md.
//
// Next.js picks up the files in src/app by name (icon.svg, favicon.ico,
// apple-icon.png, opengraph-image.png, twitter-image.png) and writes the
// <link> and <meta> tags itself; src/app/manifest.ts
// lists the ones in public/icons. The backend gets the same favicon.ico, so
// the API domain has one too.

import { copyFile, mkdir, readFile, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import sharp from "sharp";

const FRONTEND = join(dirname(fileURLToPath(import.meta.url)), "..");
const BRAND = join(FRONTEND, "brand");
const APP = join(FRONTEND, "src", "app");
const PUBLIC_ICONS = join(FRONTEND, "public", "icons");
const BACKEND_STATIC = join(FRONTEND, "..", "backend", "app", "static");

// Matches --color-background in globals.css.
const BACKGROUND = "#0b0b0f";
// The maskable icon's mark fills this share of the canvas, inside the 80 %
// safe zone that platforms keep when they crop to a circle or squircle.
const MASKABLE_SCALE = 0.7;

async function png(svgFile, size) {
  const svg = await readFile(join(BRAND, svgFile));
  // A high density renders the vector sharply before downscaling.
  return sharp(svg, { density: 1200 })
    .resize(size, size)
    .png({ compressionLevel: 9 })
    .toBuffer();
}

async function maskable(size) {
  const inner = Math.round(size * MASKABLE_SCALE);
  const mark = await png("icon-square.svg", inner);
  const offset = Math.round((size - inner) / 2);
  return sharp({
    create: { width: size, height: size, channels: 4, background: BACKGROUND },
  })
    .composite([{ input: mark, left: offset, top: offset }])
    .png({ compressionLevel: 9 })
    .toBuffer();
}

// An .ico holding PNG-encoded frames (supported by every current browser).
function ico(frames) {
  const header = Buffer.alloc(6);
  header.writeUInt16LE(0, 0); // reserved
  header.writeUInt16LE(1, 2); // type: icon
  header.writeUInt16LE(frames.length, 4);
  const entries = [];
  let offset = 6 + 16 * frames.length;
  for (const { size, data } of frames) {
    const entry = Buffer.alloc(16);
    entry.writeUInt8(size >= 256 ? 0 : size, 0); // width (0 = 256)
    entry.writeUInt8(size >= 256 ? 0 : size, 1); // height
    entry.writeUInt8(0, 2); // palette size
    entry.writeUInt8(0, 3); // reserved
    entry.writeUInt16LE(1, 4); // colour planes
    entry.writeUInt16LE(32, 6); // bits per pixel
    entry.writeUInt32LE(data.length, 8);
    entry.writeUInt32LE(offset, 12);
    entries.push(entry);
    offset += data.length;
  }
  return Buffer.concat([header, ...entries, ...frames.map((f) => f.data)]);
}

async function main() {
  await mkdir(PUBLIC_ICONS, { recursive: true });
  await mkdir(BACKEND_STATIC, { recursive: true });

  const favicon = ico([
    { size: 16, data: await png("icon-small.svg", 16) },
    { size: 32, data: await png("icon.svg", 32) },
    { size: 48, data: await png("icon.svg", 48) },
  ]);
  const shareImage = await sharp(await readFile(join(BRAND, "og.svg")), {
    density: 144,
  })
    .resize(1200, 630)
    .png({ compressionLevel: 9 })
    .toBuffer();
  const outputs = [
    [join(APP, "favicon.ico"), favicon],
    [join(BACKEND_STATIC, "favicon.ico"), favicon],
    [join(APP, "apple-icon.png"), await png("icon-square.svg", 180)],
    [join(PUBLIC_ICONS, "icon-192.png"), await png("icon.svg", 192)],
    [join(PUBLIC_ICONS, "icon-512.png"), await png("icon.svg", 512)],
    [join(PUBLIC_ICONS, "icon-maskable-512.png"), await maskable(512)],
    [join(APP, "opengraph-image.png"), shareImage],
    [join(APP, "twitter-image.png"), shareImage],
  ];
  for (const [path, data] of outputs) {
    await writeFile(path, data);
    console.log(
      `${path.slice(FRONTEND.length - "frontend".length)} (${data.length} bytes)`,
    );
  }
  await copyFile(join(BRAND, "icon.svg"), join(APP, "icon.svg"));
  console.log("frontend/src/app/icon.svg (copied from brand/icon.svg)");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
