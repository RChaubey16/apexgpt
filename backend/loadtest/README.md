# Load and cold-start tests

These tests run the backend's **production image** under its VPS budget (768 MB, 1 CPU). The backend answers through a **stub LLM** on the host, so the test spends no free-tier quota. Everything else is real: entity resolution, hybrid search and reranking, the stats database and SSE streaming.

## Run

From the repository root:

```bash
# 1. The stub LLM (OpenAI-compatible; delays imitate a fast free-tier model)
(cd backend && uv run uvicorn loadtest.stub_llm:app --host 127.0.0.1 --port 9100)

# 2. The production backend, pointed at the stub, no rate limits, no answer cache
docker compose -f docker-compose.yml -f backend/loadtest/docker-compose.loadtest.yml \
  up -d --build --wait backend

# 3. Measure
cd backend
uv run python -m loadtest coldstart --runs 3            # restarts the container
uv run python -m loadtest load --users 1,2,5,10,20 --requests 40

# 4. Back to the dev server
cd .. && docker compose up -d --build backend
```

Results (JSON and markdown) are saved in `data/loadtest/<time>/`.

**What it needs:**
- the corpus loaded;
- the search models in `data/models/`;
- the read-only role enabled (as for `python -m app.answer`).

**Stub delays** are environment variables, in milliseconds: `STUB_TOOL_DELAY_MS` (600), `STUB_FIRST_TOKEN_MS` (400) and `STUB_TOKEN_MS` (15). `STUB_TOKENS` (40) is the number of pieces per answer.

## Results (2026-11-26, Docker Desktop on a laptop, 1 CPU / 768 MiB)

**Cold start.** The models were already in `data/models/`.
- After `docker restart`, `/health` and `/health/ready` answer in **~1.1 s**.
- The first knowledge search, which loads both ONNX models, takes **1.0–1.4 s**, against 0.65–0.8 s warm.
- The first answer is done in **2.4–2.9 s**, the second in ~2.2 s.
- Memory is ~90 MiB idle and ~350 MiB with both models loaded.

**Load.** Questions are the golden set's, both stats and knowledge.

| Users | OK | Answers/min | Done p50 / p95 | Knowledge search p95 | Peak memory |
|---:|---:|---:|---|---:|---:|
| 1 | 40/40 | 32 | 1.6 / 2.5 s | 1.0 s | 373 MiB |
| 2 | 40/40 | 59 | 1.6 / 3.3 s | 1.8 s | 407 MiB |
| 5 | 40/40 | 83 | 1.6 / 8.9 s | 8.0 s | 444 MiB |
| 10 | 40/40 | 66 | 1.6 / 26 s | 25 s | 594 MiB |
| 20 | 40/40 | 89 | 1.8 / 24 s | 24 s | 602 MiB |
| 40 | 80/80 | 85 | 17 / 37 s | 37 s | 614 MiB |

**What this means:**
- **No failures, and no OOM kill even at 40 concurrent answers** (the thread pool's limit). Memory flattens out at ~610 MiB, leaving ~150 MiB of headroom.
- **CPU is the limit inside the box.** One CPU runs at 100% from the first user. Knowledge searches queue behind each other (ONNX, one thread), so their latency grows with concurrency. Stats answers stay fast. Throughput levels off at roughly 60–90 answers a minute.
- **In production the LLM is the tighter limit.** Groq's free tier allows ~8k tokens a minute, which is about 1–2 answers a minute at ~6k tokens each before the fallbacks take over. The per-IP limit is 6 answers a minute and 100 a day.
- **Not measured here:** Neon's cold start (the production database suspends after 5 idle minutes). It's measured in the production smoke test (F7.4).
