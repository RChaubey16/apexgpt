"use client";

/**
 * The /season page body (F8.5): the next race, then the drivers' and
 * constructors' standings as two timing towers.
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

import { useCallback, useEffect, useState } from "react";

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
      <div className="mx-auto flex w-full max-w-5xl flex-col gap-8 px-4 py-6 pb-[max(1.5rem,env(safe-area-inset-bottom))] sm:py-8">
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
      <div className="flex flex-col gap-1">
        <h1 className="text-4xl leading-none font-extrabold tracking-tight font-stretch-condensed sm:text-5xl">
          {season.season} season
        </h1>
        <p className="text-soft">{progress}</p>
        {season.stale && (
          <p
            role="status"
            className="mt-2 rounded-md border border-warning/40 bg-warning-bg px-3 py-2 text-sm text-warning-text"
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
        <p className="text-soft">
          The {season.season + 1} calendar isn&apos;t published yet. The next race appears
          here once it is.
        </p>
      )}

      <div className="grid grid-cols-1 gap-8 lg:grid-cols-[3fr_2fr]">
        <DriversTower rows={season.drivers} />
        <ConstructorsTower rows={season.constructors} />
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
  const when = useCallback(
    (start: string | null, date: string) =>
      start ? formatSessionTime(start, { timeZone }) : formatSessionDate(date),
    [timeZone],
  );
  // The first session still to start: marked as next.
  const nextSession = race.sessions.find(
    (s) => s.start !== null && Date.parse(s.start) > time,
  );
  const opener = race.season > standingsSeason;

  return (
    // The same 3:2 columns as the towers below: the race and its countdown
    // over the drivers, the weekend's sessions over the constructors.
    <section
      aria-labelledby="next-race"
      className="grid grid-cols-1 items-start gap-6 lg:grid-cols-[3fr_2fr] lg:gap-8"
    >
      <div className="flex flex-col gap-4">
        <div className="flex flex-col gap-1">
          <p className="text-soft">
            {opener ? `Opening race of the ${race.season} season` : "Next race"}, round{" "}
            {race.round}
          </p>
          <h2
            id="next-race"
            className="text-3xl leading-tight font-bold tracking-tight font-stretch-condensed"
          >
            {race.name}
          </h2>
          <p className="text-soft">
            {race.circuit.name}, {race.circuit.locality}, {race.circuit.country}
          </p>
        </div>

        <div className="flex flex-col gap-1">
          {race.start === null ? (
            <p className="text-lg text-soft">
              Race on {formatSessionDate(race.date)}; start time to be confirmed.
            </p>
          ) : left ? (
            <>
              <p
                className="text-4xl leading-none font-bold tabular-nums font-stretch-condensed sm:text-5xl"
                aria-hidden="true"
                data-testid="countdown"
              >
                {left.days}d {pad(left.hours)}h {pad(left.minutes)}m {pad(left.seconds)}s
              </p>
              <p className="text-soft">
                until the race starts, {formatSessionTime(race.start, { timeZone })}
              </p>
            </>
          ) : (
            <p className="text-lg font-semibold">
              The race is under way. Results appear here after the finish.
            </p>
          )}
        </div>
      </div>
      <div className="flex flex-col gap-2">
        <table className="w-full border-collapse text-sm sm:text-base">
          <caption className="sr-only">The {race.name} weekend</caption>
          <tbody>
            {race.sessions.map((s) => {
              const isNext = s === nextSession;
              const past = s.start !== null && Date.parse(s.start) <= time;
              return (
                <tr
                  key={s.kind}
                  className={`border-b border-line ${past ? "text-muted" : "text-foreground"}`}
                >
                  <th scope="row" className="py-2 pr-4 text-left font-semibold">
                    <span className="flex items-center gap-2">
                      {/* The next session: a yellow ring, the medium compound. */}
                      <span
                        aria-hidden="true"
                        className={`h-2.5 w-2.5 shrink-0 rounded-full border-2 ${isNext ? "border-warning" : "border-transparent"}`}
                      />
                      {SESSION_NAMES[s.kind]}
                      {isNext && <span className="sr-only"> (next)</span>}
                    </span>
                  </th>
                  <td className="py-2 text-right">{when(s.start, s.date)}</td>
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

