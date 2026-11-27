# ApexGPT: Features

What ApexGPT does today, and what's planned next. The original feature plan, written before the MVP was built, is in the [v1.0.0 MVP archive](./archive/v1.0.0-mvp/FEATURES.md).

Related: [PROGRESS.md](./PROGRESS.md) (status and open issues)

---

## Shipped in v1.0.0

The MVP ([release notes](https://github.com/RChaubey16/apexgpt/releases/tag/v1.0.0)) covers every World Championship season from 1950 to 2025.

**Asking**
- Questions in plain English about drivers, constructors, circuits, seasons, races, crashes, rivalries and title battles.
- **Statistics come from real queries.** Counts, rankings, records, per-season results and team-mate comparisons are computed by validated SQL over the stats views, not taken from text. Shared records are named in full.
- **History comes from cited sources.** What happened, why and how is answered from curated Wikipedia articles (hybrid search plus a reranker), and every fact is cited.
- **Follow-ups:** "Who was his team-mate that year?" is understood from the conversation.
- **Honest limits:**
  - it says when the data doesn't cover something;
  - it corrects false premises ("Senna never drove for Ferrari");
  - it declines questions outside F1 or 1950–2025;
  - it doesn't reveal its instructions.
- Results shown as tables where that's clearer, with the exact rows one click away.

**Using the app**
- Streaming answers, with tool status ("Checking the stats…") and how a follow-up was understood.
- Citation chips linking to the sources, and a sources list with the CC BY-SA attribution.
- Starter question cards.
- Chats saved in the browser, with no login (new, open, rename, delete).
- Copy an answer with its sources; 👍/👎 feedback.
- A responsive dark theme, meeting WCAG AA contrast.

**Running it**
- Free-tier LLMs with automatic fallback: Groq, then Gemini, then OpenRouter.
- Per-IP rate limits, an answer cache, and structured logs.
- A golden-set evaluation runner, load and cold-start tests, and a production smoke test.
- Weekly encrypted backups, each one verified by a test restore. Feedback is deleted after 90 days.

---

## Shipped in v1.1.0

Phase 8 ([release notes](https://github.com/RChaubey16/apexgpt/releases/tag/v1.1.0), [plan](./archive/v1.1.0/PLAN.md)):
- **A current season page** (`/season`): the drivers' and constructors' standings with team colours and the gap to the leader; the next race with a live countdown and its sessions in your time zone; the champions once a title is mathematically decided. Live data from Jolpica, kept out of the chat's data.
- **A dark, compact design** in the spirit of the F1 app (F1 red, Titillium Web), with navigation between Chat and Current season.
- **App icons and favicons** for both domains, and a web manifest.
- **Link previews:** titles, descriptions, a share image, a sitemap and robots.txt.

---

## Planned

### Not scheduled yet

When one of these is picked up, it's planned in [PLAN.md](./PLAN.md) and tracked in [PROGRESS.md](./PROGRESS.md#features) ([WORKFLOW.md](./WORKFLOW.md)).

### Left over from the MVP
- **Share an answer:** a link to a single answer. The MVP has copy only.
- **Feedback analytics:** the 👍/👎 ratings are stored but not analysed yet. Use them to find weak answers and grow the golden set.
- **Re-run ingestion from an admin endpoint.** Today the pipeline is re-run from the CLI, and data reaches production with `scripts/neon_setup.sh` (`REPLACE=1`).

### Tier 2: a richer experience

**Entity pages**, generated from the data:
- Driver profile: career stats, teams, titles, team-mates, best seasons, notable moments.
- Constructor profile: history, lineage, championships, legendary cars.
- Circuit profile: layout history, most successful drivers, famous races there.
- Season page: calendar, final standings, the title battle, key storylines.
- Entities named in answers become links to these pages.

**Comparisons:**
- Driver vs driver: overall, or as team-mates in equal machinery.
- Eras (e.g. Schumacher's Ferrari years vs Hamilton's Mercedes years), and constructors across eras.

**Visual answers:**
- Championship points progression charts (e.g. the 2010 four-way title fight).
- Win and podium charts, and season-by-season career timelines.
- The LLM decides when a chart helps and returns its data alongside the text.

**Curated story collections:**
- **Rivalries:** Senna–Prost, Hunt–Lauda, Hamilton–Rosberg, Hamilton–Verstappen, and more.
- **Title deciders:** 1976, 1986, 2007, 2008, 2010, 2012, 2021.
- **Safety and crashes:** major incidents and the safety changes that followed, handled respectfully.
- **Iconic races:** Canada 2011, Brazil 2008, Donington 1993, and more.

### Tier 3: engagement and power features
- **Trivia and quiz mode:** quizzes generated from the structured data, with difficulty levels and era filters.
- **"On this day" in F1:** race anniversaries and notable events on the home page.
- **Explain-the-sport mode:** beginner-friendly explanations of DRS, ground effect, points systems, flags and tyre rules.
- **Filters and scope:** limit a chat to an era, season or driver ("Answer only about the 1980s").
- **User accounts:** saved conversations across devices, favourite drivers and teams, bookmarked answers.

### Live season
- An ingestion job after each race weekend for results, standings and race reports. The data currently ends with 2025.
- Current-season context in answers ("How does this season compare to last year?").
- Telemetry and lap times via FastF1 (2018+): lap comparisons and tyre strategy charts. `lap_times` was deliberately left out of the MVP ([DATA-STRATEGY.md](./DATA-STRATEGY.md)).
- Auto-generated summaries after each Grand Prix.
