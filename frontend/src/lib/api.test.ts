import { describe, expect, it, vi } from "vitest";

import { checkReadiness } from "./api";

const BASE = "http://backend.test";

function jsonResponse(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function fetchReturning(response: Response | Promise<Response>) {
  return vi.fn<typeof fetch>().mockImplementation(async () => response);
}

describe("checkReadiness", () => {
  it("calls /health/ready without caching", async () => {
    const fetchImpl = fetchReturning(jsonResponse(200, { status: "ok", database: "ok" }));

    await checkReadiness(BASE, { fetchImpl });

    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, init] = fetchImpl.mock.calls[0];
    expect(url).toBe(`${BASE}/health/ready`);
    expect(init?.cache).toBe("no-store");
    expect(init?.method).toBe("GET");
  });

  it("returns ready on 200 ok/ok", async () => {
    const fetchImpl = fetchReturning(jsonResponse(200, { status: "ok", database: "ok" }));

    await expect(checkReadiness(BASE, { fetchImpl })).resolves.toBe("ready");
  });

  it("returns database_unavailable on 503", async () => {
    const fetchImpl = fetchReturning(
      jsonResponse(503, { status: "unavailable", database: "unavailable" }),
    );

    await expect(checkReadiness(BASE, { fetchImpl })).resolves.toBe(
      "database_unavailable",
    );
  });

  it("returns unreachable on network error", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockRejectedValue(new TypeError("fail"));

    await expect(checkReadiness(BASE, { fetchImpl })).resolves.toBe("unreachable");
  });

  it("returns unreachable when the request times out", async () => {
    const fetchImpl = vi.fn<typeof fetch>().mockImplementation(
      (_url, init) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () =>
            reject(new DOMException("timed out", "TimeoutError")),
          );
        }),
    );

    await expect(checkReadiness(BASE, { fetchImpl, timeoutMs: 20 })).resolves.toBe(
      "unreachable",
    );
  });

  it.each([
    ["500 status", jsonResponse(500, { detail: "Internal server error" })],
    ["404 status", jsonResponse(404, { detail: "Not Found" })],
    ["non-JSON body", new Response("<html>", { status: 200 })],
    ["wrong shape", jsonResponse(200, { ok: true })],
    ["200 but db not ok", jsonResponse(200, { status: "ok", database: "unavailable" })],
  ])("returns unexpected_response for %s", async (_name, response) => {
    const fetchImpl = fetchReturning(response);

    await expect(checkReadiness(BASE, { fetchImpl })).resolves.toBe(
      "unexpected_response",
    );
  });
});
