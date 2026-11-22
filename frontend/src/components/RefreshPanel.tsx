"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { ApiError, browserApi, type Job, type RefreshResponse } from "@/lib/api";
import { ago } from "@/lib/format";

const STEP_NAMES: Record<string, string> = {
  prices: "Prices and results",
  news: "News and filings",
  documents: "Reports",
  analysis: "AI tone and summaries",
};
const STATE_WORDS: Record<string, string> = {
  running: "Working…",
  completed: "Done",
  completed_with_errors: "Partly done",
  failed: "Failed",
  skipped: "Skipped",
};
const ACTIVE = new Set(["pending", "running"]);

export default function RefreshPanel({ ticker, lastJob }: { ticker: string; lastJob: Job | null }) {
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(lastJob && ACTIVE.has(lastJob.status) ? lastJob : null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const poll = (id: string) => {
    timer.current = setTimeout(async () => {
      try {
        const next = await browserApi<Job>(`/jobs/${id}`);
        setJob(next);
        if (ACTIVE.has(next.status)) {
          poll(id);
        } else {
          setBusy(false);
          setMessage(next.status === "failed"
            ? "The refresh failed. The page still shows the last stored data."
            : next.status === "completed_with_errors"
              ? "Updated, but some sources didn’t answer. Their data is unchanged."
              : "Updated.");
          router.refresh();
        }
      } catch {
        poll(id);   // a missed poll isn't a failed job; try again
      }
    }, 2500);
  };

  useEffect(() => {
    if (job && ACTIVE.has(job.status)) {
      setBusy(true);
      poll(job.job_id);
    }
    return () => clearTimeout(timer.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const start = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const res = await browserApi<RefreshResponse>(`/stocks/${encodeURIComponent(ticker)}/refresh`, { method: "POST" });
      setJob(res);
      if (ACTIVE.has(res.status)) {
        poll(res.job_id);
      } else {
        setBusy(false);
        setMessage(`Already refreshed ${res.finished_at ? ago(res.finished_at) : "moments ago"}; showing that update.`);
      }
    } catch (err) {
      setBusy(false);
      setMessage(err instanceof ApiError && err.status === 429
        ? "Several refreshes are running. Try again in a few minutes."
        : "Couldn’t start a refresh. Try again shortly.");
    }
  };

  const finished = lastJob?.finished_at;

  return (
    <section className="section refresh" aria-labelledby="refresh-h">
      <header><h2 id="refresh-h">Update</h2></header>
      <p className="small muted" style={{ marginBottom: "0.9rem" }}>
        {finished ? `Last refreshed ${ago(finished)}. ` : ""}Data also updates every weekday evening, and news every
        hour during market hours.
      </p>
      <button type="button" className="button" onClick={start} disabled={busy}>
        {busy ? "Refreshing…" : "Refresh this company"}
      </button>
      {job && Object.keys(job.steps).length > 0 && (
        <ol aria-live="polite">
          {Object.entries(job.steps).map(([name, step]) => (
            <li key={name}>
              <span>{STEP_NAMES[name] ?? name}</span>
              <span className="state" data-s={step.status}>{STATE_WORDS[step.status] ?? step.status}</span>
            </li>
          ))}
        </ol>
      )}
      {busy && job && Object.keys(job.steps).length === 0 && <p className="status-line">Starting…</p>}
      {message && <p className="status-line" role="status">{message}</p>}
    </section>
  );
}
