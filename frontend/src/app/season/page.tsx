import { SeasonView } from "@/components/SeasonView";
import { SiteHeader } from "@/components/SiteHeader";
import { apiBaseUrlOrNull } from "@/lib/config";
import { seasonMetadata } from "@/lib/metadata";

export const metadata = seasonMetadata;

// /season (F8.5): the current season's standings and next race, loaded in the
// browser from the backend's GET /api/season/current.
export default function SeasonPage() {
  const apiBaseUrl = apiBaseUrlOrNull();

  return (
    <main className="flex h-dvh flex-col overflow-hidden">
      <SiteHeader current="season" apiBaseUrl={apiBaseUrl} />
      <SeasonView apiBaseUrl={apiBaseUrl} />
    </main>
  );
}
