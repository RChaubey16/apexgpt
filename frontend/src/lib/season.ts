/**
 * The current season (F8.5): the client for `GET /api/season/current` (F8.3)
 * and the pure helpers the /season page uses.
 *
 * - `fetchSeason` validates the response before the page sees it, and turns
 *   every failure into a `SeasonError` whose message is safe to show.
 * - Times arrive in UTC; they're shown in the visitor's time zone with Intl.
 */

export interface DriverRow {
  position: number | null;
  position_text: string;
  driver_id: string;
  code: string | null;
  number: number | null;
  given_name: string;
  family_name: string;
  nationality: string | null;
  team: string | null;
  team_id: string | null;
  points: number;
  wins: number;
}

export interface ConstructorRow {
  position: number | null;
  position_text: string;
  constructor_id: string;
  name: string;
  nationality: string | null;
  points: number;
  wins: number;
}

export type SessionKind =
  | "practice_1"
  | "practice_2"
  | "practice_3"
  | "sprint_qualifying"
  | "sprint"
  | "qualifying"
  | "race";

export interface Session {
  kind: SessionKind;
  date: string; // YYYY-MM-DD
  start: string | null; // ISO, UTC; null while the time isn't published
}

export interface NextRace {
  season: number;
  round: number;
  name: string;
  url: string | null;
  circuit: { circuit_id: string; name: string; locality: string; country: string };
  date: string;
  start: string | null;
  sessions: Session[];
}

/** Who has won each title (F8.7); null while it's still open. */
export interface Champions {
  driver_id: string | null;
  constructor_id: string | null;
}

export interface SeasonSnapshot {
  season: number;
  round: number | null;
  total_rounds: number | null;
  complete: boolean;
  drivers: DriverRow[];
  constructors: ConstructorRow[];
  next_race: NextRace | null;
  /** Optional: a backend from before F8.7 doesn't send it. */
  champions?: Champions;
  fetched_at: string;
  stale: boolean;
}

export const DEFAULT_SEASON_TIMEOUT_MS = 15_000;

export class SeasonError extends Error {
  constructor(
    message: string,
    /** Seconds to wait before retrying, from a 429's Retry-After. */
    readonly retryAfterSeconds?: number,
  ) {
    super(message);
    this.name = "SeasonError";
  }
}

const UNREACHABLE = "Can't reach the server. Check your connection and try again.";
const UNAVAILABLE =
  "The current season's data is unavailable right now. Try again later.";
const BAD_DATA = "The server sent season data this page can't read. Try again later.";

// --- validation ------------------------------------------------------------------

type Json = Record<string, unknown>;

const isObject = (v: unknown): v is Json =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isString = (v: unknown): v is string => typeof v === "string";
const isNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
const orNull =
  <T>(check: (v: unknown) => v is T) =>
  (v: unknown): v is T | null =>
    v === null || check(v);
const isDate = (v: unknown): v is string => isString(v) && !Number.isNaN(Date.parse(v));

const SESSION_KINDS: readonly SessionKind[] = [
  "practice_1",
  "practice_2",
  "practice_3",
  "sprint_qualifying",
  "sprint",
  "qualifying",
  "race",
];

function isDriver(v: unknown): v is DriverRow {
  return (
    isObject(v) &&
    orNull(isNumber)(v.position) &&
    isString(v.position_text) &&
    isString(v.driver_id) &&
    orNull(isString)(v.code) &&
    orNull(isNumber)(v.number) &&
    isString(v.given_name) &&
    isString(v.family_name) &&
    orNull(isString)(v.team) &&
    orNull(isString)(v.team_id) &&
    isNumber(v.points) &&
    isNumber(v.wins)
  );
}

function isConstructor(v: unknown): v is ConstructorRow {
  return (
    isObject(v) &&
    orNull(isNumber)(v.position) &&
    isString(v.position_text) &&
    isString(v.constructor_id) &&
    isString(v.name) &&
    isNumber(v.points) &&
    isNumber(v.wins)
  );
}

function isSession(v: unknown): v is Session {
  return (
    isObject(v) &&
    SESSION_KINDS.includes(v.kind as SessionKind) &&
    isDate(v.date) &&
    orNull(isDate)(v.start)
  );
}

function isNextRace(v: unknown): v is NextRace {
  const c = isObject(v) ? v.circuit : undefined;
  return (
    isObject(v) &&
    isNumber(v.season) &&
    isNumber(v.round) &&
    isString(v.name) &&
    orNull(isString)(v.url) &&
    isObject(c) &&
    isString(c.name) &&
    isString(c.locality) &&
    isString(c.country) &&
    isDate(v.date) &&
    orNull(isDate)(v.start) &&
    Array.isArray(v.sessions) &&
    v.sessions.every(isSession)
  );
}

export function isSeasonSnapshot(v: unknown): v is SeasonSnapshot {
  return (
    isObject(v) &&
    isNumber(v.season) &&
    orNull(isNumber)(v.round) &&
    orNull(isNumber)(v.total_rounds) &&
    typeof v.complete === "boolean" &&
    Array.isArray(v.drivers) &&
    v.drivers.every(isDriver) &&
    Array.isArray(v.constructors) &&
    v.constructors.every(isConstructor) &&
    orNull(isNextRace)(v.next_race) &&
    (v.champions === undefined ||
      (isObject(v.champions) &&
        orNull(isString)(v.champions.driver_id) &&
        orNull(isString)(v.champions.constructor_id))) &&
    isDate(v.fetched_at) &&
    typeof v.stale === "boolean"
  );
}

