"use client";

/**
 * The /season page body (F8.5, restyled in F8.6 after the F1 app): the next
 * race on a card with a boxed countdown, then the drivers' and constructors'
 * standings as compact rows with team colour bars.
 *
 * - Loaded in the browser from GET /api/season/current (cached by the
 *   backend for 10 minutes), like the chat and the backend status.
 * - Times are shown in the visitor's time zone; the countdown ticks each
 *   second and isn't announced to screen readers (the start time is).
 * - Stale data (Jolpica unreachable) is shown with a note; with no data at
 *   all, the error and a Retry button.
 * - Off-season: final standings, and the next season's opener once its
 *   calendar is out.
 */

import { useEffect, useState } from "react";

import {
  countdown,
  fetchSeason,
  formatPoints,
  formatSessionDate,
  formatSessionTime,
  gapToLeader,
  localTimeZone,
  SeasonError,
  SESSION_NAMES,
  teamColour,
  type ConstructorRow,
  type DriverRow,
  type NextRace,
  type SeasonSnapshot,
} from "@/lib/season";

type Load =
  | { state: "loading" }
  | { state: "error"; message: string }
  | { state: "ready"; season: SeasonSnapshot };

interface SeasonViewProps {
  /** Validated backend URL, or null if config is invalid. */
  apiBaseUrl: string | null;
  /** For tests: the season client. */
  load?: typeof fetchSeason;
  /** For tests: the clock (epoch ms) and the time zone to show times in. */
  now?: () => number;
  timeZone?: string;
}

export function SeasonView({
  apiBaseUrl,
  load = fetchSeason,
  now = Date.now,
  timeZone,
}: SeasonViewProps) {
  const [result, setResult] = useState<Load>(
    apiBaseUrl
      ? { state: "loading" }
      : { state: "error", message: "This page is misconfigured (no backend URL)." },
  );
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!apiBaseUrl) return;
    const controller = new AbortController();
    load(apiBaseUrl, { signal: controller.signal }).then(
      (season) => {
        if (!controller.signal.aborted) setResult({ state: "ready", season });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message =
          error instanceof SeasonError
            ? error.message
            : "Something went wrong loading the season. Try again.";
        setResult({ state: "error", message });
      },
    );
    return () => controller.abort();
  }, [apiBaseUrl, attempt, load]);

  const retry = () => {
    setResult({ state: "loading" });
    setAttempt((n) => n + 1);
  };

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-5 px-4 py-5 pb-[max(1.25rem,env(safe-area-inset-bottom))]">
        {result.state === "loading" && (
          <p role="status" className="text-soft">
            Loading the standings…
          </p>
        )}
        {result.state === "error" && (
          <div
            role="alert"
            className="flex flex-wrap items-center gap-3 rounded-md border border-danger-line bg-danger-bg px-4 py-3 text-danger-text"
          >
            <span>{result.message}</span>
            {apiBaseUrl && (
              <button
                type="button"
                onClick={retry}
                className="rounded-md border border-control px-3 py-1 text-sm text-soft hover:border-foreground hover:text-foreground"
              >
                Retry
              </button>
            )}
          </div>
        )}
        {result.state === "ready" && (
          <Season season={result.season} now={now} timeZone={timeZone} />
        )}
      </div>
    </div>
  );
}

function Season({
  season,
  now,
  timeZone,
}: {
  season: SeasonSnapshot;
  now: () => number;
  timeZone?: string;
}) {
  const progress = season.complete
    ? "Final standings"
    : season.round && season.total_rounds
      ? `Standings after round ${season.round} of ${season.total_rounds}`
      : "Standings";

  return (
    <>
      <div className="flex flex-col gap-0.5">
        <h1 className="text-xl font-bold">{season.season} season</h1>
        <p className="text-muted">{progress}</p>
        {season.stale && (
          <p
            role="status"
            className="mt-2 rounded-md border border-warning/40 bg-warning-bg px-3 py-2 text-warning-text"
          >
            The live data source can&apos;t be reached, so these standings may be out of
            date. Last updated {formatSessionTime(season.fetched_at, { timeZone })}.
          </p>
        )}
      </div>

      {season.next_race ? (
        <NextRaceView
          race={season.next_race}
          standingsSeason={season.season}
          now={now}
          timeZone={timeZone}
        />
      ) : (
        <p className="rounded-lg bg-surface px-4 py-3 text-soft">
          The {season.season + 1} calendar isn&apos;t published yet. The next race appears
          here once it is.
        </p>
      )}

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-[3fr_2fr]">
        <DriversStandings rows={season.drivers} />
        <ConstructorsStandings rows={season.constructors} />
      </div>

      <p className="text-xs text-muted">
        Data from the Jolpica-F1 API, refreshed every 10 minutes. The chat&apos;s own data
        covers 1950 to 2025.
      </p>
    </>
  );
}

