import { ImageResponse } from "next/og";

import { api, type SentimentHistory, type Summary } from "@/lib/api";
import { plain, signed } from "@/lib/format";
import { C, DISPLAY, fonts, Strip, TEXT, Wordmark } from "@/og/card";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Company price and 30-day news tone";
export const revalidate = 3600;

export default async function Image({ params }: { params: Promise<{ ticker: string }> }) {
  const { ticker } = await params;
  const t = encodeURIComponent(ticker);
  const [summary, sentiment] = await Promise.all([
    api<Summary>(`/stocks/${t}/summary`).catch(() => null),
    api<SentimentHistory>(`/stocks/${t}/sentiment?days=30`).catch(() => null),
  ]);
  const name = summary?.company_name ?? ticker.toUpperCase();
  const p = summary?.price;
  const up = (p?.change ?? 0) >= 0;

  return new ImageResponse(
    (
      <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", background: "#ffffff",
                    padding: "56px 72px", fontFamily: TEXT, color: C.ink }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <Wordmark />
          <span style={{ fontSize: 26, color: C.muted }}>
            {summary ? `${summary.listing.exchange}: ${summary.listing.symbol}` : ticker.toUpperCase()}
          </span>
        </div>
        <div style={{ display: "flex", fontFamily: DISPLAY, fontWeight: 700, fontSize: name.length > 20 ? 76 : 96,
                      lineHeight: 1, marginTop: 56, letterSpacing: -2 }}>
          {name}
        </div>
        <div style={{ display: "flex", alignItems: "center", marginTop: 24 }}>
          {p ? (
            <>
              <span style={{ fontFamily: DISPLAY, fontWeight: 700, fontSize: 72, letterSpacing: -1 }}>₹{plain(p.close)}</span>
              {p.change_pct != null && (
                <span style={{ fontFamily: DISPLAY, fontWeight: 600, fontSize: 40, color: up ? C.up : C.down, marginLeft: 32, paddingTop: 10 }}>
                  {signed(p.change_pct)}% on the day
                </span>
              )}
            </>
          ) : (
            <span style={{ fontSize: 36, color: C.muted }}>Prices, results, filings and news tone</span>
          )}
        </div>
        <div style={{ display: "flex", flexDirection: "column", marginTop: "auto" }}>
          <span style={{ fontSize: 24, color: C.ink2, marginBottom: 14 }}>
            News tone, last 30 days
            {sentiment?.overall_label ? `: ${sentiment.overall_label}` : ""}
          </span>
          <Strip history={sentiment?.history ?? []} />
        </div>
      </div>
    ),
    { ...size, fonts: await fonts() },
  );
}
