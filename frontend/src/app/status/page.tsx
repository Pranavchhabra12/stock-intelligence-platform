import type { Metadata } from "next";

import LiveCheck, { StatusRow } from "@/components/LiveCheck";
import { maybe } from "@/lib/api";
import { ago, fmtDateTime } from "@/lib/format";

export const metadata: Metadata = { title: "Status" };
export const dynamic = "force-dynamic";

interface Status {
  status: "ok" | "warning" | "failed";
  checked_at: string;
  api: { version: string; started_at: string; region: string | null };
  database_ms: number | null;
  companies: { listed: number | null; tracked: number | null; cap: number };
  checks: { name: string; status: "ok" | "warning" | "failed"; detail: string; last_success: string | null }[];
}

const HEADLINE = {
  ok: "Everything is working",
  warning: "Working, with something to look at",
  failed: "Something isn’t working",
};

export default async function StatusPage() {
  const status = await maybe<Status>("/status", 0);

  return (
    <div className="status-page">
      <h1>{status ? HEADLINE[status.status] : "The API isn’t answering"}</h1>
      <p className="lede muted">
        {status
          ? `Checked ${fmtDateTime(status.checked_at)} IST. Each part shows whether it works and how fresh its data is.`
          : "The website is up, but its API didn’t answer. It may be waking up; reload in a minute."}
      </p>

      <ul className="status-list">
        <StatusRow name="Website" status="ok" detail="You’re looking at it." />
        <LiveCheck />
        {status?.checks.map((c) => (
          <StatusRow key={c.name} name={c.name} status={c.status} detail={c.detail}
                     when={c.status !== "ok" && c.last_success ? ago(c.last_success) : null} />
        ))}
      </ul>

      {status && (
        <dl className="status-facts">
          <div><dt>Companies searchable</dt><dd className="num">{status.companies.listed?.toLocaleString("en-IN") ?? "—"}</dd></div>
          <div><dt>In Power BI</dt><dd className="num">{status.companies.tracked ?? "—"} of {status.companies.cap}</dd></div>
          <div><dt>API version</dt><dd className="num">{status.api.version}</dd></div>
          <div><dt>API running since</dt><dd>{ago(status.api.started_at)}</dd></div>
        </dl>
      )}
      <p className="small muted" style={{ marginTop: "1.5rem", maxWidth: "60ch" }}>
        These checks read the platform’s own records, so loading this page never spends a data provider’s quota.
        The outside providers themselves (Yahoo, Upstox, the news feeds and Gemini) are called once a day by an
        automated check on GitHub.
      </p>
    </div>
  );
}
