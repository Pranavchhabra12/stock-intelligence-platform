"use client";

import { useState } from "react";

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
        <div className="table-scroll" tabIndex={0} aria-label="Results table, scrolls sideways">
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
      <p className="source">
        As reported{data?.source?.attribution ? `. ${data.source.attribution.replace(/\.\s*$/, "")}` : ""}. A dash means the source didn’t
        report that figure; nothing is estimated.
      </p>
    </section>
  );
}
