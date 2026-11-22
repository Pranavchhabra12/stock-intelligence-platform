import type { Metadata } from "next";
import { notFound } from "next/navigation";

import FinancialsTable from "@/components/FinancialsTable";
import Flash from "@/components/Flash";
import NewsList from "@/components/NewsList";
import PriceChart from "@/components/PriceChart";
import QuoteBar from "@/components/QuoteBar";
import RefreshPanel from "@/components/RefreshPanel";
import TrackButton from "@/components/TrackButton";
import ToneLegend from "@/components/ToneLegend";
import ToneStrip from "@/components/ToneStrip";
import { toneWord } from "@/lib/tone";
import { ApiError, type CompanyPage as PageData, companyTag, maybe } from "@/lib/api";
import { fmtDate, metricValue, rupees, signed } from "@/lib/format";

type Params = { params: Promise<{ ticker: string }> };

const DOC_TYPES: Record<string, string> = {
  annual_report: "Annual report",
  quarterly_results: "Quarterly results",
  investor_presentation: "Investor presentation",
  exchange_filing: "Exchange filing",
  earnings_transcript: "Earnings call transcript",
  other_disclosure: "Disclosure",
};

const KEY_ORDER = ["market_cap", "pe_ratio", "pb_ratio", "dividend_yield", "roe", "eps_ttm", "revenue_ttm",
  "net_profit_ttm", "revenue_growth_yoy", "profit_growth_yoy"];

async function load(ticker: string) {
  // One request for the whole page; the API reads it all over one database connection.
  try {
    const page = await maybe<PageData>(`/stocks/${encodeURIComponent(ticker)}/page`, 300, [companyTag(ticker)]);
    if (!page) return null;
    return {
      ...page,
      jobs: { jobs: page.last_job ? [page.last_job] : [] },
    };
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return "missing" as const;
    throw err;
  }
}

export async function generateMetadata({ params }: Params): Promise<Metadata> {
  const { ticker } = await params;
  const data = await load(ticker);
  if (!data || data === "missing") return { title: ticker.toUpperCase() };
  return {
    title: `${data.company.company_name} (${ticker.toUpperCase()})`,
    description: `Price, results, filings and news tone for ${data.company.company_name}.`,
  };
}

