import { ChatApp } from "@/components/ChatApp";
import { SiteHeader } from "@/components/SiteHeader";
import { ConfigError, getApiBaseUrl } from "@/lib/config";
import { homeMetadata } from "@/lib/metadata";

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

export const metadata = homeMetadata;

export default function Home() {
  const apiBaseUrl = resolveApiBaseUrl();

  return (
    <main className="flex h-dvh flex-col overflow-hidden">
      <SiteHeader current="chat" apiBaseUrl={apiBaseUrl} />
      <ChatApp apiBaseUrl={apiBaseUrl} />
    </main>
  );
}
