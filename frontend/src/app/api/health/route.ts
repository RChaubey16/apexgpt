/**
 * Frontend liveness, used by the Docker/Coolify healthcheck.
 * Does not call the backend: each service reports only on itself.
 */
export function GET() {
  return Response.json({ status: "ok", service: "apexgpt-frontend" });
}
