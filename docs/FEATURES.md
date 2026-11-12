# ApexGPT — Feature Plan

All features planned for ApexGPT, grouped into tiers. **Tier 1 is the MVP** (see [MVP-PLAN.md](./MVP-PLAN.md)). Tier 2, Tier 3 and the Live Season phase will be prioritised after the MVP ships.

Coverage scope: **1950 → 2025**. The ongoing season comes in the Live Season phase.

---

## Tier 1 — Core (MVP)

### 1. Conversational Q&A
- Ask anything in natural language about drivers, constructors, circuits, seasons, races, crashes, rivalries and championship battles.
- Streaming responses (token by token).
- Follow-up awareness ("What about his teammate that year?").
- Every answer cites its sources (article links, race references).
- Honest "I don't know" when the data doesn't cover something, with no made-up answers.

### 2. Accurate Stats Answers
- Counting, ranking and comparison questions are answered with real queries against structured data, not from text chunks.
- Results are shown as tables where that's clearer (e.g. "Top 10 drivers by pole positions").

### 3. Full Coverage (1950–2025)
- Championships, races, qualifying, sprints, fastest laps, DNFs and their reasons.
- Changes over time: points systems, regulation eras, team name changes and lineage (e.g. Toleman → Benetton → Renault → Lotus → Alpine).

### 4. Basic Chat UX
- Suggested starter questions ("Greatest title deciders", "Explain the 2021 Abu Dhabi controversy").
- Copy or share an answer.
- Chat history kept in the browser (no login).
- Answer feedback (👍/👎).

---

## Tier 2 — Enhanced Experience

### 5. Entity Pages (generated from data)
- **Driver profile:** career stats, teams, titles, teammates, best seasons, notable moments.
- **Constructor profile:** history, lineage, championships, legendary cars.
- **Circuit profile:** layout history, lap records, most successful drivers, famous races there.
- **Season page:** calendar, final standings, title battle summary, key storylines.
- Entities mentioned in chat answers become clickable links to these pages.

### 6. Comparisons
- Driver vs driver head-to-head (overall, or as teammates in equal machinery).
- Era comparisons (e.g. Schumacher's Ferrari era vs Hamilton's Mercedes era).
- Constructor vs constructor across eras.

### 7. Visual Answers
- Championship points progression charts (e.g. the 2010 four-way title fight).
- Win and podium bar charts; season-by-season career timelines.
- The LLM decides when a chart helps and returns chart data alongside the text.

### 8. Curated Story Collections
- **Rivalries:** Senna–Prost, Hunt–Lauda, Hamilton–Rosberg, Hamilton–Verstappen, and more.
- **Title deciders:** 1976, 1986, 2007, 2008, 2010, 2012, 2021.
- **Safety & crashes:** major incidents and the safety changes that followed (handled respectfully).
- **Iconic races:** Canada 2011, Brazil 2008, Donington 1993, and more.

---

## Tier 3 — Engagement & Power Features

### 9. F1 Trivia / Quiz Mode
- Quizzes generated from the structured data.
- Difficulty levels and era filters.

### 10. "On This Day" in F1
- Race anniversaries and notable events on the home page.

### 11. Explain-the-Sport Mode
- Beginner-friendly explanations: DRS, ground effect, points systems, flag rules, tyre rules.

### 12. Filters & Scope Controls
- Limit a chat to an era, season or driver ("Answer only about the 1980s").

### 13. User Accounts
- Saved conversations, favourite drivers and teams, bookmarked answers.

### 14. Answer Feedback Analytics
- Logged feedback used to evaluate and improve retrieval quality over time.

---

## Live Season Phase

- An ingestion job after each race weekend for results, standings and race reports.
- Current-season context in answers (e.g. "How does this season compare to last year?").
- Telemetry and lap-time analysis via FastF1 (2018+): lap comparisons, tyre strategy charts.
- Auto-generated race weekend summaries after each Grand Prix.

---

## Admin & Operations (internal)

- Re-runnable ingestion pipeline (fetch → clean → chunk → embed → upsert), triggered from the CLI or an admin endpoint.
- Evaluation set (~100 F1 questions with known answers) to catch retrieval regressions.
- Rate limiting per IP (free LLM tiers have limits).
- Logging of queries, latency and token use per provider.
