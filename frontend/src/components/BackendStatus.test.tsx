import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api";

import { BackendStatus } from "./BackendStatus";

const BASE = "http://backend.test";

function statusEl() {
  return screen.getByTestId("backend-status");
}

describe("BackendStatus", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("checks readiness on mount and shows ready", async () => {
    const spy = vi.spyOn(api, "checkReadiness").mockResolvedValue("ready");

    render(<BackendStatus apiBaseUrl={BASE} />);

    expect(statusEl()).toHaveAttribute("data-state", "checking");
    await waitFor(() => expect(statusEl()).toHaveAttribute("data-state", "ready"));
    expect(spy).toHaveBeenCalledWith(BASE, expect.any(Object));
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it.each([
    ["database_unavailable", "database is unavailable"],
    ["unreachable", "Can't reach the backend"],
    ["unexpected_response", "unexpected response"],
  ] as const)("shows %s with a retry button", async (state, text) => {
    vi.spyOn(api, "checkReadiness").mockResolvedValue(state);

    render(<BackendStatus apiBaseUrl={BASE} />);

    await waitFor(() => expect(statusEl()).toHaveAttribute("data-state", state));
    expect(statusEl()).toHaveTextContent(text);
    expect(screen.getByRole("button", { name: "Retry" })).toBeInTheDocument();
  });

  it("retries when the button is clicked", async () => {
    const spy = vi
      .spyOn(api, "checkReadiness")
      .mockResolvedValueOnce("database_unavailable")
      .mockResolvedValueOnce("ready");

    render(<BackendStatus apiBaseUrl={BASE} />);
    await waitFor(() =>
      expect(statusEl()).toHaveAttribute("data-state", "database_unavailable"),
    );

    await userEvent.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(statusEl()).toHaveAttribute("data-state", "ready"));
    expect(spy).toHaveBeenCalledTimes(2);
  });

  it("shows misconfigured and never calls the backend without a URL", () => {
    const spy = vi.spyOn(api, "checkReadiness");

    render(<BackendStatus apiBaseUrl={null} />);

    expect(statusEl()).toHaveAttribute("data-state", "misconfigured");
    expect(spy).not.toHaveBeenCalled();
    expect(screen.queryByRole("button", { name: "Retry" })).not.toBeInTheDocument();
  });

  it("is announced to assistive technology", async () => {
    vi.spyOn(api, "checkReadiness").mockResolvedValue("ready");

    render(<BackendStatus apiBaseUrl={BASE} />);

    expect(screen.getByRole("status")).toHaveAttribute("aria-live", "polite");
    await waitFor(() => expect(statusEl()).toHaveAttribute("data-state", "ready"));
  });
});
