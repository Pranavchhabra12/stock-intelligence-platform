import Link from "next/link";

import SearchBox from "@/components/SearchBox";
import ToneLegend from "@/components/ToneLegend";
import ToneStrip from "@/components/ToneStrip";
import { maybe, OVERVIEW_TAG } from "@/lib/api";
import { fmtDate, plain, signed } from "@/lib/format";

interface Overview {
  count: number;
  tone_days: number;
  companies: {
    company_id: string;
    company_name: string;
    sector: string | null;
    exchange: string;
    symbol: string;
    trade_date: string | null;
    close: number | null;
    change_pct: number | null;
    tone_30d: { date: string; score: number; article_count: number }[];
  }[];
}

export default async function Home() {
  const overview = await maybe<Overview>("/stocks", 300, [OVERVIEW_TAG]);
  const latest = overview?.companies.map((c) => c.trade_date).filter(Boolean).sort().at(-1);
  // The hero shows the product itself: the company that moved most on the latest day.
  const featured = overview?.companies
    .filter((c) => c.close != null && c.change_pct != null)
    .sort((a, b) => Math.abs(b.change_pct!) - Math.abs(a.change_pct!))[0];

  return (
    <>
      <section className="home-hero">
        <div>
          <h1>Research Indian listed companies</h1>
          <p className="lede">
            Prices, quarterly results, exchange filings and the tone of the news, in one place, for companies listed on
            NSE and BSE.
          </p>
          <SearchBox autoFocus />
          <p className="hint">Try “RIL”, “Infosys” or a BSE code like 500325.</p>
        </div>
        {featured && (
          <Link className="featured" href={`/stocks/${encodeURIComponent(featured.symbol)}`}>
            <span className="why">Biggest move{featured.trade_date ? ` on ${fmtDate(featured.trade_date)}` : ""}</span>
            <p className="name">{featured.company_name}</p>
            <div className="row">
              <span className="num px">₹{plain(featured.close)}</span>
              <span className={`num ${featured.change_pct! >= 0 ? "up" : "down"}`}>
                {featured.change_pct! >= 0 ? "▲" : "▼"} {signed(featured.change_pct)}%
              </span>
            </div>
            <ToneStrip large decorative history={featured.tone_30d} days={overview!.tone_days}
                       label={`${featured.company_name}: news tone by day, last ${overview!.tone_days} days`} />
            <p className="small muted" style={{ marginTop: "0.5rem" }}>News tone, last {overview!.tone_days} days</p>
            <p className="go">Open {featured.company_name}</p>
          </Link>
        )}
      </section>

      <section aria-labelledby="board-h">
        <div className="board-head">
          <h2 id="board-h">Companies tracked</h2>
          {latest && <p className="small muted">Closing prices for {fmtDate(latest)}</p>}
        </div>
        {!overview ? (
          <p className="empty-state">The data service isn’t answering right now, so prices can’t be shown. Search
            still works once it’s back.</p>
        ) : (
          <>
            <table className="board">
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col" className="right">Last close</th>
                  <th scope="col" className="right">Day</th>
                  <th scope="col" className="tone-cell">News tone, last {overview.tone_days} days</th>
                </tr>
              </thead>
              <tbody>
                {overview.companies.map((c) => (
                  <tr key={c.company_id}>
                    <td className="company">
                      <Link href={`/stocks/${encodeURIComponent(c.symbol)}`}>{c.company_name}</Link>
                      <span className="sub">{c.exchange}: {c.symbol}<span className="hide-sm">{c.sector ? `, ${c.sector}` : ""}</span></span>
                    </td>
                    <td className="right num price">{c.close != null ? plain(c.close) : "—"}</td>
                    <td className={`right num ${c.change_pct == null ? "" : c.change_pct >= 0 ? "up" : "down"}`}>
                      {c.change_pct == null ? "—" : `${signed(c.change_pct)}%`}
                    </td>
                    <td className="tone-cell">
                      <ToneStrip history={c.tone_30d} days={overview.tone_days}
                                 label={`${c.company_name}: news tone by day`} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ToneLegend />
          </>
        )}
      </section>
    </>
  );
}