// --- the client --------------------------------------------------------------------

interface FetchOptions {
  timeoutMs?: number;
  fetchImpl?: typeof fetch;
  signal?: AbortSignal;
}

export async function fetchSeason(
  baseUrl: string,
  { timeoutMs = DEFAULT_SEASON_TIMEOUT_MS, fetchImpl = fetch, signal }: FetchOptions = {},
): Promise<SeasonSnapshot> {
  const timeout = AbortSignal.timeout(timeoutMs);
  const combined = signal ? AbortSignal.any([signal, timeout]) : timeout;

  let response: Response;
  try {
    response = await fetchImpl(`${baseUrl}/api/season/current`, {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: combined,
    });
  } catch (error) {
    if (signal?.aborted) throw error; // the caller went away: not an error to show
    throw new SeasonError(UNREACHABLE);
  }

  if (response.status === 429) {
    const retry = Number(response.headers.get("Retry-After"));
    const seconds = Number.isFinite(retry) && retry > 0 ? Math.ceil(retry) : undefined;
    throw new SeasonError(
      seconds
        ? `Too many requests. Try again in ${seconds} seconds.`
        : "Too many requests. Try again in a minute.",
      seconds,
    );
  }
  if (response.status === 503) throw new SeasonError(UNAVAILABLE);
  if (response.status !== 200) throw new SeasonError(BAD_DATA);

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new SeasonError(BAD_DATA);
  }
  if (!isSeasonSnapshot(body)) throw new SeasonError(BAD_DATA);
  return body;
}

// --- helpers for the page ------------------------------------------------------------

/** Points as F1 writes them: "402", or "402.5" after a half-points race. */
export function formatPoints(points: number): string {
  return Number.isInteger(points) ? String(points) : points.toFixed(1);
}

/** The interval to P1 ("−98"), or "Leader" for the leader (and ties with it). */
export function gapToLeader(points: number, leaderPoints: number): string {
  const gap = leaderPoints - points;
  return gap <= 0 ? "Leader" : `−${formatPoints(gap)}`;
}

export const SESSION_NAMES: Record<SessionKind, string> = {
  practice_1: "Practice 1",
  practice_2: "Practice 2",
  practice_3: "Practice 3",
  sprint_qualifying: "Sprint qualifying",
  sprint: "Sprint",
  qualifying: "Qualifying",
  race: "Race",
};

export interface Countdown {
  days: number;
  hours: number;
  minutes: number;
  seconds: number;
}

/** Time left until `start`, or null once it has passed. */
export function countdown(start: string, now: number): Countdown | null {
  const left = Math.floor((Date.parse(start) - now) / 1000);
  if (left <= 0) return null;
  return {
    days: Math.floor(left / 86_400),
    hours: Math.floor((left % 86_400) / 3_600),
    minutes: Math.floor((left % 3_600) / 60),
    seconds: left % 60,
  };
}

/** "Sun 29 Nov, 19:00", in the visitor's time zone (or `timeZone`, for tests). */
export function formatSessionTime(
  start: string,
  { locale, timeZone }: { locale?: string; timeZone?: string } = {},
): string {
  return new Intl.DateTimeFormat(locale ?? "en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    timeZone,
  }).format(new Date(start));
}

/** A date with no published time: "Sun 29 Nov" (the UTC calendar date). */
export function formatSessionDate(date: string, locale = "en-GB"): string {
  return new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(new Date(`${date}T00:00:00Z`));
}

/** The visitor's time zone name, for the "Times in …" note. */
export function localTimeZone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "your time zone";
  } catch {
    return "your time zone";
  }
}

/**
 * Team colours for the timing-tower stripes, by Jolpica constructor id. A
 * team not listed (a new entrant, a renamed team) gets a neutral stripe.
 * Approximate livery colours; they're a visual aid, never the only label.
 */
export const TEAM_COLOURS: Readonly<Record<string, string>> = {
  mercedes: "#27f4d2",
  ferrari: "#e8002d",
  red_bull: "#3671c6",
  mclaren: "#ff8000",
  aston_martin: "#229971",
  alpine: "#ff87bc",
  williams: "#64c4ff",
  rb: "#6692ff",
  haas: "#b6babd",
  audi: "#f50537",
  cadillac: "#c9cdd2",
};
export const NEUTRAL_TEAM_COLOUR = "#6e7a8a"; // --color-control

export function teamColour(teamId: string | null): string {
  return (teamId && TEAM_COLOURS[teamId]) || NEUTRAL_TEAM_COLOUR;
}

/**
 * The line announcing decided titles (F8.7), or null while both are open.
 * Names come from the standings; an id missing from them is ignored.
 */
export function championsLine(season: SeasonSnapshot): string | null {
  const { driver_id, constructor_id } = season.champions ?? {};
  const driver = driver_id && season.drivers.find((d) => d.driver_id === driver_id);
  const team =
    constructor_id &&
    season.constructors.find((c) => c.constructor_id === constructor_id);
  const name = driver && `${driver.given_name} ${driver.family_name}`;
  const year = season.season;
  if (name && team) return `${name} and ${team.name} are the ${year} world champions.`;
  if (name)
    return `${name} is the ${year} world champion. The constructors' title is still open.`;
  if (team)
    return `${team.name} are the ${year} constructors' champions. The drivers' title is still open.`;
  return null;
}
