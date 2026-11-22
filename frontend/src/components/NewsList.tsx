"use client";

import { useState } from "react";

import { browserApi, type News, type NewsArticle, type Sentiment } from "@/lib/api";
import { ago } from "@/lib/format";

type Filter = "all" | Sentiment;

export default function NewsList({ ticker, initial }: { ticker: string; initial: News | null }) {
  const [articles, setArticles] = useState<NewsArticle[]>(initial?.articles ?? []);
  const [cursor, setCursor] = useState<string | null>(initial?.next_before ?? null);
  const [filter, setFilter] = useState<Filter>("all");
  const [loading, setLoading] = useState(false);
  const [failed, setFailed] = useState(false);

  const shown = filter === "all" ? articles : articles.filter((a) => a.sentiment === filter);

  const loadMore = async () => {
    if (!cursor) return;
    setLoading(true);
    setFailed(false);
    try {
      const body = await browserApi<News>(
        `/stocks/${encodeURIComponent(ticker)}/news?limit=20&before=${encodeURIComponent(cursor)}`);
      setArticles((a) => [...a, ...body.articles]);
      setCursor(body.next_before);
    } catch {
      setFailed(true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <section className="section" aria-labelledby="news-h">
      <header>
        <h2 id="news-h">News and filings</h2>
        <div className="choice" role="group" aria-label="Filter by tone">
          {(["all", "positive", "neutral", "negative"] as Filter[]).map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}>
              {f === "all" ? "All" : f[0].toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </header>

      {articles.length === 0 ? (
        <p className="empty-state">No news collected for this company yet. Refresh it to look for the latest headlines.</p>
      ) : shown.length === 0 ? (
        <p className="empty-state">No {filter} stories among the {articles.length} loaded.</p>
      ) : (
        <ul className="news">
          {shown.map((a) => (
            <li key={a.article_id}>
              <span className="mark" data-tone={a.sentiment ?? "none"} aria-hidden="true" />
              <div>
                <a className="headline" href={a.url} target="_blank" rel="noopener noreferrer">{a.headline}</a>
                <p className="meta">
                  <span>{a.publisher ?? a.source}</span>
                  {a.published_at && <time dateTime={a.published_at}>{ago(a.published_at)}</time>}
                  <span className="tone-word" data-tone={a.sentiment ?? "none"}>
                    {a.sentiment ? `Tone: ${a.sentiment}` : "Not rated yet"}
                  </span>
                </p>
              </div>
            </li>
          ))}
        </ul>
      )}

      {cursor && (
        <button type="button" className="more" onClick={loadMore} disabled={loading}>
          {loading ? "Loading…" : "Show older stories"}
        </button>
      )}
      {failed && <p className="small down" role="alert">Couldn’t load older stories. Try again.</p>}
      <p className="source">
        Headlines link to the original publisher; only the headline is shown here. Tone is rated by AI for this
        company and describes the news, not where the price will go.
      </p>
    </section>
  );
}
