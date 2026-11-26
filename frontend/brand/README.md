# ApexGPT brand assets

The logo is the header's speed-stripe mark: three slanted F1-red stripes (`#e10600`) on the site's background (`#0b0b0f`).

| File              | Use                                                                                                                                                        |
| ----------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `icon.svg`        | The master: a rounded tile. Served as the SVG favicon, and the source of the 32/48 px favicon frames and the manifest's 192/512 icons                      |
| `icon-small.svg`  | Two bolder stripes for the 16×16 favicon frame, where three thin stripes blur together                                                                     |
| `icon-square.svg` | Full-bleed (no rounded corners) for platforms that mask icons themselves: the Apple touch icon, and the maskable manifest icon (scaled into the safe zone) |

After changing any of them, regenerate every icon file (frontend and backend) from `frontend/`:

```bash
npm run icons
```

Never edit the generated PNG or ICO files by hand. The tests check they match these sources.
