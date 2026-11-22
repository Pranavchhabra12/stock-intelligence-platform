import "@fontsource/rajdhani/500.css";
import "@fontsource/rajdhani/600.css";
import "@fontsource/rajdhani/700.css";
import "@fontsource/mukta/400.css";
import "@fontsource/mukta/500.css";
import "@fontsource/mukta/600.css";
import "./globals.css";

import type { Metadata, Viewport } from "next";
import Link from "next/link";

import SearchBox from "@/components/SearchBox";

export const metadata: Metadata = {
  title: { default: "Stock Intelligence", template: "%s | Stock Intelligence" },
  description: "Prices, results, filings and AI-rated news tone for companies listed on NSE and BSE.",
};

export const viewport: Viewport = { themeColor: "#ffffff", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en-IN">
      <body>
        <header className="site-header">
          <div className="wrap">
            <Link href="/" className="wordmark">Stock <span>Intelligence</span></Link>
            <div className="header-search"><SearchBox compact /></div>
            <nav aria-label="Site">
              <Link href="/">Companies</Link>
              <Link href="/about">How it works</Link>
            </nav>
          </div>
        </header>
        <main className="wrap">{children}</main>
        <footer className="site-footer">
          <div className="wrap">
            <p>
              An educational research project, not investment advice. Prices are end-of-day and come from third-party
              sources credited on each page. News tone and report summaries are produced by AI and can be wrong; check
              the original before relying on them.
            </p>
            <p>Built with Next.js, FastAPI and Postgres.</p>
          </div>
        </footer>
      </body>
    </html>
  );
}
