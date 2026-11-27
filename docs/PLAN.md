# ApexGPT: Plan

The features being built now, planned the same way as the MVP ([archived plan](./archive/v1.0.0-mvp/MVP-PLAN.md)). Each feature is one branch and one PR, built one at a time ([WORKFLOW.md](./WORKFLOW.md)). Progress is tracked in [PROGRESS.md](./PROGRESS.md#features).

---

## Phase 8: v1.1.0, polish and the current season

**Goal:**
- The site looks finished: its own icon everywhere, proper metadata and social previews, and a complete frontend redesign.
- It shows the **current Formula 1 season** on its own page: the drivers' and constructors' standings, and the next race.

**Out of scope:**
- The current season is **not added to the chat's data.** Answers still cover 1950–2025. The season page reads live data from the Jolpica API instead.

**Done when:**
- v1.1.0 is deployed;
- the production smoke test passes, extended to the season endpoint;
- the release is tagged.

| ID | Branch | Scope | Commit message |
|---|---|---|---|
| F8.1 | `feature/app-icons` | An ApexGPT logo (SVG, from the racing-stripe motif); favicons for both domains (frontend and API); an `apple-touch-icon`; a web manifest with 192/512 and maskable icons | `feat: add app icons and favicons` |
| F8.2 | `feature/page-metadata` | Title template, description, canonical URL, Open Graph and Twitter card tags, a social preview image (1200×630), `robots.txt` and a sitemap | `feat: add page metadata and social previews` |
| F8.3 | `feature/season-api` | `GET /api/season/current`: the drivers' and constructors' standings plus the next race, from the Jolpica API; a server-side cache; validated external data; the off-season handled; a rate limit | `feat: add current season endpoint` |
| F8.4a | `feature/revamp-shell` | The redesign's foundation, with Claude's **frontend-design** skill: the "pit wall" design tokens (colours, type), the Archivo font, the logo and share image recoloured, and a shared site header with navigation between pages (shown once there are two) | `feat: add the pit wall design system and site header` |
| F8.4b | `feature/revamp-chat` | Every chat screen in the new design: the chat list and drawer, the empty state and starter questions, answers (the timing-tower stripe, tables, citations, sources), the composer, errors and notices. Behaviour unchanged | `feat: restyle the chat in the pit wall design` |
| F8.5 | `feature/season-page` | The `/season` page in the new design: both standings tables, the next race in the visitor's local time, and navigation (Chat · Current season) | `feat: add current season page` |

**After F8.5:** deploy, run the smoke test, and tag `v1.1.0` with a GitHub Release.

### Decided

- **Order:** icons → metadata → the season endpoint → the revamp → the season page. The season page comes after the revamp, so it's designed once, in the new style.
- **The season view gets its own page (`/season`),** with a top navigation. It has a shareable URL and room to grow, and keeps the chat uncluttered.
- **The logo is designed in F8.1;** there isn't an existing one.
- **The revamp uses the frontend-design skill,** not mockups or outside references.
- **F8.3, settled when it started (2026-11-27):**
  - **Columns:** drivers' standings have position, driver (name, code, number, nationality), latest team, points and wins; constructors' standings have position, team, nationality, points and wins.
  - **The next race:** round, name, circuit and location, the race start, and every session of the weekend (practice, sprint qualifying, sprint, qualifying), all in UTC. The page shows them in the visitor's time zone and runs the countdown.
  - **The off-season:** the final standings with `complete: true`, plus the next season's first race once Jolpica publishes the calendar (`next_race: null` until then). If Jolpica's "current" moves to a season with no races yet, the previous season's final standings are shown.
  - **Freshness:** cached for 10 minutes (Jolpica's own cache time), so ~18 requests an hour at most. When Jolpica fails, the last data is served with `stale: true` for up to 24 hours, retried at most once a minute; with nothing cached, a 503.

- **F8.4, settled when it started (2026-11-27):**
  - **Direction: the pit wall.** The engineers' timing screens: deep slate (not black), dense and precise. Colour is used for meaning and taken from the tyre compounds: soft red for the logo and the one primary action, medium yellow for in progress, intermediate green for ready, wet blue for sources and links, and the hard compound's white for emphasis.
  - **Type:** Archivo, one family at two widths. The condensed width is for the wordmark, headings and figures, and the normal width for reading. Figures are tabular everywhere. Geist Mono is for code and SQL only.
  - **Dropped:** the checkered band, all-caps tracked labels, "A · B · C" meta lines and the red "GPT" in the wordmark (the generic defaults the skill steers away from).
  - **Scope:** a design system, the shared header and every chat screen. Behaviour and tests stay the same; no new chat features.
  - **Split into two PRs,** F8.4a (the foundation and header) and F8.4b (the chat screens), so the look can be reviewed before every screen changes.
  - **The logo keeps its shape** (the three stripes), recoloured to the new palette.
  - **F8.4b, the chat:** questions are condensed header lines in a left-aligned log, not bubbles. Each answer has a timing-tower stripe coloured by its state: yellow while streaming, quiet grey when done, red on an error, dashed when stopped. Starter questions are rows of a timing table, not cards. Citations and links are wet blue. Keyboard focus rings are hard white, so red is only the logo, Send and errors.

- **F8.5, settled when it started (2026-11-27):**
  - **Layout:** the next race first (name, circuit, a live countdown, and the weekend's sessions in the visitor's time zone, the next one marked), then the drivers' and constructors' standings as two timing towers, side by side on wide screens (3:2) and stacked on phones.
  - **Extras:** each row shows the gap to the leader, and a stripe in its team's colour (a small map in the frontend; a team not in it gets a neutral grey). "Title still open" markers were left out.
  - **Loaded in the browser** from `GET /api/season/current`, like the chat; the backend caches it.

### Facts checked while planning (2026-11-26)

- **The season in progress is 2026.** ApexGPT's data ends with 2025, the last finished season.
- **The Jolpica API (`api.jolpi.ca/ergast/f1/current/…`) has everything needed:**
  - standings after round 21;
  - the next race: round 22, the Qatar GP on 29 Nov, 16:00 UTC;
  - the 23-race calendar.
- **The frontend serves a generic placeholder `favicon.ico`,** with no `apple-touch-icon` and no web manifest. The API domain has no favicon (404).
- **The page has a title and a one-line description,** but no Open Graph or Twitter tags.
