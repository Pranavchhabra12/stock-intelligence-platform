// Shared pieces for the link-preview images (1200x630) shown when a page is shared on LinkedIn etc.
// Rendered by next/og, which supports a subset of CSS: every box with several children is a flex box.

import { readFile } from "node:fs/promises";
import { join } from "node:path";

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

// The "Ext" faces carry ₹ and other symbols missing from the Latin subset.
export const DISPLAY = "Rajdhani, RajdhaniExt";
export const TEXT = "Mukta, MuktaExt";

export const C = {
  ink: "#1c2333", ink2: "#485266", muted: "#6b7485", line: "#dce1e8", accent: "#0e6e7e",
  pos: "#2166ac", neg: "#c4621b", mid: "#a7afbc", up: "#17734a", down: "#b0362c", panel: "#f2f4f7",
};

export async function fonts() {
  const dir = join(process.cwd(), "src/og/fonts");
  const load = (f: string) => readFile(join(dir, f));
  const [r7, r7x, r6, m5, m5x] = await Promise.all([
    load("rajdhani-latin-700-normal.woff"), load("rajdhani-latin-ext-700-normal.woff"),
    load("rajdhani-latin-600-normal.woff"), load("mukta-latin-500-normal.woff"), load("mukta-latin-ext-500-normal.woff"),
  ]);
  return [
    { name: "Rajdhani", data: r7, weight: 700 as const, style: "normal" as const },
    { name: "RajdhaniExt", data: r7x, weight: 700 as const, style: "normal" as const },
    { name: "Rajdhani", data: r6, weight: 600 as const, style: "normal" as const },
    { name: "Mukta", data: m5, weight: 500 as const, style: "normal" as const },
    { name: "MuktaExt", data: m5x, weight: 500 as const, style: "normal" as const },
  ];
}

/** Solid-colour version of the site's tone fill (next/og has no color-mix). */
export function toneHex(score: number): string {
  if (Math.abs(score) < 0.05) return C.mid;
  const t = 0.35 + 0.65 * Math.min(1, Math.abs(score) / 0.8);
  const pole = score > 0 ? C.pos : C.neg;
  const mix = (a: string, b: string) => {
    const pa = [1, 3, 5].map((i) => parseInt(a.slice(i, i + 2), 16));
    const pb = [1, 3, 5].map((i) => parseInt(b.slice(i, i + 2), 16));
    return "#" + pa.map((v, i) => Math.round(v * t + pb[i] * (1 - t)).toString(16).padStart(2, "0")).join("");
  };
  return mix(pole, C.mid);
}

export function lastDays(n: number): string[] {
  const ist = new Date(Date.now() + 5.5 * 3600 * 1000);
  return Array.from({ length: n }, (_, k) => {
    const d = new Date(Date.UTC(ist.getUTCFullYear(), ist.getUTCMonth(), ist.getUTCDate() - (n - k)));
    return d.toISOString().slice(0, 10);
  });
}

export function Strip({ history, height = 56 }: { history: { date: string; score: number }[]; height?: number }) {
  const byDate = new Map(history.map((d) => [d.date, d.score]));
  return (
    <div style={{ display: "flex", gap: 5, width: "100%" }}>
      {lastDays(30).map((d) => {
        const s = byDate.get(d);
        return (
          <div key={d} style={{
            flex: 1, height, borderRadius: 3,
            background: s == null ? "#ffffff" : toneHex(s),
            border: s == null ? `2px solid ${C.line}` : "none",
          }} />
        );
      })}
    </div>
  );
}

export function Wordmark() {
  return (
    <div style={{ display: "flex", fontFamily: DISPLAY, fontWeight: 700, fontSize: 34, color: C.ink }}>
      <span>Stock</span><span style={{ color: C.accent, marginLeft: 10 }}>Intelligence</span>
    </div>
  );
}
