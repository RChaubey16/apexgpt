/**
 * The header on every page (F8.4a): the logo and wordmark (a link home), the
 * navigation between pages, and the backend status.
 *
 * F1-app styling (F8.6): a compact carbon bar, and tabs with the current
 * one underlined in F1 red.
 */

import Link from "next/link";

import { BackendStatus } from "@/components/BackendStatus";
import { navigation, type NavItem, type PageId } from "@/lib/nav";

interface SiteHeaderProps {
  /** The page being shown, marked as current in the navigation. */
  current: PageId;
  /** Validated backend URL, or null if config is invalid. */
  apiBaseUrl: string | null;
  /** For tests: the pages to list. */
  items?: readonly NavItem[];
}

/** The three-stripe logo (brand/icon.svg), drawn in CSS at text size. */
export function BrandMark({ className = "" }: { className?: string }) {
  return (
    <span
      className={`speed-stripes h-5 w-7 -skew-x-12 ${className}`}
      aria-hidden="true"
    />
  );
}

export function SiteHeader({ current, apiBaseUrl, items }: SiteHeaderProps) {
  const pages = navigation(items);

  return (
    <header className="shrink-0 border-b border-line bg-surface pt-[env(safe-area-inset-top)]">
      <div className="flex flex-wrap items-center gap-x-6 gap-y-1 px-4 py-2 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
        <Link
          href="/"
          className="flex items-center gap-2.5 rounded-sm"
          aria-label="ApexGPT, home"
        >
          <BrandMark />
          <span className="flex items-baseline gap-2.5">
            <span className="text-xl leading-none font-bold">ApexGPT</span>
            <span className="hidden text-xs text-muted sm:inline">
              Formula 1, 1950 to 2025
            </span>
          </span>
        </Link>

        {pages.length > 0 && (
          <nav aria-label="Pages" className="order-last w-full sm:order-none sm:w-auto">
            <ul className="flex gap-1">
              {pages.map((page) => {
                const isCurrent = page.id === current;
                return (
                  <li key={page.id}>
                    <Link
                      href={page.href}
                      aria-current={isCurrent ? "page" : undefined}
                      className={`block border-b-2 px-3 py-1.5 text-sm font-semibold ${
                        isCurrent
                          ? "border-accent text-foreground"
                          : "border-transparent text-muted hover:text-foreground"
                      }`}
                    >
                      {page.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
        )}

        {/* Calls /health/ready on load, which also wakes a suspended database. */}
        <div className="ml-auto">
          <BackendStatus apiBaseUrl={apiBaseUrl} />
        </div>
      </div>
    </header>
  );
}
