// A /api/season/current response for the season tests (F8.5): 2026 after
// round 21 of 23, the Qatar GP next.

import type { SeasonSnapshot } from "@/lib/season";

export const NOW = Date.parse("2026-11-27T12:00:00Z");

export function snapshot(overrides: Partial<SeasonSnapshot> = {}): SeasonSnapshot {
  return {
    season: 2026,
    round: 21,
    total_rounds: 23,
    complete: false,
    drivers: [
      {
        position: 1,
        position_text: "1",
        driver_id: "antonelli",
        code: "ANT",
        number: 12,
        given_name: "Andrea Kimi",
        family_name: "Antonelli",
        nationality: "Italian",
        team: "Mercedes",
        team_id: "mercedes",
        points: 402,
        wins: 9,
      },
      {
        position: 2,
        position_text: "2",
        driver_id: "max_verstappen",
        code: "VER",
        number: 3,
        given_name: "Max",
        family_name: "Verstappen",
        nationality: "Dutch",
        team: "Red Bull",
        team_id: "red_bull",
        points: 304.5,
        wins: 4,
      },
      {
        position: 3,
        position_text: "3",
        driver_id: "newbie",
        code: null,
        number: null,
        given_name: "New",
        family_name: "Driver",
        nationality: null,
        team: "New Team",
        team_id: "new_team",
        points: 12,
        wins: 0,
      },
    ],
    constructors: [
      {
        position: 1,
        position_text: "1",
        constructor_id: "mercedes",
        name: "Mercedes",
        nationality: "German",
        points: 666,
        wins: 12,
      },
      {
        position: 2,
        position_text: "2",
        constructor_id: "ferrari",
        name: "Ferrari",
        nationality: "Italian",
        points: 517,
        wins: 2,
      },
    ],
    next_race: {
      season: 2026,
      round: 22,
      name: "Qatar Grand Prix",
      url: "https://en.wikipedia.org/wiki/2026_Qatar_Grand_Prix",
      circuit: {
        circuit_id: "losail",
        name: "Lusail International Circuit",
        locality: "Lusail",
        country: "Qatar",
      },
      date: "2026-11-29",
      start: "2026-11-29T16:00:00Z",
      sessions: [
        { kind: "practice_1", date: "2026-11-27", start: "2026-11-27T10:30:00Z" },
        { kind: "qualifying", date: "2026-11-28", start: "2026-11-28T18:00:00Z" },
        { kind: "race", date: "2026-11-29", start: "2026-11-29T16:00:00Z" },
      ],
    },
    fetched_at: "2026-11-27T11:55:00Z",
    stale: false,
    ...overrides,
  };
}
