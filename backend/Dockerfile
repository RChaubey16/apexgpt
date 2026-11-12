# syntax=docker/dockerfile:1

# ---------- Builder: resolve and install dependencies with uv ----------
FROM python:3.12-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:0.11.2 /uv /bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /app

# Install dependencies first (cached unless the lockfile changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# ---------- Dev: adds test dependencies; used by docker compose ----------
FROM builder AS dev

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

ENV PATH="/app/.venv/bin:$PATH"
COPY . .
EXPOSE 8000
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# ---------- Runtime: slim image, non-root, no build tools ----------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN groupadd --system app && useradd --system --gid app --no-create-home app

WORKDIR /app

COPY --from=builder /app/.venv /app/.venv
COPY app ./app
# Migrations ship with the image so they can be run in place:
#   docker run --rm -e DATABASE_URL=... <image> alembic upgrade head
COPY alembic.ini ./
COPY migrations ./migrations

USER app

EXPOSE 8000

# Liveness only: /health never touches the database, so this 30s poll does not
# keep Neon awake. Readiness (with DB check) is /health/ready.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"]

# Proxy headers (X-Forwarded-For/Proto) are trusted only from the IPs in
# FORWARDED_ALLOW_IPS (read natively by uvicorn). The default trusts nothing
# but localhost; production sets it to the Traefik proxy address (F7.1).
ENV FORWARDED_ALLOW_IPS=127.0.0.1

# Single worker: keeps memory within the VPS budget (embedding models load per worker).
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers"]