export default async function CompanyPage({ params }: Params) {
  const { ticker } = await params;
  const data = await load(ticker);
  if (data === "missing") notFound();
  if (!data) {
    return (
      <div className="prose">
        <h1>{ticker.toUpperCase()}</h1>
        <p>The data service isn’t answering right now. Reload the page in a minute.</p>
      </div>
    );
  }

  const { company, summary, prices, quarterly, annual, news, sentiment, analysis, reports, jobs, tracking } = data;
  // An untracked company opened for the first time has nothing stored yet: fetch it once.
  const firstLook = !summary?.price && !(news?.articles.length);
  const price = summary?.price ?? null;
  const metrics = new Map(summary?.metrics.map((m) => [m.code, m]));
  const range = price?.high_52w && price.low_52w && price.high_52w > price.low_52w
    ? ((price.close - price.low_52w) / (price.high_52w - price.low_52w)) * 100 : null;
  const report = analysis?.reports[0];
  const moveText = price?.change != null && price.change_pct != null
    ? `${price.change >= 0 ? "▲" : "▼"} ${signed(price.change)} (${signed(price.change_pct)}%)` : null;
  const moveClass = price?.change == null ? "" : price.change >= 0 ? "up" : "down";
  const totals = sentiment?.history.reduce((acc, d) => ({
    pos: acc.pos + d.positive, neu: acc.neu + d.neutral, neg: acc.neg + d.negative,
  }), { pos: 0, neu: 0, neg: 0 });

  return (
    <>
      <QuoteBar name={company.company_name} price={price ? rupees(price.close) : null} move={moveText}
                moveClass={moveClass} />
      <section className="company-head">
        <div>
          <div className="company-title">
            <h1>{company.company_name}</h1>
            <div className="listings">
              {company.listings.map((l) => (
                <span className="listing-tag" key={l.listing_id}>
                  {l.exchange} {l.exchange === "BSE" ? l.exchange_code ?? l.symbol : l.symbol}
                </span>
              ))}
            </div>
            <TrackButton ticker={ticker} tracked={company.is_tracked} count={tracking.tracked_count}
                         cap={tracking.cap} />
          </div>
          {(company.sector || company.industry) && (
            <p className="company-sub">{[company.sector, company.industry].filter(Boolean).join(", ")}</p>
          )}
        </div>

        {price ? (
          <div className="quote" id="quote-anchor">
            <div>
              <p className="num last"><Flash value={rupees(price.close)} /></p>
              <p className="when">Close on {fmtDate(price.trade_date)}, {summary?.listing.exchange}</p>
            </div>
            {moveText && (
              <p className={`num move ${moveClass}`}>
                <Flash value={moveText} />
                <span className="visually-hidden"> from the previous close</span>
              </p>
            )}
            {range != null && (
              <div className="range52">
                <span className="small muted">52-week range</span>
                <div className="bar" role="img"
                     aria-label={`Current price is ${Math.round(range)}% of the way from the 52-week low to the high`}>
                  <i style={{ left: `calc(${range}% - 1.5px)` }} />
                </div>
                <div className="ends num">
                  <span>{rupees(price.low_52w, 0)}</span><span>{rupees(price.high_52w, 0)}</span>
                </div>
              </div>
            )}
          </div>
        ) : (
          <p className="empty-state" id="quote-anchor">
            {firstLook
              ? "This is the first time anyone has opened this company, so its prices, results and news are being fetched now. It takes about a minute."
              : "No prices stored for this company yet. Use “Refresh this company” to fetch them."}
          </p>
        )}

        <div className="tone-block">
          <div className="tone-caption">
            <span>
              News tone, last 30 days:{" "}
              <strong>{sentiment?.overall_score != null
                ? `${toneWord(sentiment.overall_score)} (${signed(sentiment.overall_score)})`
                : company.is_tracked ? "not enough news yet" : "starts once it’s added to Power BI"}</strong>
            </span>
            {totals && sentiment && sentiment.article_count > 0 && (
              <span className="small muted">
                {sentiment.article_count} articles: {totals.pos} positive, {totals.neu} neutral, {totals.neg} negative
              </span>
            )}
          </div>
          <ToneStrip large history={sentiment?.history ?? []} label={`${company.company_name}: news tone for each of the last 30 days`} />
          <ToneLegend />
        </div>

        <nav className="jump" aria-label="Jump to a section">
          <a href="#price-h">Price</a>
          <a href="#fin-h">Results</a>
          <a href="#report-h">Report</a>
          <a href="#news-h">News</a>
        </nav>
      </section>

      <div className="layout">
        <div>
          <PriceChart ticker={ticker} initial={prices} />
          <FinancialsTable quarterly={quarterly} annual={annual} />

          <section className="section report" aria-labelledby="report-h">
            <header><h2 id="report-h">From the annual report</h2></header>
            {report ? (
              <>
                <p className="small muted" style={{ marginBottom: "0.75rem" }}>
                  <a href={report.url} target="_blank" rel="noopener noreferrer">{report.title}</a>
                  {report.fiscal_period ? `, ${report.fiscal_period}` : ""}
                </p>
                <p className="summary">{report.summary}</p>
                {report.key_points.length > 0 && (
                  <>
                    <h3>Key points</h3>
                    <ul>
                      {report.key_points.map((p) => (
                        <li key={p.point}>{p.point} <span className="pages">{pageRef(p.pages)}</span></li>
                      ))}
                    </ul>
                  </>
                )}
                {report.risks.length > 0 && (
                  <>
                    <h3>Risks the company describes</h3>
                    <ul>
                      {report.risks.map((p) => (
                        <li key={p.point}>{p.point} <span className="pages">{pageRef(p.pages)}</span></li>
                      ))}
                    </ul>
                  </>
                )}
                <p className="ai-note">
                  Summarised by AI from the report’s own text. Every figure above appears in the report, and page
                  numbers refer to the PDF. Check the report before relying on it.
                </p>
              </>
            ) : (
              <p className="empty-state">No report has been summarised for this company yet.</p>
            )}
          </section>

          <NewsList ticker={ticker} initial={news} />
        </div>

        <aside className="aside" aria-label="Key numbers and update">
          <section className="section" aria-labelledby="key-h">
            <header><h2 id="key-h">Key numbers</h2></header>
            {summary ? (
              <dl className="metrics">
                {KEY_ORDER.map((code) => metrics.get(code)).filter(Boolean).map((m) => (
                  <div key={m!.code}>
                    <dt>{m!.label}</dt>
                    <dd className="num"><Flash value={metricValue(m!.unit, m!.value)} /></dd>
                    {(m!.basis || m!.note) && (
                      <span className="basis">{m!.value == null ? m!.note : `Based on ${m!.basis}`}</span>
                    )}
                  </div>
                ))}
              </dl>
            ) : (
              <p className="empty-state">Key numbers aren’t available right now.</p>
            )}
            <p className="source">Worked out from the latest stored price and reported results.</p>
          </section>

          <RefreshPanel ticker={ticker} lastJob={jobs?.jobs[0] ?? null} autoStart={firstLook} />

          {reports && reports.documents.length > 0 && (
            <section className="section" aria-labelledby="docs-h">
              <header><h2 id="docs-h">Reports and filings</h2></header>
              <ul className="docs">
                {reports.documents.slice(0, 8).map((d) => (
                  <li key={d.document_id}>
                    <a href={d.url} target="_blank" rel="noopener noreferrer">{d.title}</a>
                    <span className="muted">
                      {DOC_TYPES[d.document_type] ?? d.document_type}
                      {d.publication_date ? `, ${fmtDate(d.publication_date)}` : ""}
                      {d.page_count ? `, ${d.page_count} pages` : ""}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </div>
    </>
  );
}

function pageRef(pages: number[]): string {
  if (pages.length === 0) return "";
  const lo = Math.min(...pages), hi = Math.max(...pages);
  return lo === hi ? `(p. ${lo})` : pages.length === hi - lo + 1 ? `(pp. ${lo}–${hi})` : `(pp. ${pages.join(", ")})`;
}
