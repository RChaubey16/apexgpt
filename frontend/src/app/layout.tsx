import type { Metadata, Viewport } from "next";
import { Geist_Mono, Titillium_Web } from "next/font/google";
import { getSiteUrl } from "@/lib/config";
import { siteMetadata } from "@/lib/metadata";

import "./globals.css";

// Compact and sporty, in the spirit of F1 broadcast graphics (F8.6).
const titillium = Titillium_Web({
  variable: "--font-titillium",
  subsets: ["latin"],
  weight: ["400", "600", "700"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Title template, description, share cards (F8.2); see src/lib/metadata.ts.
export const metadata: Metadata = siteMetadata(getSiteUrl());

export const viewport: Viewport = {
  // Matches --color-background, so the phone's browser bar blends in.
  themeColor: "#14141c",
  colorScheme: "dark",
  // Lay out under the notch/home bar; the composer pads itself clear of it.
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${titillium.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
