/**
 * Backend API client.
 *
 * `checkReadiness` calls `/health/ready`, which also wakes a suspended Neon
 * database. A cold start can take a second or two, hence the generous timeout.
 */

export type ReadinessState =
  | "ready" // backend and database OK
  | "database_unavailable" // backend up, database down or waking (503)
  | "unreachable" // network error, timeout or CORS failure
  | "unexpected_response"; // anything else (bad status or body)

export const DEFAULT_READINESS_TIMEOUT_MS = 10_000;

interface CheckOptions {
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
}

function isReadinessBody(body: unknown): body is { status: string; database: string } {
  return (
    typeof body === "object" &&
    body !== null &&
    typeof (body as Record<string, unknown>).status === "string" &&
    typeof (body as Record<string, unknown>).database === "string"
  );
}

export async function checkReadiness(
  baseUrl: string,
  {
    timeoutMs = DEFAULT_READINESS_TIMEOUT_MS,
    fetchImpl = fetch,
    signal,
  }: CheckOptions = {},
): Promise<ReadinessState> {
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/health/ready`, {
      method: "GET",
      headers: { Accept: "application/json" },
      cache: "no-store",
      signal: combined,
    });
  } catch {
    return "unreachable";
  }

  if (response.status !== 200 && response.status !== 503) {
    return "unexpected_response";
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return "unexpected_response";
  }
  if (!isReadinessBody(body)) {
    return "unexpected_response";
  }

  if (response.status === 200 && body.status === "ok" && body.database === "ok") {
    return "ready";
  }
  if (response.status === 503 && body.database === "unavailable") {
    return "database_unavailable";
  }
  return "unexpected_response";
}
