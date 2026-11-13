# ApexGPT — Lean Data Strategy

**Rule:** store only what someone might actually ask about, and keep each fact in exactly one place. Numbers live in SQL tables. Stories live in the vector store. Nothing is stored in both.

**Why lean:** production uses the Neon free tier (1 GB storage per project; writes that add data fail beyond it). Lean data also improves answers, because removing tables and boilerplate means search results contain more story and less noise. Smaller indexes also load faster after Neon's cold starts.

**Target:** ~110–150 MB total, leaving ~85% headroom for post-MVP features.

---

## 1. Structured Data (SQL)

| Table | Keep? | Reason |
|---|---|---|
| `seasons`, `circuits`, `drivers`, `constructors`, `races`, `status` | ✅ | Core entities, small |
| `results`, `sprint_results` | ✅ | Most stats questions depend on these (wins, podiums, DNFs) |
| `qualifying` | ✅ | Pole and front-row questions (~10k rows) |
| `driver_standings`, `constructor_standings` | ✅ | "Who led after round 10?", future points charts; a few MB |
| `pit_stops` | ✅ | Small (2011+, ~11k rows); answers "fastest pit stop" questions |
| `lap_times` | ❌ Deferred | 600k+ rows, larger than everything else combined; rarely asked. Returns with FastF1 in the Live Season phase. |
| `driver_aliases`, `constructor_aliases` | ✅ | Tiny; needed to recognise names like "Schumi", "Checo" |
| `constructor_lineage` | ✅ | Tiny; team histories (Tyrrell → BAR → Honda → Brawn → Mercedes) |

**Column and type rules**
- Drop redundant columns (e.g. text duplicates of numeric fields such as `position_text`).
- Use compact types: `smallint` for positions/grid/laps/rounds, `int` for IDs, `numeric(6,2)` or `real` for points.
- Keep each entity's Wikipedia URL (used for citations).
- Times (race time, fastest lap, qualifying laps, pit stop duration) are stored once, as integer milliseconds (`*_ms`).
- `results.position` is the classified finishing position and is NULL for unclassified cars; `position_order` is the full classification order. Results are one row per car entry, not per (race, driver): 1950s shared drives mean a driver can appear twice in one race, and co-drivers share a position and split points.

- **Qualifying data exists only from 1994** (as in Ergast). Pole positions across all eras therefore come from `results.grid = 1`, which matches the official counts (Senna 65, Hamilton 104); `qualifying.position = 1` is only valid from 1994. The stats views (F1.4) must use the grid definition.
- A fastest-lap rank of 0 in the source means "no timed lap" and is stored as NULL.

**Source:** the Jolpica-F1 CSV database dump (free tier, delayed 14 days, non-commercial use). It covers 1950 to the current season in Jolpica's own session-based schema, so the loader (F1.2) transforms it rather than copying it.

**Estimated size:** ~15–25 MB including indexes.

---

## 2. Narrative Corpus (Vectors)

### 2a. Content Stripping

Remove from every article:
- **All tables**: classification tables, standings after each race, "Complete Formula One World Championship results" grids. SQL already holds these numbers. Removing tables alone cuts the corpus by ~40–60%.
- **Sections:** References, External links, See also, Notes, Further reading, Bibliography, Helmet, Racing record, Career summary.
- **Page furniture:** infoboxes, navboxes, image captions, citation markers (`[1]`, `[citation needed]`).

### 2b. Article Selection by Importance

| Article set | Depth | Approx. count |
|---|---|---|
| Season articles ("YYYY Formula One World Championship", 1950–2025) | Full text | 76 |
| Grand Prix race reports | Background + race report sections only | ~1,150 |
| **Notable drivers** | Full biography | ~250 |
| Other drivers | Intro paragraph only | ~530 |
| **Major constructors** | Full article | ~60 |
| Minor constructors | Intro paragraph only | ~100 |
| Circuits | Intro + history sections | ~77 |
| **Curated topic articles** | Full article | ~150 |

**Notable driver** = meets any of: World Champion, race winner, podium finisher, or 30+ championship starts. Computed from the structured data, not hand-picked.

**Major constructor** = meets any of: Constructors' Champion, race winner, or 5+ seasons entered. Computed from the structured data.

**Curated topics** live in a hand-maintained list (`ingestion/narrative/topics.yaml`), grouped into:
- Rivalries (Senna–Prost, Hunt–Lauda, Hamilton–Rosberg, Hamilton–Verstappen, …)
- Fatal accidents and major crashes, and the safety changes that followed
- Controversies (Spygate, Crashgate, Indianapolis 2005, Abu Dhabi 2021, …)
- Regulation eras (ground effect, turbo era, V10s, hybrid era, 2022 regulations, …)
- Iconic races and title deciders
- Sport concepts (points systems history, DRS, safety car, flags)

The curated topic list is the most valuable part of the corpus: it targets the "crashes, rivalries, famous races" questions directly.

### 2c. Chunking and Storage Rules

| Rule | Detail |
|---|---|
| Chunk size | ~400–600 tokens, split on section boundaries |
| Overlap | ~50 tokens within a section; none across section boundaries |
| Vector type | `halfvec(384)` (16-bit), which halves vector and index size with negligible quality loss |
| Vector index | HNSW on the `halfvec` column (`halfvec_cosine_ops`) |
| Full-text search | GIN index directly on `to_tsvector('english', text)`, with **no stored `tsvector` column** |
| Metadata | Integer columns/arrays: `season`, `race_id`, `driver_ids int[]`, `constructor_ids int[]`, `circuit_id`, `topic` (short text), `source_url`, `section` |
| Raw articles | Not stored in the DB. Kept in a git-ignored `data/` folder on the dev machine; chunks store only `source_url` |

**Estimated corpus:** ~2,400 articles → ~12–15k chunks → ~80–120 MB.

---

## 3. Operational Data

| Data | Where | Retention |
|---|---|---|
| Answer cache | In memory on the backend (LRU) | Process lifetime |
| Query logs | Rotated log files on the VPS | 14 days |
| Feedback (👍/👎) | DB table: question, short answer excerpt (≤500 chars), rating, timestamp | 90 days, then deleted |

**Estimated size:** <10 MB.

---

## 4. Size Guard

The ingestion pipeline enforces the budget:
- Prints the size of each table (`pg_total_relation_size`) after every run.
- **Warns at 700 MB** total database size.
- **Refuses to load at 900 MB**, which keeps a safe margin below Neon's 1 GB per-project limit.

---

## 5. Budget Summary

| Area | Estimate |
|---|---|
| Structured | ~15–25 MB |
| Narrative | ~80–120 MB |
| Operational | <10 MB |
| **Total** | **~110–150 MB of 1 GB** |

---

## 6. Deferred Data (Post-MVP)

| Data | Returns with |
|---|---|
| `lap_times` | Live Season phase (FastF1 telemetry, 2018+) |
| Fuller bios for non-notable drivers | Only if eval/feedback shows demand |
| Live season results and race reports | Live Season phase |

If the data later approaches 1 GB, upgrade the Neon plan or move to self-hosted pgvector with a `pg_dump`/restore, because the schema stays the same.
