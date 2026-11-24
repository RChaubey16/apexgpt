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
      <header className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-b border-zinc-800 bg-background px-4 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-xl font-bold tracking-tight">
            Apex<span className="text-red-500">GPT</span>
          </h1>
          <p className="hidden text-xs font-semibold uppercase tracking-[0.2em] text-zinc-500 sm:block">
            Formula 1 · 1950–2025
          </p>
        </div>
        {/* Calls /health/ready on load, which also wakes a suspended database. */}
        <BackendStatus apiBaseUrl={apiBaseUrl} />
      </header>
      <ChatApp apiBaseUrl={apiBaseUrl} />
    </main>
  );
}
