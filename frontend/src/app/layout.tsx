import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { getSiteUrl } from "@/lib/config";
import { siteMetadata } from "@/lib/metadata";

import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

// Title template, description, share cards (F8.2); see src/lib/metadata.ts.
export const metadata: Metadata = siteMetadata(getSiteUrl());

export const viewport: Viewport = {
  // Matches --color-background, so the phone's browser bar blends in.
  themeColor: "#0b0b0f",
  colorScheme: "dark",
  // Lay out under the notch/home bar; the composer pads itself clear of it.
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
