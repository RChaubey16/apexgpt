import { describe, expect, it } from "vitest";

import { ConfigError, DEFAULT_SITE_URL, parseApiBaseUrl, parseSiteUrl } from "./config";

describe("parseApiBaseUrl", () => {
  it.each([
    ["http://localhost:8000", "http://localhost:8000"],
    ["http://localhost:8000/", "http://localhost:8000"],
    ["  https://api.apexgpt.app  ", "https://api.apexgpt.app"],
    ["https://apexgpt.app/backend/", "https://apexgpt.app/backend"],
  ])("accepts %j", (raw, expected) => {
    expect(parseApiBaseUrl(raw)).toBe(expected);
  });

  it.each([
    [undefined, "not set"],
    ["", "not set"],
    ["   ", "not set"],
    ["not a url", "not a valid URL"],
    ["ftp://example.com", "http or https"],
    ["javascript:alert(1)", "http or https"],
    ["https://user:pw@api.example.com", "credentials"],
    ["https://api.example.com?x=1", "query"],
    ["https://api.example.com#frag", "fragment"],
  ])("rejects %j", (raw, message) => {
    expect(() => parseApiBaseUrl(raw)).toThrow(ConfigError);
    expect(() => parseApiBaseUrl(raw)).toThrow(message);
  });
});

describe("parseSiteUrl", () => {
  it.each([undefined, "", "   "])("falls back to local development for %j", (raw) => {
    expect(parseSiteUrl(raw)).toBe(DEFAULT_SITE_URL);
  });

  it("normalises a production URL", () => {
    expect(parseSiteUrl(" https://apexgpt.example.com/ ")).toBe(
      "https://apexgpt.example.com",
    );
  });

  it.each([
    ["apexgpt.example.com", "is not a valid URL"],
    ["ftp://apexgpt.example.com", "must use http or https"],
    ["https://user:pw@apexgpt.example.com", "must not contain credentials"],
    ["https://apexgpt.example.com/?ref=x", "must not contain credentials, a query"],
  ])("rejects %s", (raw, message) => {
    expect(() => parseSiteUrl(raw)).toThrow(ConfigError);
    expect(() => parseSiteUrl(raw)).toThrow(`NEXT_PUBLIC_SITE_URL ${message}`);
  });
});
