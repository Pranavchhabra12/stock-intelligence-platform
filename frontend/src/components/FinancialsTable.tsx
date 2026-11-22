"use client";

import { useEffect, useRef, useState } from "react";

import type { Financials } from "@/lib/api";
import { metricValue } from "@/lib/format";

const ROWS = ["total_revenue", "net_profit", "eps", "shareholders_equity"];

export default function FinancialsTable({ quarterly, annual }: {
  quarterly: Financials | null;
  annual: Financials | null;
}) {
  const hasQuarters = (quarterly?.periods.length ?? 0) > 0;
  const [kind, setKind] = useState<"quarterly" | "annual">(hasQuarters ? "quarterly" : "annual");
  const data = kind === "quarterly" ? quarterly : annual;
  // Oldest on the left, so the table reads in time order.
  const periods = [...(data?.periods ?? [])].reverse();
  const defs = data?.metric_definitions ?? {};
  // Equity missing only in June and December quarters is how Indian reporting works, not a gap.
  const noEquity = kind === "quarterly" ? periods.filter((p) => p.metrics.shareholders_equity == null) : [];
  // Yahoo sometimes lags by several quarters; say so rather than pass old figures off as the latest.
  const newest = data?.periods[0]?.period_end;
  const behind = kind === "quarterly" && newest != null
    && Date.now() - Date.parse(newest) > 200 * 24 * 3600 * 1000;
  const halfYearly = noEquity.length > 0 && noEquity.every((p) => p.fiscal_quarter === 1 || p.fiscal_quarter === 3);
  // On a narrow screen the table scrolls sideways; open it on the newest period.
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = scroller.current;
    if (el) el.scrollLeft = el.scrollWidth;
  }, [kind]);

  return (
    <section className="section" aria-labelledby="fin-h">
      <header>
        <h2 id="fin-h">Results</h2>
        <div className="choice" role="group" aria-label="Reporting period">
          <button type="button" aria-pressed={kind === "quarterly"} onClick={() => setKind("quarterly")}>Quarterly</button>
          <button type="button" aria-pressed={kind === "annual"} onClick={() => setKind("annual")}>Annual</button>
        </div>
      </header>
      {periods.length === 0 ? (
        <p className="empty-state">No {kind} results stored yet.</p>
      ) : (
        <div className="table-scroll" ref={scroller} tabIndex={0} aria-label="Results table, scrolls sideways">
          <table className="statement">
            <thead>
              <tr>
                <th scope="col">{kind === "quarterly" ? "Quarter" : "Year"}</th>
                {periods.map((p) => <th scope="col" key={p.period_end}>{p.label}</th>)}
              </tr>
            </thead>
            <tbody>
              {ROWS.filter((code) => defs[code]).map((code) => (
                <tr key={code}>
                  <th scope="row">{defs[code].label}</th>
                  {periods.map((p) => (
                    <td key={p.period_end} className="num">{metricValue(defs[code].unit, p.metrics[code] ?? null)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {periods.length > 2 && <p className="scroll-hint small muted">Swipe the table for earlier periods.</p>}
      {behind && (
        <p className="source">
          The data source hasn’t published this company’s recent quarters yet, so these are the latest it has.
          Annual results may be newer.
        </p>
      )}
      {halfYearly && (
        <p className="source">
          Indian companies publish their balance sheet every six months, so equity is shown for the September and
          March quarters only.
        </p>
      )}
      <p className="source">
        As reported{data?.source?.attribution ? `. ${data.source.attribution.replace(/\.\s*$/, "")}` : ""}. A dash means
        that figure wasn’t in the data for that period; nothing is estimated.
      </p>
    </section>
  );
}