// --- the towers ---------------------------------------------------------------------

function Stripe({ colour }: { colour: string }) {
  return (
    <span
      aria-hidden="true"
      className="h-6 w-1 shrink-0 rounded-sm"
      style={{ backgroundColor: colour }}
    />
  );
}

const th = "py-2 text-sm font-semibold text-soft font-stretch-condensed";
const td = "py-2 tabular-nums";

function DriversTower({ rows }: { rows: DriverRow[] }) {
  const leader = rows[0]?.points ?? 0;
  return (
    <section aria-labelledby="drivers" className="min-w-0">
      <h2
        id="drivers"
        className="mb-2 text-2xl font-bold tracking-tight font-stretch-condensed"
      >
        Drivers
      </h2>
      {rows.length === 0 ? (
        <p className="text-soft">No results yet.</p>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-control">
              <th scope="col" className={`${th} w-10 text-right`}>
                <abbr title="Position" className="no-underline">
                  Pos
                </abbr>
              </th>
              <th scope="col" className={`${th} pl-4 text-left`}>
                Driver
              </th>
              <th scope="col" className={`${th} hidden text-right sm:table-cell`}>
                Wins
              </th>
              <th scope="col" className={`${th} pl-3 text-right`}>
                Gap
              </th>
              <th scope="col" className={`${th} pl-3 text-right`}>
                Points
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.driver_id} className="border-b border-line">
                <td className={`${td} text-right font-semibold`}>{d.position_text}</td>
                <td className="py-1.5 pl-4">
                  <span className="flex items-center gap-3">
                    <Stripe colour={teamColour(d.team_id)} />
                    <span className="flex min-w-0 flex-col">
                      <span className="truncate">
                        <span className="text-soft">{d.given_name}</span>{" "}
                        <span className="font-semibold">{d.family_name}</span>
                      </span>
                      {d.team && (
                        <span className="truncate text-xs text-muted">{d.team}</span>
                      )}
                    </span>
                  </span>
                </td>
                <td className={`${td} hidden text-right text-soft sm:table-cell`}>
                  {d.wins}
                </td>
                <td className={`${td} pl-3 text-right text-soft`}>
                  {gapToLeader(d.points, leader)}
                </td>
                <td className={`${td} pl-3 text-right font-semibold`}>
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

function ConstructorsTower({ rows }: { rows: ConstructorRow[] }) {
  const leader = rows[0]?.points ?? 0;
  return (
    <section aria-labelledby="constructors" className="min-w-0">
      <h2
        id="constructors"
        className="mb-2 text-2xl font-bold tracking-tight font-stretch-condensed"
      >
        Constructors
      </h2>
      {rows.length === 0 ? (
        <p className="text-soft">No results yet.</p>
      ) : (
        <table className="w-full border-collapse">
          <thead>
            <tr className="border-b border-control">
              <th scope="col" className={`${th} w-10 text-right`}>
                <abbr title="Position" className="no-underline">
                  Pos
                </abbr>
              </th>
              <th scope="col" className={`${th} pl-4 text-left`}>
                Team
              </th>
              <th scope="col" className={`${th} hidden text-right sm:table-cell`}>
                Wins
              </th>
              <th scope="col" className={`${th} pl-3 text-right`}>
                Gap
              </th>
              <th scope="col" className={`${th} pl-3 text-right`}>
                Points
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.constructor_id} className="border-b border-line">
                <td className={`${td} text-right font-semibold`}>{c.position_text}</td>
                <td className="py-2.5 pl-4">
                  <span className="flex items-center gap-3">
                    <Stripe colour={teamColour(c.constructor_id)} />
                    <span className="truncate font-semibold">{c.name}</span>
                  </span>
                </td>
                <td className={`${td} hidden text-right text-soft sm:table-cell`}>
                  {c.wins}
                </td>
                <td className={`${td} pl-3 text-right text-soft`}>
                  {gapToLeader(c.points, leader)}
                </td>
                <td className={`${td} pl-3 text-right font-semibold`}>
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
