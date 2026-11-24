import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import type { Source, Table } from "@/lib/chat";

import { AnswerContent, cellText, columnLabel, linkCitations } from "./AnswerContent";

const S1: Source = {
  id: "S1",
  title: "2021 Abu Dhabi Grand Prix",
  url: "https://en.wikipedia.org/wiki/2021_Abu_Dhabi_Grand_Prix",
  section: "Race",
  season: 2021,
};
const S3: Source = {
  id: "S3",
  title: "Michael Masi",
  url: "https://en.wikipedia.org/wiki/Michael_Masi",
  section: null,
  season: null,
};
const TABLE: Table = {
  columns: ["driver_name", "monza_wins"],
  rows: [
    ["Lewis Hamilton", 5],
    ["Michael Schumacher", 5],
  ],
};

function show(
  text: string,
  { citations = [] as Source[], tables = [] as Table[], complete = true } = {},
) {
  return render(
    <AnswerContent
      text={text}
      citations={citations}
      tables={tables}
      complete={complete}
    />,
  );
}

describe("AnswerContent", () => {
  it("renders markdown", () => {
    show("**Verstappen** won.\n\n- Latifi crashed\n- Safety car\n\n1. one\n2. two");

    expect(screen.getByText("Verstappen").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(4);
  });

  it("renders the model's GFM table, scrollable", () => {
    show(
      "| Driver | Monza wins |\n|---|---|\n| Lewis Hamilton | 5 |\n| Michael Schumacher | 5 |",
    );

    const table = screen.getByRole("table");
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Driver", "Monza wins"]);
    expect(within(table).getAllByRole("row")).toHaveLength(3);
    expect(table.parentElement).toHaveClass("overflow-x-auto");
  });

  it("turns known citation markers into chips linking to the source", () => {
    show("Verstappen passed on the last lap [S1][S3].", { citations: [S1, S3] });

    const chip = screen.getByRole("link", {
      name: "Source 1: 2021 Abu Dhabi Grand Prix › Race",
    });
    expect(chip).toHaveAttribute("href", S1.url);
    expect(chip).toHaveAttribute("target", "_blank");
    expect(chip).toHaveAttribute("rel", "noopener noreferrer");
    expect(chip).toHaveTextContent("1");
    expect(
      screen.getByRole("link", { name: "Source 3: Michael Masi" }),
    ).toBeInTheDocument();
    expect(screen.getByTestId("answer-text")).not.toHaveTextContent("[S1]");
  });

  it("leaves a marker the backend never sent as text", () => {
    show("Fact [S9].", { citations: [S1] });

    expect(screen.getByTestId("answer-text")).toHaveTextContent("Fact [S9].");
    expect(screen.queryByRole("link", { name: /Source 9/ })).not.toBeInTheDocument();
  });

  it("shows a marker as text while its citation event hasn't arrived yet", () => {
    const { rerender } = show("Fact [S1].", { complete: false });
    expect(screen.getByTestId("answer-text")).toHaveTextContent("Fact [S1].");

    rerender(
      <AnswerContent text="Fact [S1]." citations={[S1]} tables={[]} complete={false} />,
    );

    expect(screen.getByRole("link", { name: /Source 1/ })).toBeInTheDocument();
  });

  it("lists the cited sources once the answer is complete", () => {
    const { rerender } = show("A [S1] B [S3].", { citations: [S1, S3], complete: false });
    expect(screen.queryByRole("region", { name: "Sources" })).not.toBeInTheDocument();

    rerender(
      <AnswerContent text="A [S1] B [S3]." citations={[S1, S3]} tables={[]} complete />,
    );

    const sources = screen.getByRole("region", { name: "Sources" });
    const links = within(sources).getAllByRole("link");
    expect(links.map((l) => [l.textContent, l.getAttribute("href")])).toEqual([
      ["2021 Abu Dhabi Grand Prix › Race", S1.url],
      ["Michael Masi", S3.url],
    ]);
    expect(sources).toHaveTextContent("CC BY-SA 4.0");
  });

  it("puts the exact stats rows behind a disclosure", async () => {
    const user = userEvent.setup();
    show("Hamilton and Schumacher, 5 each.", {
      tables: [TABLE, { ...TABLE, note: "first 50 rows" }],
    });

    const summary = screen.getByText("Show the data (4 rows from the stats database)");
    const details = summary.closest("details")!;
    expect(details).not.toHaveAttribute("open");

    await user.click(summary);

    expect(details).toHaveAttribute("open");
    const tables = within(details).getAllByRole("table");
    expect(tables).toHaveLength(2);
    expect(
      within(tables[0])
        .getAllByRole("columnheader")
        .map((h) => h.textContent),
    ).toEqual(["Driver name", "Monza wins"]);
    expect(within(details).getByText("first 50 rows")).toBeInTheDocument();
  });

  it("says 1 row, and shows no data or sources while streaming", () => {
    const { rerender } = show("x", {
      tables: [{ columns: ["a"], rows: [[1]] }],
      complete: false,
    });
    expect(screen.queryByText(/Show the data/)).not.toBeInTheDocument();

    rerender(
      <AnswerContent
        text="x"
        citations={[]}
        tables={[{ columns: ["a"], rows: [[1]] }]}
        complete
      />,
    );

    expect(
      screen.getByText("Show the data (1 row from the stats database)"),
    ).toBeInTheDocument();
  });

  describe("safety", () => {
    it("never renders raw HTML", () => {
      const { container } = show(
        'Hi <img src=x onerror="alert(1)"> <script>alert(1)</script> <b>bold</b>',
      );

      expect(container.querySelector("img, script, b")).toBeNull();
    });

    it("drops javascript: and data: links", () => {
      show(
        "[click](javascript:alert(1)) and [img](data:text/html,<script>alert(1)</script>)",
      );

      for (const link of screen.queryAllByRole("link")) {
        expect(link.getAttribute("href") ?? "").not.toMatch(/^(javascript|data):/i);
      }
    });

    it("opens external links in a new tab without the opener", () => {
      show("See [Wikipedia](https://en.wikipedia.org/wiki/Formula_One).");

      const link = screen.getByRole("link", { name: "Wikipedia" });
      expect(link).toHaveAttribute("target", "_blank");
      expect(link).toHaveAttribute("rel", "noopener noreferrer nofollow");
    });

    it("doesn't let the text forge a citation chip", () => {
      show("[S1](cite:S1) and [evil](cite:S9)", { citations: [] });

      expect(screen.queryAllByRole("link")).toHaveLength(0);
      expect(screen.getByTestId("answer-text")).toHaveTextContent("S1 and evil");
    });
  });

  it("renders a real answer (Abu Dhabi 2021, after citation clean-up)", () => {
    const text = [
      "**The 2021 Abu Dhabi Grand Prix decided the title.**",
      "",
      "| Season | Champion | Points |",
      "|---|---|---|",
      "| 2021 | Max Verstappen | 395.5 |",
      "",
      "**Key events**",
      "",
      "- Both entered on 369.5 points [S1].",
      "- A late safety car after Latifi's crash [S1][S3].",
    ].join("\n");

    show(text, { citations: [S1, S3], tables: [TABLE] });

    expect(screen.getAllByRole("table")).toHaveLength(2); // the model's + the hidden data
    expect(screen.getAllByRole("link", { name: /Source 1/ })).toHaveLength(2);
    expect(screen.getByRole("link", { name: /Source 3/ })).toBeInTheDocument();
  });
});

describe("helpers", () => {
  it("links only known, not-already-linked markers", () => {
    expect(linkCitations("a [S1] b [S2] c [S1](x)", new Set(["S1"]))).toBe(
      "a [S1](cite:S1) b [S2] c [S1](x)",
    );
  });

  it("labels columns", () => {
    expect(columnLabel("driver_name")).toBe("Driver name");
    expect(columnLabel("wins")).toBe("Wins");
  });

  it("formats cells", () => {
    expect(cellText(null)).toBe("—");
    expect(cellText(1566)).toBe("1,566");
    expect(cellText(395.5)).toBe("395.5");
    expect(cellText(true)).toBe("yes");
    expect(cellText("Senna")).toBe("Senna");
    expect(cellText({ a: 1 })).toBe('{"a":1}');
  });
});
