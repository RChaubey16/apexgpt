import { describe, expect, it, vi } from "vitest";

import {
  championsLine,
  countdown,
  fetchSeason,
  formatPoints,
  formatSessionDate,
  formatSessionTime,
  gapToLeader,
  isSeasonSnapshot,
  NEUTRAL_TEAM_COLOUR,
  SeasonError,
  teamColour,
  type SeasonSnapshot,
} from "@/lib/season";
import { snapshot } from "@/test/season";

const BASE = "http://backend.test";

function respond(status: number, body: unknown, headers: Record<string, string> = {}) {
  return vi.fn<typeof fetch>(
    async () =>
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status,
        headers,
      }),
  );
}

describe("fetchSeason", () => {
  it("returns a valid snapshot from the endpoint", async () => {
    const fetchImpl = respond(200, snapshot());
    await expect(fetchSeason(BASE, { fetchImpl })).resolves.toEqual(snapshot());
    expect(fetchImpl.mock.calls[0][0]).toBe(`${BASE}/api/season/current`);
  });

  it.each([
    ["a 503", respond(503, { detail: "x" }), /unavailable right now/],
    ["a 500", respond(500, "oops"), /can't read/],
    ["bad JSON", respond(200, "<html>"), /can't read/],
    ["a bad shape", respond(200, { ...snapshot(), drivers: "none" }), /can't read/],
    [
      "a 429 with Retry-After",
      respond(429, {}, { "Retry-After": "30" }),
      /in 30 seconds/,
    ],
    ["a 429 without it", respond(429, {}), /in a minute/],
    [
      "a network error",
      vi.fn<typeof fetch>(async () => {
        throw new TypeError("fail");
      }),
      /Can't reach the server/,
    ],
  ])("turns %s into a safe message", async (_, fetchImpl, message) => {
    await expect(fetchSeason(BASE, { fetchImpl })).rejects.toThrow(message);
    await expect(fetchSeason(BASE, { fetchImpl })).rejects.toBeInstanceOf(SeasonError);
  });

  it("keeps the 429's wait", async () => {
    const error = await fetchSeason(BASE, {
      fetchImpl: respond(429, {}, { "Retry-After": "12" }),
    }).then(
      () => null,
      (e: SeasonError) => e,
    );
    expect(error?.retryAfterSeconds).toBe(12);
  });

  it("rethrows the caller's abort, not a message", async () => {
    const controller = new AbortController();
    controller.abort();
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new DOMException("aborted", "AbortError");
    });
    await expect(
      fetchSeason(BASE, { fetchImpl, signal: controller.signal }),
    ).rejects.toHaveProperty("name", "AbortError");
  });
});

describe("isSeasonSnapshot", () => {
  it("accepts the off-season and a race with unpublished times", () => {
    expect(isSeasonSnapshot(snapshot({ next_race: null, complete: true }))).toBe(true);
    const race = snapshot().next_race!;
    expect(
      isSeasonSnapshot(
        snapshot({
          next_race: {
            ...race,
            start: null,
            sessions: [{ kind: "race", date: race.date, start: null }],
          },
        }),
      ),
    ).toBe(true);
  });

  it.each([
    ["an unknown session", { kind: "warm_up", date: "2026-11-29", start: null }],
    ["a bad date", { kind: "race", date: "soon", start: null }],
  ])("rejects %s", (_, session) => {
    const race = snapshot().next_race!;
    expect(
      isSeasonSnapshot(
        snapshot({ next_race: { ...race, sessions: [session as never] } }),
      ),
    ).toBe(false);
  });

  it("rejects missing fields and non-objects", () => {
    expect(isSeasonSnapshot(null)).toBe(false);
    expect(isSeasonSnapshot([])).toBe(false);
    const missing: Partial<SeasonSnapshot> = snapshot();
    delete missing.stale;
    expect(isSeasonSnapshot(missing)).toBe(false);
    expect(isSeasonSnapshot(snapshot({ drivers: [{ points: "lots" } as never] }))).toBe(
      false,
    );
  });
});

describe("helpers", () => {
  it("writes points and gaps like a timing tower", () => {
    expect(formatPoints(402)).toBe("402");
    expect(formatPoints(304.5)).toBe("304.5");
    expect(gapToLeader(402, 402)).toBe("Leader");
    expect(gapToLeader(304.5, 402)).toBe("−97.5");
    expect(gapToLeader(12, 402)).toBe("−390");
  });

  it("counts down to a start, and stops once it's passed", () => {
    const start = "2026-11-29T16:00:00Z";
    const now = Date.parse("2026-11-28T13:45:30Z");
    expect(countdown(start, now)).toEqual({
      days: 1,
      hours: 2,
      minutes: 14,
      seconds: 30,
    });
    expect(countdown(start, Date.parse(start))).toBeNull();
    expect(countdown(start, Date.parse(start) + 1000)).toBeNull();
  });

  it("shows session times in a given time zone", () => {
    const start = "2026-11-29T16:00:00Z";
    expect(formatSessionTime(start, { timeZone: "UTC" })).toBe("Sun 29 Nov, 16:00");
    expect(formatSessionTime(start, { timeZone: "Asia/Kolkata" })).toBe(
      "Sun 29 Nov, 21:30",
    );
    expect(formatSessionDate("2026-11-29")).toBe("Sun 29 Nov");
  });

  it("gives every team a stripe colour, neutral for one it doesn't know", () => {
    expect(teamColour("mercedes")).toBe("#27f4d2");
    expect(teamColour("new_team")).toBe(NEUTRAL_TEAM_COLOUR);
    expect(teamColour(null)).toBe(NEUTRAL_TEAM_COLOUR);
  });
});

describe("championsLine (F8.7)", () => {
  const both = { driver_id: "antonelli", constructor_id: "mercedes" };

  it("names both champions", () => {
    expect(championsLine(snapshot({ champions: both }))).toBe(
      "Andrea Kimi Antonelli and Mercedes are the 2026 world champions.",
    );
  });

  it("names one, saying the other title is open", () => {
    expect(
      championsLine(snapshot({ champions: { ...both, constructor_id: null } })),
    ).toBe(
      "Andrea Kimi Antonelli is the 2026 world champion. The constructors' title is still open.",
    );
    expect(championsLine(snapshot({ champions: { ...both, driver_id: null } }))).toBe(
      "Mercedes are the 2026 constructors' champions. The drivers' title is still open.",
    );
  });

  it("says nothing while both are open, or for an id not in the standings", () => {
    expect(championsLine(snapshot())).toBeNull();
    expect(
      championsLine(
        snapshot({ champions: { driver_id: "nobody", constructor_id: null } }),
      ),
    ).toBeNull();
  });

  it("is validated in the response", () => {
    expect(isSeasonSnapshot(snapshot({ champions: both }))).toBe(true);
    // A backend from before F8.7 sends none: no champions, not bad data.
    const old: Partial<SeasonSnapshot> = snapshot();
    delete old.champions;
    expect(isSeasonSnapshot(old)).toBe(true);
    expect(championsLine(old as SeasonSnapshot)).toBeNull();
    expect(isSeasonSnapshot(snapshot({ champions: null as never }))).toBe(false);
    expect(
      isSeasonSnapshot(
        snapshot({ champions: { driver_id: 1, constructor_id: null } as never }),
      ),
    ).toBe(false);
  });
});
