"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { showTrackedCompany } from "@/app/actions";
import { ApiError, browserApi, type TrackResponse } from "@/lib/api";

/** "Add to Power BI": the company is then collected daily, rated by AI and included in the
 * dashboard data. Anyone can add one, up to the demo's cap. */
export default function TrackButton({ ticker, tracked, count, cap }: {
  ticker: string;
  tracked: boolean;
  count: number;
  cap: number;
}) {
  const router = useRouter();
  const [isTracked, setTracked] = useState(tracked);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const full = !isTracked && count >= cap;

  const add = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await browserApi<TrackResponse>(`/stocks/${encodeURIComponent(ticker)}/track`, { method: "POST" });
      setTracked(true);
      setMessage(res.created
        ? `Added. Power BI now follows ${res.tracked_count} of ${res.cap} companies; AI news tone is being added now.`
        : "Already in Power BI.");
      await showTrackedCompany(ticker).catch(() => false);
      router.refresh();
    } catch (err) {
      setMessage(err instanceof ApiError && err.status === 409
        ? `Power BI already follows ${cap} companies, the most this free demo allows.`
        : "Couldn’t add it right now. Try again in a moment.");
    } finally {
      setBusy(false);
    }
  };

  if (isTracked) {
    return (
      <span className="track-tag" title="Collected daily, rated by AI and included in the Power BI dashboard">
        <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14"><path d="M3 8.5 6.5 12 13 4.5"
          fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
        In Power BI
        {message && <span className="visually-hidden" role="status">{message}</span>}
      </span>
    );
  }
  return (
    <span className="track">
      <button type="button" className="track-button" onClick={add} disabled={busy || full}>
        {busy ? "Adding…" : "Add to Power BI"}
      </button>
      {(message || full) && (
        <span className="small muted" role="status">
          {message ?? `Power BI already follows ${cap} companies, the most this free demo allows.`}
        </span>
      )}
    </span>
  );
}
