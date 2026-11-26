# ApexGPT: Progress

Where the project stands, and the features worked on since the MVP. **Read this first when resuming work.**

- **How to update:** follow [WORKFLOW.md](./WORKFLOW.md).
  - When a feature's PR is raised, add or update its row under **Features**.
  - Tick it after the merge.
  - Keep **Current status** and **Next up** true.
  - Close or add **Open issues** as they change.
- **History:** the MVP's plan, checklists, Decision Log and day-by-day Session Log are in the [v1.0.0 MVP archive](./archive/v1.0.0-mvp/).

Related: [PLAN.md](./PLAN.md) (the features being built now) · [FEATURES.md](./FEATURES.md) (what's planned) · [DEPLOYMENT.md](./DEPLOYMENT.md) (running it) · [DATA-STRATEGY.md](./DATA-STRATEGY.md) (the data) · [WORKFLOW.md](./WORKFLOW.md) (how work is done)

---

## Current status

| | |
|---|---|
| **Version** | [v1.0.0](https://github.com/RChaubey16/apexgpt/releases/tag/v1.0.0), the MVP (released 2026-11-26) |
| **Live** | https://apexgpt.ruturaj.xyz · API https://apexgpt-api.ruturaj.xyz |
| **Hosting** | Coolify on one VPS (backend 768 MB / 1 CPU, frontend 384 MB) · Neon Postgres 18 + pgvector (~80 MB of the 1 GB free tier) |
| **Data** | Seasons 1950–2025: Jolpica-F1 statistics, 14,581 chunks from ~2,350 Wikipedia articles |
| **Health** | Production smoke test PASS (infrastructure 7/7, answers 8/8) · weekly encrypted backup verified by a test restore |
| **In progress** | Phase 8 (v1.1.0): F8.1 app icons and favicons (PR raised). See [PLAN.md](./PLAN.md) |
| **Last updated** | 2026-11-26 |

**What v1.0.0 does:**
- Cited answers to F1 statistics questions (text-to-SQL over five stats views) and history questions (hybrid search with reranking over Wikipedia).
- Follow-ups, corrected false premises, and declined out-of-scope questions.
- A streaming chat UI with local history, copy and feedback.

The full list is in [FEATURES.md](./FEATURES.md#shipped-in-v100).

## Next up

**Phase 8, v1.1.0** ([PLAN.md](./PLAN.md)): app icons, page metadata, a current-season endpoint, a frontend revamp and a `/season` page, built one at a time. **F8.1** is in review; next is **F8.2, `feature/page-metadata`**.

After that, pick from:
1. **The open issues below,** especially the ones marked ⭐ (they affect answer quality or operations).
2. **The planned features** in [FEATURES.md](./FEATURES.md#planned).

Before shipping a change that affects answers, run the evaluation (`python -m evals run` or `rescore`, judged by one pinned provider) and, after deploying, the production smoke test (`python -m evals smoke`).

---

## Features

Work since v1.0.0. Status: ⬜ planned · 🟡 in progress · 🔍 PR raised · ✅ merged · ⛔ blocked.

### Phase 8: v1.1.0 ([plan](./PLAN.md))

| Feature | Branch | PR | Status | Notes |
|---|---|---|---|---|
| F8.1 App icons and favicons | `feature/app-icons` | | 🔍 | Logo = the header's three speed stripes (`frontend/brand/`); `npm run icons` generates the favicon (16/32/48), SVG icon, Apple icon, manifest icons (192/512/maskable) and the API domain's favicon |
| F8.2 Page metadata and social previews | `feature/page-metadata` | | ⬜ | |
| F8.3 Current season endpoint | `feature/season-api` | | ⬜ | |
| F8.4 Frontend revamp | `feature/frontend-revamp` | | ⬜ | Install the frontend-design skill first |
| F8.5 Current season page | `feature/season-page` | | ⬜ | |
| Deploy, smoke test, tag `v1.1.0` | | | ⬜ | |

The MVP's 44 features (F0.1–F7.4) are listed in the [archived PROGRESS.md](./archive/v1.0.0-mvp/PROGRESS.md#feature-checklists).

---

## Open issues

Carried over from the MVP (each tag is the feature where the issue was found). ⭐ = most worth doing next.

### Answer quality
- ⭐ **No before/after measurement of the F6.3 tuning yet.** The eval judge grades differently by provider: on identical answers, 7 of 54 verdicts changed between Groq (strict) and Gemini (lenient). Runs judged through the fallback chain can't be compared, which is why the judge is now pinned. Re-judge both runs with one pinned provider when its quota allows: `python -m evals rescore <run> --judge-provider groq` on `data/eval/runs/20261126T031244Z-baseline` and `…T034345Z-tuned`. *(F6.3)*
- ⭐ **Fallback "echo".** After a provider switch mid-answer, a model can repeat our flattened tool history as its answer (nemotron answered "I called query_stats with {…}."). `prepare_messages` in `backend/app/llm/client.py` writes other providers' tool calls as "I called X with Y."; rephrase or summarise, and test on all three providers. *(F3.3/F6.3)*
- **Prompt rules not checked live yet.** Two rules from F6.3 haven't been run against a live model:
  - a false premise must be checked with the tools (`trick-hamilton-ferrari-title` once answered from memory);
  - a race missing from the data must be explained, not reported as "data not available" (`trick-monaco-2020`).

  Run `python -m evals run --category trick`. *(F6.3)*
- **The follow-up rewrite can add a name** the conversation didn't contain ("the race director" → "Michael Masi"). Requests that aren't questions ("shorter please") are rewritten like questions. *(F4.2)*
- **Retrieval misses:** "the first ever World Championship race" (no year in the question) and the Indianapolis 500's championship years. Both are still answered correctly end to end, because the LLM picks better search terms. The 1988 season article drops from 5th to 8th after reranking. *(F6.2/F6.3)*
- **Fallback providers' answers** (Gemini flash-lite, nemotron) are less polished than gpt-oss-120b's. Score each provider on the golden set, and revisit the defaults as free tiers change. *(F6)*
- **Entity resolution:**
  - an everyday-word surname in an all-lowercase question isn't found ("pace" for Carlos Pace);
  - an ambiguous name ("Schumacher" alone, with no season) isn't mentioned as ambiguous in the answer. *(F3.4)*
- **Search terms:** words like "explain" or "tell me about" count towards the full-text and article lists. *(F3.6)*

### Capacity and cost
- **Free-tier LLM limits are the real capacity limit.** Groq allows ~8k tokens a minute (~1–2 answers) before fallback, and under pressure an answer can take ~60 s. The server itself handled 40 concurrent answers. *(F6.4/F7.4)*
- **The `query_stats` tool description** is ~6,000 characters, sent with every request that offers the tool. Offer tools only when needed, or shorten it. *(F3.7/F6.3)*

### Operations
- ⭐ **A deploy has a short outage.** Coolify removes the old containers before the new ones are healthy: a few seconds of HTTP 503. The answer cache also starts empty. Deploy outside busy hours, or look at Coolify's rolling updates. *(F7.4)*
- **Migrations run on every backend start.** Keep them additive, or deploy a non-backward-compatible one separately. *(F7.1)*
- **Logs rotate by size, not age** (10 MB × 5). They hold users' questions; add time-based rotation if a time limit is wanted, like feedback's 90 days. *(F4.5/F7.1)*
- **GitHub disables scheduled workflows** after 60 days without commits. If the weekly backup stops, re-enable it under **Actions**. *(F7.3)*

### Behaviour worth knowing (by design, for now)
- **Two browser tabs with the same chat open:** the last save wins. *(F5.4)*
- **The answer cache isn't cleared by a data reload;** entries expire after 24 h. *(F4.4)*
- **Corpus details:** 4 chunks are longer than the embedder's 512 tokens (their ends are only in full-text search), and 39 articles are very short stubs. *(F2.3/F2.4)*
