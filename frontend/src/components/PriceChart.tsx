"use client";

import { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { browserApi, type PriceRow, type Prices } from "@/lib/api";
import { fmtDate, rupees, signed } from "@/lib/format";

const RANGES = [
  { key: "1M", days: 31 },
  { key: "6M", days: 183 },
  { key: "1Y", days: 366 },
  { key: "5Y", days: 1827 },
] as const;
type RangeKey = (typeof RANGES)[number]["key"];

const axisDate = (days: number) => (iso: string) => {
  const d = new Date(iso);
  return days > 400
    ? d.toLocaleDateString("en-IN", { year: "numeric" })
    : d.toLocaleDateString("en-IN", { day: "numeric", month: "short" });
};

export default function PriceChart({ ticker, initial }: { ticker: string; initial: Prices | null }) {
  const [range, setRange] = useState<RangeKey>("1Y");
  const [cache, setCache] = useState<Partial<Record<RangeKey, PriceRow[]>>>(
    initial ? { "1Y": initial.prices } : {});
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);
  const rows = cache[range] ?? [];
  const days = RANGES.find((r) => r.key === range)!.days;

  const choose = async (key: RangeKey) => {
    setRange(key);
    setFailed(false);
    if (cache[key]) return;
    const d = RANGES.find((r) => r.key === key)!.days;
    const start = new Date(Date.now() - d * 864e5).toISOString().slice(0, 10);
    setLoading(true);
    try {
      const body = await browserApi<Prices>(`/stocks/${encodeURIComponent(ticker)}/prices?start=${start}`);
      setCache((c) => ({ ...c, [key]: body.prices }));
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  const change = useMemo(() => {
    if (rows.length < 2) return null;
    const first = rows[0].close, last = rows[rows.length - 1].close;
    return { abs: last - first, pct: ((last - first) / first) * 100 };
  }, [rows]);

  const domain = useMemo<[number, number] | undefined>(() => {
    if (!rows.length) return undefined;
    const closes = rows.map((r) => r.close);
    const lo = Math.min(...closes), hi = Math.max(...closes), pad = (hi - lo) * 0.08 || hi * 0.02;
    return [Math.max(0, lo - pad), hi + pad];
  }, [rows]);

  return (
    <section className="section" aria-labelledby="price-h">
      <header>
        <div>
          <h2 id="price-h">Price</h2>
          {change && (
            <p className={`small ${change.abs >= 0 ? "up" : "down"}`}>
              {signed(change.pct)}% over {range === "1M" ? "the last month" : range === "6M" ? "six months"
                : range === "1Y" ? "the last year" : "five years"}
            </p>
          )}
        </div>
        <div className="choice" role="group" aria-label="Chart range">
          {RANGES.map((r) => (
            <button key={r.key} type="button" aria-pressed={range === r.key} onClick={() => choose(r.key)}>
              {r.key}
            </button>
          ))}
        </div>
      </header>

      <div className="chart-box" aria-busy={loading}>
        {failed ? (
          <p className="empty-state">Couldn’t load this range. Pick it again to retry.</p>
        ) : rows.length === 0 ? (
          <p className="empty-state">{loading ? "Loading prices…" : "No prices stored yet. Refresh the company to fetch them."}</p>
        ) : (
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={rows} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
              <CartesianGrid vertical={false} stroke="var(--line)" strokeDasharray="0" />
              <XAxis dataKey="trade_date" tickFormatter={axisDate(days)} minTickGap={48}
                     tick={{ fill: "var(--muted)", fontSize: 12 }} tickLine={false} axisLine={{ stroke: "var(--line)" }} />
              <YAxis domain={domain} width={64} orientation="right" tickLine={false} axisLine={false}
                     tick={{ fill: "var(--muted)", fontSize: 12 }}
                     tickFormatter={(v: number) => v.toLocaleString("en-IN", { maximumFractionDigits: 0 })} />
              <Tooltip
                cursor={{ stroke: "var(--ink-2)", strokeWidth: 1 }}
                content={({ active, payload }) => {
                  const p = active && payload?.[0]?.payload as PriceRow | undefined;
                  if (!p) return null;
                  return (
                    <div className="chart-tip">
                      <strong>{fmtDate(p.trade_date)}</strong><br />
                      Close {rupees(p.close)}<br />
                      Range {rupees(p.low)} to {rupees(p.high)}
                    </div>
                  );
                }}
              />
              <Line type="linear" dataKey="close" stroke="#1f3a5f" strokeWidth={2} dot={false}
                    activeDot={{ r: 4, stroke: "#fff", strokeWidth: 2, fill: "#1f3a5f" }} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>
      {rows.length > 0 && (
        <p className="visually-hidden">
          Closing price from {fmtDate(rows[0].trade_date)} ({rupees(rows[0].close)}) to{" "}
          {fmtDate(rows[rows.length - 1].trade_date)} ({rupees(rows[rows.length - 1].close)}).
        </p>
      )}
      {initial && initial.sources.length > 0 && (
        <p className="source">
          {initial.listing.exchange} daily closes{initial.price_basis === "split_adjusted" ? ", adjusted for splits and bonuses" : ""}.{" "}
          {initial.sources.map((s) => s.attribution ?? s.name).join(" ")}
        </p>
      )}
    </section>
  );
}
