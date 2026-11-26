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

/** Parse and normalise a public base URL (http/https, no trailing slash). */
function parseBaseUrl(name: string, raw: string | undefined): string {
  const value = raw?.trim();
  if (!value) {
    throw new ConfigError(`${name} is not set`);
  }

  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new ConfigError(`${name} is not a valid URL`);
  }

  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new ConfigError(`${name} must use http or https`);
  }
  if (url.search || url.hash || url.username || url.password) {
    throw new ConfigError(`${name} must not contain credentials, a query or a fragment`);
  }

  return url.toString().replace(/\/+$/, "");
}

/** Parse and normalise the backend base URL (http/https, no trailing slash). */
export function parseApiBaseUrl(raw: string | undefined): string {
  return parseBaseUrl("NEXT_PUBLIC_API_URL", raw);
}

export function getApiBaseUrl(): string {
  return parseApiBaseUrl(process.env.NEXT_PUBLIC_API_URL);
}

/** Local development's address, used when NEXT_PUBLIC_SITE_URL is unset. */
export const DEFAULT_SITE_URL = "http://localhost:3000";

/**
 * The frontend's own public address (F8.2), for absolute URLs in metadata:
 * the canonical link, share-card images and the sitemap. Optional locally;
 * docker-compose.prod.yml requires it, so production never falls back.
 */
export function parseSiteUrl(raw: string | undefined): string {
  if (!raw?.trim()) {
    return DEFAULT_SITE_URL;
  }
  return parseBaseUrl("NEXT_PUBLIC_SITE_URL", raw);
}

export function getSiteUrl(): string {
  return parseSiteUrl(process.env.NEXT_PUBLIC_SITE_URL);
}
