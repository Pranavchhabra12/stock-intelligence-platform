"use client";

import { useEffect, useState } from "react";

type State = { status: "checking" | "ok" | "warning" | "failed"; detail: string };

/** Checks the API from the visitor's own browser, through this site, and times it. */
export default function LiveCheck() {
  const [state, setState] = useState<State>({ status: "checking", detail: "Checking…" });

  useEffect(() => {
    const started = performance.now();
    const slow = setTimeout(() => setState({ status: "checking", detail: "The API is waking up; this takes up to a minute after a quiet spell." }), 4000);
    fetch("/api/health", { cache: "no-store" })
      .then(async (res) => {
        const ms = Math.round(performance.now() - started);
        clearTimeout(slow);
        if (!res.ok) {
          setState({ status: "failed", detail: `The API answered with an error (${res.status}).` });
          return;
        }
        setState(ms > 4000
          ? { status: "warning", detail: `Answered in ${(ms / 1000).toFixed(1)} s; it had been asleep. It's quick now.` }
          : { status: "ok", detail: `Answered in ${ms} ms.` });
      })
      .catch(() => {
        clearTimeout(slow);
        setState({ status: "failed", detail: "Couldn’t reach the API from this browser." });
      });
    return () => clearTimeout(slow);
  }, []);

  return <StatusRow name="Website to API (from your browser)" status={state.status} detail={state.detail} />;
}

const WORDS = { ok: "Working", warning: "Needs a look", failed: "Not working", checking: "Checking" };

export function StatusRow({ name, status, detail, when }: {
  name: string;
  status: "ok" | "warning" | "failed" | "checking";
  detail: string;
  when?: string | null;
}) {
  return (
    <li className="status-row" data-status={status}>
      <span className="status-mark" aria-hidden="true">
        {status === "ok" ? "✓" : status === "warning" ? "!" : status === "failed" ? "×" : "…"}
      </span>
      <div>
        <p className="status-name">{name} <span className="status-word">{WORDS[status]}</span></p>
        <p className="status-detail">{detail}{when ? ` Last worked ${when}.` : ""}</p>
      </div>
    </li>
  );
}
