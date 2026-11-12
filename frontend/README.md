# ApexGPT frontend

Next.js 16 (App Router, TypeScript, Tailwind 4), built as a standalone server for Docker.

## Commands

```bash
npm ci                 # install exact versions
npm run dev            # http://localhost:3000
npm test               # Vitest + Testing Library
npm run lint           # ESLint (zero warnings allowed)
npm run typecheck      # next typegen + tsc
npm run format         # Prettier
npm run build          # production build (.next/standalone)
```

## Configuration

| Variable              | When           | Purpose                                                                                                                     |
| --------------------- | -------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `NEXT_PUBLIC_API_URL` | **Build time** | Backend base URL (http/https, no credentials/query). Inlined into the page at `next build`, so changing it needs a rebuild. |

Locally it is read from `frontend/.env.local` (git-ignored), e.g.:

```bash
echo "NEXT_PUBLIC_API_URL=http://localhost:8000" > .env.local
```

The backend must allow the frontend's origin in `CORS_ORIGINS`.

## Docker

```bash
docker build --build-arg NEXT_PUBLIC_API_URL=http://localhost:8000 -t apexgpt-frontend .
docker run -p 3000:3000 apexgpt-frontend
```

The build fails if `NEXT_PUBLIC_API_URL` is missing. The `dev` target (`--target dev`) runs `next dev` for docker compose.

## Health

- `/api/health`: frontend liveness (Docker healthcheck). Does not call the backend.
- The home page calls the backend's `/health/ready` on load, which also wakes a suspended Neon database.
