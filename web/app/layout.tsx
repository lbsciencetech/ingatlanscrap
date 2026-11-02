import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Flat finder",
  description: "Plain-language ingatlan.com search via MCP sampling",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
