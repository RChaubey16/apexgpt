/**
 * Validated public config.
 *
 * NEXT_PUBLIC_* values are inlined into the browser bundle at BUILD time
 * (`next build`), so the backend URL is a Docker build argument, not a runtime
 * env var. Referencing `process.env.NEXT_PUBLIC_API_URL` literally is required
 * for Next.js to inline it.
 */

export class ConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ConfigError";
  }
}

/** Parse and normalise the backend base URL (http/https, no trailing slash). */
export function parseApiBaseUrl(raw: string | undefined): string {
  const value = raw?.trim();
  if (!value) {
    throw new ConfigError("NEXT_PUBLIC_API_URL is not set");
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError("NEXT_PUBLIC_API_URL is not a valid URL");
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConfigError("NEXT_PUBLIC_API_URL must use http or https");
  }
  if (url.search || url.hash || url.username || url.password) {
    throw new ConfigError(
      "NEXT_PUBLIC_API_URL must not contain credentials, a query or a fragment",
    );
  }

  return url.toString().replace(/\/+$/, "");
}

export function getApiBaseUrl(): string {
  return parseApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);
}