// --- the next race ---------------------------------------------------------------------

/** Re-renders every second while mounted, for the countdown. */
function useClock(now: () => number): number {
  const [time, setTime] = useState(now);
  useEffect(() => {
    const timer = setInterval(() => setTime(now()), 1000);
    return () => clearInterval(timer);
  }, [now]);
  return time;
}

const pad = (n: number) => String(n).padStart(2, "0");

/** One boxed countdown figure, as on the F1 app: "02" over "days". */
function CountdownBox({ value, unit }: { value: string; unit: string }) {
  return (
    <span className="flex w-14 flex-col items-center rounded-md bg-raised py-1.5">
      <span className="text-2xl leading-none font-bold tabular-nums">{value}</span>
      <span className="mt-1 text-[0.7rem] font-semibold tracking-wide text-muted uppercase">
        {unit}
      </span>
    </span>
  );
}

function NextRaceView({
  race,
  standingsSeason,
  now,
  timeZone,
}: {
  race: NextRace;
  standingsSeason: number;
  now: () => number;
  timeZone?: string;
}) {
  const time = useClock(now);
  const left = race.start ? countdown(race.start, time) : null;
  const when = (start: string | null, date: string) =>
    start ? formatSessionTime(start, { timeZone }) : formatSessionDate(date);
  // The first session still to start: marked as next.
  const nextSession = race.sessions.find(
    (s) => s.start !== null && Date.parse(s.start) > time,
  );
  const opener = race.season > standingsSeason;

  return (
    <section
      aria-labelledby="next-race"
      className="grid grid-cols-1 gap-4 rounded-lg border-l-4 border-accent bg-surface p-4 lg:grid-cols-[3fr_2fr] lg:gap-6"
    >
      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-0.5">
          <p className="text-xs font-semibold tracking-wide text-accent-text uppercase">
            {opener ? `Opening race of the ${race.season} season` : "Next race"}, round{" "}
            {race.round}
          </p>
          <h2 id="next-race" className="text-lg leading-tight font-bold">
            {race.name}
          </h2>
          <p className="text-muted">
            {race.circuit.name}, {race.circuit.locality}, {race.circuit.country}
          </p>
        </div>

        {race.start === null ? (
          <p className="text-soft">
            Race on {formatSessionDate(race.date)}; start time to be confirmed.
          </p>
        ) : left ? (
          <div className="flex flex-col gap-1.5">
            <p className="flex gap-1.5" aria-hidden="true" data-testid="countdown">
              <CountdownBox value={pad(left.days)} unit="days" />
              <CountdownBox value={pad(left.hours)} unit="hrs" />
              <CountdownBox value={pad(left.minutes)} unit="mins" />
              <CountdownBox value={pad(left.seconds)} unit="secs" />
            </p>
            <p className="text-muted">
              until the race starts, {formatSessionTime(race.start, { timeZone })}
            </p>
          </div>
        ) : (
          <p className="font-semibold">
            The race is under way. Results appear here after the finish.
          </p>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <table className="w-full border-collapse">
          <caption className="sr-only">The {race.name} weekend</caption>
          <tbody>
            {race.sessions.map((s) => {
              const isNext = s === nextSession;
              const past = s.start !== null && Date.parse(s.start) <= time;
              return (
                <tr
                  key={s.kind}
                  className={`border-b border-line last:border-b-0 ${past ? "text-muted" : "text-foreground"}`}
                >
                  <th scope="row" className="py-1.5 pr-4 text-left font-semibold">
                    <span className="flex items-center gap-2">
                      {/* The next session: a red dot. */}
                      <span
                        aria-hidden="true"
                        className={`h-1.5 w-1.5 shrink-0 rounded-full ${isNext ? "bg-accent" : "bg-transparent"}`}
                      />
                      {SESSION_NAMES[s.kind]}
                      {isNext && <span className="sr-only"> (next)</span>}
                    </span>
                  </th>
                  <td className="py-1.5 text-right tabular-nums">
                    {when(s.start, s.date)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        <p className="text-xs text-muted">Times in {timeZone ?? localTimeZone()}.</p>
      </div>
    </section>
  );
}

// --- the standings ------------------------------------------------------------------

function TeamBar({ colour }: { colour: string }) {
  return (
    <span
      aria-hidden="true"
      className="h-5 w-1 shrink-0 rounded-sm"
      style={{ backgroundColor: colour }}
    />
  );
}

// Rows are separate cards (a table with spaced rows), like the F1 app.
const table = "w-full border-separate border-spacing-y-1";
const th = "px-2 pb-0.5 text-xs font-semibold tracking-wide text-muted uppercase";
const cell = "bg-surface px-2 py-2 tabular-nums first:rounded-l-md last:rounded-r-md";

function Heading({ id, children }: { id: string; children: string }) {
  return (
    <h2 id={id} className="mb-1 text-base font-bold">
      {children}
    </h2>
  );
}

function DriversStandings({ rows }: { rows: DriverRow[] }) {
  const leader = rows[0]?.points ?? 0;
  return (
    <section aria-labelledby="drivers" className="min-w-0">
      <Heading id="drivers">Drivers</Heading>
      {rows.length === 0 ? (
        <p className="text-muted">No results yet.</p>
      ) : (
        <table className={table}>
          <thead>
            <tr>
              <th scope="col" className={`${th} w-8 text-right`}>
                <abbr title="Position" className="no-underline">
                  Pos
                </abbr>
              </th>
              <th scope="col" className={`${th} text-left`}>
                Driver
              </th>
              <th scope="col" className={`${th} hidden text-right sm:table-cell`}>
                Wins
              </th>
              <th scope="col" className={`${th} text-right`}>
                Gap
              </th>
              <th scope="col" className={`${th} text-right`}>
                <abbr title="Points" className="no-underline">
                  Pts
                </abbr>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.driver_id}>
                <td className={`${cell} text-right font-bold`}>{d.position_text}</td>
                <td className={`${cell} w-full`}>
                  <span className="flex items-center gap-2.5">
                    <TeamBar colour={teamColour(d.team_id)} />
                    <span className="flex min-w-0 flex-col leading-tight sm:flex-row sm:items-baseline sm:gap-2">
                      <span className="truncate">
                        <span className="text-soft">{d.given_name}</span>{" "}
                        <span className="font-bold uppercase">{d.family_name}</span>
                      </span>
                      {d.team && (
                        <span className="truncate text-xs text-muted">{d.team}</span>
                      )}
                    </span>
                  </span>
                </td>
                <td className={`${cell} hidden text-right text-soft sm:table-cell`}>
                  {d.wins}
                </td>
                <td className={`${cell} text-right whitespace-nowrap text-muted`}>
                  {gapToLeader(d.points, leader)}
                </td>
                <td className={`${cell} text-right font-bold`}>
                  {formatPoints(d.points)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

function ConstructorsStandings({ rows }: { rows: ConstructorRow[] }) {
  const leader = rows[0]?.points ?? 0;
  return (
    <section aria-labelledby="constructors" className="min-w-0">
      <Heading id="constructors">Constructors</Heading>
      {rows.length === 0 ? (
        <p className="text-muted">No results yet.</p>
      ) : (
        <table className={table}>
          <thead>
            <tr>
              <th scope="col" className={`${th} w-8 text-right`}>
                <abbr title="Position" className="no-underline">
                  Pos
                </abbr>
              </th>
              <th scope="col" className={`${th} text-left`}>
                Team
              </th>
              <th scope="col" className={`${th} hidden text-right sm:table-cell`}>
                Wins
              </th>
              <th scope="col" className={`${th} text-right`}>
                Gap
              </th>
              <th scope="col" className={`${th} text-right`}>
                <abbr title="Points" className="no-underline">
                  Pts
                </abbr>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.constructor_id}>
                <td className={`${cell} text-right font-bold`}>{c.position_text}</td>
                <td className={`${cell} w-full`}>
                  <span className="flex items-center gap-2.5">
                    <TeamBar colour={teamColour(c.constructor_id)} />
                    <span className="truncate font-bold">{c.name}</span>
                  </span>
                </td>
                <td className={`${cell} hidden text-right text-soft sm:table-cell`}>
                  {c.wins}
                </td>
                <td className={`${cell} text-right whitespace-nowrap text-muted`}>
                  {gapToLeader(c.points, leader)}
                </td>
                <td className={`${cell} text-right font-bold`}>
                  {formatPoints(c.points)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
