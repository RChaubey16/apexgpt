import { ChatApp } from "@/components/ChatApp";
import { SiteHeader } from "@/components/SiteHeader";
import { apiBaseUrlOrNull } from "@/lib/config";
import { homeMetadata } from "@/lib/metadata";

export const metadata = homeMetadata;

export default function Home() {
  const apiBaseUrl = apiBaseUrlOrNull();

  return (
    <main className="flex h-dvh flex-col overflow-hidden">
      <SiteHeader current="chat" apiBaseUrl={apiBaseUrl} />
      <ChatApp apiBaseUrl={apiBaseUrl} />
    </main>
  );
}
