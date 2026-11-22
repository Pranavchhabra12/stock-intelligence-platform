"use client";

import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";

import { browserApi, type SearchResult } from "@/lib/api";

function tickerOf(r: SearchResult): string {
  const nse = r.listings.find((l) => l.exchange === "NSE");
  return nse?.symbol ?? r.listings[0]?.exchange_code ?? r.listings[0]?.symbol ?? r.company_id;
}

export default function SearchBox({ compact = false, autoFocus = false }: { compact?: boolean; autoFocus?: boolean }) {
  const router = useRouter();
  const id = useId();
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const query = q.trim();
    if (query.replace(/\W/g, "").length < 2) {
      setResults(null);
      setError(null);
      return;
    }
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      try {
        const body = await browserApi<{ results: SearchResult[] }>(
          `/stocks/search?q=${encodeURIComponent(query)}&limit=6`, { signal: controller.signal });
        setResults(body.results);
        setActive(0);
        setError(null);
      } catch (err) {
        if ((err as Error).name !== "AbortError") setError("Search isn't available right now. Try again shortly.");
      }
    }, 180);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [q]);

  useEffect(() => {
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setResults(null);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (r: SearchResult) => {
    setResults(null);
    setQ("");
    router.push(`/stocks/${encodeURIComponent(tickerOf(r))}`);
  };

  const onKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!results?.length) {
      if (e.key === "Escape") setResults(null);
      return;
    }
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => (a + 1) % results.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a - 1 + results.length) % results.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      go(results[active]);
    } else if (e.key === "Escape") {
      setResults(null);
    }
  };

  const open = results !== null || error !== null;

  return (
    <div className={`search${compact ? " compact" : ""}`} ref={box}>
      <label htmlFor={`${id}-q`} className="visually-hidden">Search companies</label>
      <input
        id={`${id}-q`}
        type="search"
        role="combobox"
        aria-expanded={open}
        aria-controls={`${id}-list`}
        aria-autocomplete="list"
        aria-activedescendant={results?.length ? `${id}-opt-${active}` : undefined}
        autoComplete="off"
        spellCheck={false}
        autoFocus={autoFocus}
        placeholder={compact ? "Search any NSE company" : "Search any NSE company by name or symbol"}
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={onKey}
      />
      {open && (
        <ul className="search-results" id={`${id}-list`} role="listbox">
          {error && <li><span className="empty">{error}</span></li>}
          {results?.length === 0 && (
            <li><span className="empty">No listed company matches “{q.trim()}”. Try its NSE symbol.</span></li>
          )}
          {results?.map((r, i) => (
            <li key={r.company_id} id={`${id}-opt-${i}`} role="option" aria-selected={i === active}>
              <a href={`/stocks/${encodeURIComponent(tickerOf(r))}`}
                 onClick={(e) => { e.preventDefault(); go(r); }}
                 onMouseEnter={() => setActive(i)}>
                <span>
                  {r.company_name}
                  {r.is_tracked && <span className="in-pbi">In Power BI</span>}
                </span>
                <span className="tick">{r.listings.map((l) => l.exchange === "BSE" ? l.exchange_code : l.symbol)
                  .filter(Boolean).join(" / ")}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
