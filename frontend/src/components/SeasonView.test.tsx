import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SeasonView } from "@/components/SeasonView";
import { SeasonError, type fetchSeason, type SeasonSnapshot } from "@/lib/season";
import { NOW, snapshot } from "@/test/season";

const BASE = "http://backend.test";
const now = () => NOW;

function view(load: typeof fetchSeason, apiBaseUrl: string | null = BASE) {
  return render(
    <SeasonView apiBaseUrl={apiBaseUrl} load={load} now={now} timeZone="UTC" />,
  );
}

const loads = (season: SeasonSnapshot) => vi.fn<typeof fetchSeason>(async () => season);

describe("SeasonView", () => {
  it("shows loading, then the season", async () => {
    const load = loads(snapshot());
    view(load);

    expect(screen.getByRole("status")).toHaveTextContent("Loading the standings…");
    expect(
      await screen.findByRole("heading", { level: 1, name: "2026 season" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Standings after round 21 of 23")).toBeInTheDocument();
    expect(load).toHaveBeenCalledWith(
      BASE,
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("shows the next race: where, a countdown and the sessions in local time", async () => {
    view(loads(snapshot()));

    const race = await screen.findByRole("region", { name: "Qatar Grand Prix" });
    expect(within(race).getByText("Next race, round 22")).toBeInTheDocument();
    expect(
      within(race).getByText("Lusail International Circuit, Lusail, Qatar"),
    ).toBeInTheDocument();
    // NOW is Fri 27 Nov 12:00 UTC; the race starts Sun 29 Nov 16:00 UTC.
    expect(within(race).getByTestId("countdown")).toHaveTextContent(
      "02days04hrs00mins00secs",
    );
    expect(within(race).getByTestId("countdown")).toHaveAttribute("aria-hidden", "true");
    expect(
      within(race).getByText("until the race starts, Sun 29 Nov, 16:00"),
    ).toBeInTheDocument();

    const rows = within(race).getAllByRole("row");
    expect(rows.map((r) => r.textContent)).toEqual([
      "Practice 1Fri 27 Nov, 10:30",
      "Qualifying (next)Sat 28 Nov, 18:00",
      "RaceSun 29 Nov, 16:00",
    ]);
    expect(within(race).getByText("Times in UTC.")).toBeInTheDocument();
  });

  it("lists the drivers as a tower: position, name, team, gap and points", async () => {
    view(loads(snapshot()));

    const drivers = await screen.findByRole("region", { name: "Drivers" });
    const [, leader, second, newcomer] = within(drivers).getAllByRole("row");
    expect(leader).toHaveTextContent("1Andrea Kimi AntonelliMercedes9Leader402");
    expect(second).toHaveTextContent("2Max VerstappenRed Bull4−97.5304.5");
    expect(newcomer).toHaveTextContent("3New DriverNew Team0−390");
  });

  it("gives each row its team's stripe, neutral for an unknown team", async () => {
    const { container } = view(loads(snapshot()));
    await screen.findByRole("region", { name: "Drivers" });

    const stripes = [
      ...container.querySelectorAll<HTMLElement>(
        "section[aria-labelledby=drivers] tbody [style]",
      ),
    ].map((s) => s.style.backgroundColor);
    expect(stripes).toEqual([
      "rgb(39, 244, 210)",
      "rgb(54, 113, 198)",
      "rgb(110, 122, 138)",
    ]);
  });

  it("lists the constructors with their gaps", async () => {
    view(loads(snapshot()));

    const teams = await screen.findByRole("region", { name: "Constructors" });
    const [, first, second] = within(teams).getAllByRole("row");
    expect(first).toHaveTextContent("1Mercedes12Leader666");
    expect(second).toHaveTextContent("2Ferrari2−149517");
  });

  it("says when the race is under way", async () => {
    const race = snapshot().next_race!;
    render(
      <SeasonView
        apiBaseUrl={BASE}
        load={loads(snapshot())}
        now={() => Date.parse(race.start!) + 60_000}
        timeZone="UTC"
      />,
    );

    expect(await screen.findByText(/The race is under way/)).toBeInTheDocument();
    expect(screen.queryByTestId("countdown")).not.toBeInTheDocument();
  });

  it("handles a race whose start time isn't published", async () => {
    const race = snapshot().next_race!;
    view(
      loads(
        snapshot({
          next_race: {
            ...race,
            start: null,
            sessions: [{ kind: "race", date: race.date, start: null }],
          },
        }),
      ),
    );

    expect(
      await screen.findByText("Race on Sun 29 Nov; start time to be confirmed."),
    ).toBeInTheDocument();
  });

  it("shows the final standings and the next season's opener", async () => {
    const race = snapshot().next_race!;
    view(
      loads(
        snapshot({
          complete: true,
          round: 23,
          next_race: { ...race, season: 2027, round: 1, name: "Australian Grand Prix" },
        }),
      ),
    );

    expect(await screen.findByText("Final standings")).toBeInTheDocument();
    expect(
      screen.getByText("Opening race of the 2027 season, round 1"),
    ).toBeInTheDocument();
  });

  it("says when the next calendar isn't out", async () => {
    view(loads(snapshot({ complete: true, next_race: null })));

    expect(
      await screen.findByText(/The 2027 calendar isn't published yet/),
    ).toBeInTheDocument();
  });

  it("warns when the standings may be out of date", async () => {
    view(loads(snapshot({ stale: true })));

    const note = await screen.findByText(/may be out of date/);
    expect(note).toHaveAttribute("role", "status");
    expect(note).toHaveTextContent("Last updated Fri 27 Nov, 11:55.");
  });

  it("says when a season has no results yet", async () => {
    view(loads(snapshot({ drivers: [], constructors: [] })));

    await screen.findByRole("region", { name: "Drivers" });
    expect(screen.getAllByText("No results yet.")).toHaveLength(2);
  });

  it("shows the error and retries", async () => {
    const user = userEvent.setup();
    const load = vi
      .fn<typeof fetchSeason>()
      .mockRejectedValueOnce(new SeasonError("The current season's data is unavailable"))
      .mockResolvedValueOnce(snapshot());
    view(load);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The current season's data is unavailable",
    );
    await user.click(screen.getByRole("button", { name: "Retry" }));
    expect(
      await screen.findByRole("heading", { name: "2026 season" }),
    ).toBeInTheDocument();
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("never shows an unexpected error's details", async () => {
    view(
      vi.fn<typeof fetchSeason>().mockRejectedValue(new Error("TypeError at line 42")),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Something went wrong loading the season");
    expect(alert).not.toHaveTextContent("line 42");
  });

  it("explains a misconfigured page without fetching or offering Retry", () => {
    const load = loads(snapshot());
    view(load, null);

    expect(screen.getByRole("alert")).toHaveTextContent("misconfigured");
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
    expect(load).not.toHaveBeenCalled();
  });

  it("announces decided champions and tags their rows (F8.7)", async () => {
    view(
      loads(
        snapshot({ champions: { driver_id: "antonelli", constructor_id: "mercedes" } }),
      ),
    );

    expect(
      await screen.findByText(
        "Andrea Kimi Antonelli and Mercedes are the 2026 world champions.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Champions decided")).toBeInTheDocument();
    const drivers = screen.getByRole("region", { name: "Drivers" });
    const teams = screen.getByRole("region", { name: "Constructors" });
    expect(within(drivers).getAllByText("Champion")).toHaveLength(1);
    expect(within(drivers).getAllByRole("row")[1]).toHaveTextContent("Champion");
    expect(within(teams).getAllByRole("row")[1]).toHaveTextContent("Champion");
  });

  it("says just 'Champions' once the season is over", async () => {
    view(
      loads(
        snapshot({
          complete: true,
          next_race: null,
          champions: { driver_id: "antonelli", constructor_id: "mercedes" },
        }),
      ),
    );

    expect(await screen.findByText("Champions")).toBeInTheDocument();
  });

  it("shows no champions while both titles are open", async () => {
    view(loads(snapshot()));

    await screen.findByRole("region", { name: "Drivers" });
    expect(screen.queryByText(/world champion/)).not.toBeInTheDocument();
    expect(screen.queryByText("Champion")).not.toBeInTheDocument();
  });
});
