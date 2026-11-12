import { BackendStatus } from "@/components/BackendStatus";
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
    <main className="flex flex-1 flex-col items-center justify-center gap-8 px-6 py-24 text-center">
      <div className="flex flex-col items-center gap-3">
        <p className="text-xs font-semibold uppercase tracking-[0.3em] text-red-500">
          Formula 1 · 1950–2025
        </p>
        <h1 className="text-5xl font-bold tracking-tight sm:text-6xl">
          Apex<span className="text-red-500">GPT</span>
        </h1>
        <p className="max-w-md text-base text-zinc-400">
          Ask anything about drivers, constructors, circuits, seasons, rivalries and
          championship battles. Chat is coming soon.
        </p>
      </div>
      <BackendStatus apiBaseUrl={apiBaseUrl} />
    </main>
  );
}
