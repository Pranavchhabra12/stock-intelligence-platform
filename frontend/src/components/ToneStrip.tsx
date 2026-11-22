"use client";

import { useState } from "react";

import { fmtDate } from "@/lib/format";
import { toneFill, toneWord } from "@/lib/tone";

export interface ToneDay {
  date: string;
  score: number;
  article_count: number;
  positive?: number;
  neutral?: number;
  negative?: number;
}

/** Calendar days ending yesterday (India time): today isn't scored until it's over. */
function lastDays(n: number): string[] {
  const todayIst = new Date(Date.now() + 5.5 * 3600 * 1000);
  const out: string[] = [];
  for (let i = n; i >= 1; i--) {
    const d = new Date(Date.UTC(todayIst.getUTCFullYear(), todayIst.getUTCMonth(), todayIst.getUTCDate() - i));
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}

export default function ToneStrip({ history, days = 30, large = false, label, decorative = false }: {
  history: ToneDay[];
  days?: number;
  large?: boolean;
  label: string;
  /** inside a link: no focus stops or tooltip of its own */
  decorative?: boolean;
}) {
  const interactive = large && !decorative;
  const byDate = new Map(history.map((d) => [d.date, d]));
  const dates = lastDays(days);
  const [tip, setTip] = useState<{ i: number; day: ToneDay } | null>(null);

  return (
    <div style={{ position: "relative" }}>
      <div className={`tone-strip${large ? " large" : ""}`} role={decorative ? undefined : "list"}
           aria-label={decorative ? undefined : label} aria-hidden={decorative || undefined}
           onMouseLeave={() => setTip(null)}>
        {dates.map((date, i) => {
          const day = byDate.get(date);
          const text = day
            ? `${fmtDate(date)}: ${toneWord(day.score)} (${day.score.toFixed(2)}), ${day.article_count} article${
              day.article_count === 1 ? "" : "s"}`
            : `${fmtDate(date)}: no rated news`;
          return (
            <div
              key={date}
              role={decorative ? undefined : "listitem"}
              className={`day${large ? " reveal" : ""}`}
              style={{ ["--tone-fill" as string]: day ? toneFill(day.score) : undefined, ["--i" as string]: i }}
              data-has={day ? "true" : "false"}
              tabIndex={day && interactive ? 0 : -1}
              aria-label={decorative ? undefined : text}
              onMouseEnter={() => day && setTip({ i, day })}
              onFocus={() => day && setTip({ i, day })}
              onBlur={() => setTip(null)}
            />
          );
        })}
      </div>
      {tip && interactive && (
        <div className="tone-tip" role="status"
             style={{ left: `${((tip.i + 0.5) / dates.length) * 100}%` }}>
          <strong>{fmtDate(tip.day.date)}</strong>
          <br />
          Tone {toneWord(tip.day.score)} ({tip.day.score > 0 ? "+" : ""}{tip.day.score.toFixed(2)})
          <br />
          {tip.day.article_count} article{tip.day.article_count === 1 ? "" : "s"}
          {tip.day.positive != null &&
            `: ${tip.day.positive} positive, ${tip.day.neutral} neutral, ${tip.day.negative} negative`}
        </div>
      )}
    </div>
  );
}
