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
| F8.4 | `feature/frontend-revamp` | The complete redesign, using Claude's **frontend-design** skill (install it before starting). The exact scope is settled when it starts, and it may split into smaller features once designed | `feat: revamp the frontend design` |
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

### Open questions (settled when the feature starts)

- **F8.5: the page.** How the standings, the next race and the countdown are laid out, in the new design.

### Facts checked while planning (2026-11-26)

- **The season in progress is 2026.** ApexGPT's data ends with 2025, the last finished season.
- **The Jolpica API (`api.jolpi.ca/ergast/f1/current/…`) has everything needed:**
  - standings after round 21;
  - the next race: round 22, the Qatar GP on 29 Nov, 16:00 UTC;
  - the 23-race calendar.
- **The frontend serves a generic placeholder `favicon.ico`,** with no `apple-touch-icon` and no web manifest. The API domain has no favicon (404).
- **The page has a title and a one-line description,** but no Open Graph or Twitter tags.
