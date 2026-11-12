import { describe, expect, it } from "vitest";

import { ConfigError, parseApiBaseUrl } from "./config";

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
