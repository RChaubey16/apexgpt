import { BackendStatus } from "@/components/BackendStatus";
import { ChatApp } from "@/components/ChatApp";
import { ConfigError, getApiBaseUrl } from "@/lib/config";

function resolveApiBaseUrl(): string | null {
  try {
    return getApiBaseUrl();
  } catch (error) {
    if (error instanceof ConfigError) {
      // Logged at build/render on the server; the UI shows a generic message.
      console.error(`[config] ${error.message}`);
      return null;
    }
    throw error;
  }
}

export default function Home() {
  const apiBaseUrl = resolveApiBaseUrl();

  return (
    <main className="flex h-dvh flex-col overflow-hidden">
      <header className="shrink-0 bg-surface pt-[env(safe-area-inset-top)]">
        <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-2 px-4 py-2.5 pl-[max(1rem,env(safe-area-inset-left))] pr-[max(1rem,env(safe-area-inset-right))]">
          <div className="flex items-center gap-3">
            <span className="speed-stripes h-5 w-7 -skew-x-12" aria-hidden="true" />
            <h1 className="text-xl font-black italic tracking-tight uppercase">
              Apex<span className="text-accent-text">GPT</span>
            </h1>
            <p className="hidden border-l border-line pl-3 text-xs font-semibold tracking-[0.2em] text-muted uppercase sm:block">
              Formula 1 · 1950–2025
            </p>
          </div>
          {/* Calls /health/ready on load, which also wakes a suspended database. */}
          <BackendStatus apiBaseUrl={apiBaseUrl} />
        </div>
        <div className="checkered h-1.5 opacity-80" aria-hidden="true" />
      </header>
      <ChatApp apiBaseUrl={apiBaseUrl} />
    </main>
  );
}
