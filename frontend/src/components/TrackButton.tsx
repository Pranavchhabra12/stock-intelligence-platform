"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import { showRemovedCompany, showTrackedCompany } from "@/app/actions";
import { ApiError, browserApi, type TrackResponse, type UntrackResponse } from "@/lib/api";

/** "Add to Power BI": the company is then collected daily, rated by AI and included in the
 * dashboard data. Anyone can add one, up to the demo's cap, and remove one a visitor added.
 * The starting companies stay, so the dashboard is never empty. */
export default function TrackButton({ ticker, name, tracked, canRemove, count, cap }: {
  ticker: string;
  name: string;
  tracked: boolean;
  canRemove: boolean;
  count: number;
  cap: number;
}) {
  const router = useRouter();
  const [isTracked, setTracked] = useState(tracked);
  // A company added on this visit can be removed again straight away.
  const [removable, setRemovable] = useState(canRemove);
  const [tracking, setTracking] = useState(count);
  const [busy, setBusy] = useState<"add" | "remove" | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const removeRef = useRef<HTMLButtonElement>(null);
  const full = !isTracked && tracking >= cap;
  const path = `/stocks/${encodeURIComponent(ticker)}/track`;

  const add = async () => {
    setBusy("add");
    setMessage(null);
    try {
      const res = await browserApi<TrackResponse>(path, { method: "POST" });
      setTracked(true);
      setRemovable(true);
      setTracking(res.tracked_count);
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
      setBusy(null);
    }
  };

  const remove = async () => {
    setBusy("remove");
    setMessage(null);
    try {
      const res = await browserApi<UntrackResponse>(path, { method: "DELETE" });
      setTracked(false);
      setConfirming(false);
      setTracking(res.tracked_count);
      setMessage(`Removed. Power BI now follows ${res.tracked_count} of ${res.cap} companies.`);
      await showRemovedCompany(ticker).catch(() => false);
      router.refresh();
    } catch (err) {
      setConfirming(false);
      if (err instanceof ApiError && err.status === 409) {
        setRemovable(false);
        setMessage("This is one of the starting companies, so it stays in Power BI.");
      } else {
        setMessage("Couldn’t remove it right now. Try again in a moment.");
      }
    } finally {
      setBusy(null);
    }
  };

  if (isTracked) {
    return (
      <span className="track">
        <span className="track-tag" title="Collected daily, rated by AI and included in the Power BI dashboard">
          <svg aria-hidden="true" viewBox="0 0 16 16" width="14" height="14"><path d="M3 8.5 6.5 12 13 4.5"
            fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></svg>
          In Power BI
        </span>
        {removable && !confirming && (
          <button type="button" className="track-remove" ref={removeRef}
                  onClick={() => { setMessage(null); setConfirming(true); }}>
            Remove
          </button>
        )}
        {confirming && (
          <span className="track-confirm" role="group" aria-label={`Remove ${name} from Power BI?`}>
            <span className="small">Stop updating {name} every day? Its data so far is kept.</span>
            <button type="button" className="track-button danger" onClick={remove} disabled={busy !== null}
                    autoFocus>
              {busy === "remove" ? "Removing…" : "Remove from Power BI"}
            </button>
            <button type="button" className="track-remove" disabled={busy !== null}
                    onClick={() => { setConfirming(false); requestAnimationFrame(() => removeRef.current?.focus()); }}>
              Keep it
            </button>
          </span>
        )}
        {message && <span className="small muted" role="status">{message}</span>}
      </span>
    );
  }
  return (
    <span className="track">
      <button type="button" className="track-button" onClick={add} disabled={busy !== null || full}>
        {busy === "add" ? "Adding…" : "Add to Power BI"}
      </button>
      {(message || full) && (
        <span className="small muted" role="status">
          {message ?? `Power BI already follows ${cap} companies, the most this free demo allows.`}
        </span>
      )}
    </span>
  );
}
