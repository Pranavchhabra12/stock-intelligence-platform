import { ImageResponse } from "next/og";

import { maybe } from "@/lib/api";
import { C, DISPLAY, fonts, Strip, TEXT, Wordmark } from "@/og/card";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";
export const alt = "Stock Intelligence: research Indian listed companies";
export const revalidate = 3600;

interface Overview { companies: { company_name: string; tone_30d: { date: string; score: number }[] }[] }

export default async function Image() {
  const overview = await maybe<Overview>("/stocks").catch(() => null);
  const rows = (overview?.companies ?? []).slice(0, 5);

  return new ImageResponse(
    (
      <div style={{ display: "flex", flexDirection: "column", width: "100%", height: "100%", background: "#ffffff",
                    padding: "56px 72px", fontFamily: TEXT, color: C.ink }}>
        <Wordmark />
        <div style={{ display: "flex", fontFamily: DISPLAY, fontWeight: 700, fontSize: 66, lineHeight: 1,
                      marginTop: 36, letterSpacing: -1.5 }}>
          Research Indian listed companies
        </div>
        <span style={{ fontSize: 28, color: C.ink2, marginTop: 14 }}>
          Prices, results and AI-rated news tone for NSE and BSE companies
        </span>
        <div style={{ display: "flex", flexDirection: "column", gap: 12, marginTop: 44 }}>
          {rows.map((c) => (
            <div key={c.company_name} style={{ display: "flex", alignItems: "center", gap: 24 }}>
              <span style={{ width: 300, fontFamily: DISPLAY, fontWeight: 600, fontSize: 24 }}>{c.company_name}</span>
              <div style={{ display: "flex", flex: 1 }}><Strip history={c.tone_30d} height={20} /></div>
            </div>
          ))}
        </div>
      </div>
    ),
    { ...size, fonts: await fonts() },
  );
}
