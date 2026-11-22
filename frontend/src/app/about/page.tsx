import type { Metadata } from "next";

export const metadata: Metadata = { title: "How it works" };

export default function About() {
  return (
    <article className="prose">
      <h1>How it works</h1>
      <p>
        Stock Intelligence brings together the things you would otherwise look up in five places: the share price,
        quarterly and annual results, exchange filings, news coverage and what the annual report says. It covers a
        small set of companies listed on NSE and BSE and is an educational project, not investment advice.
      </p>

      <h2>Where the data comes from</h2>
      <ul>
        <li>Prices and results: Yahoo Finance, with Upstox and EODHD as fallbacks when it has no data. Each stored price records which source supplied it.</li>
        <li>News: Economic Times and Mint feeds and Google News search. Only the headline and a link are kept; you read the story on the publisher’s site.</li>
        <li>Filings: BSE’s official announcement, results and annual-report feeds.</li>
        <li>Reports: annual reports from the companies’ own investor pages.</li>
      </ul>

      <h2>How the numbers are worked out</h2>
      <p>
        Market cap, P/E, P/B, dividend yield, ROE and growth are calculated each time a page loads, from the latest
        stored price and the reported results. Each one says what it was based on: the last four quarters when they
        are all reported, otherwise the latest full year. If a figure can’t be worked out honestly, the page says why
        instead of guessing.
      </p>

      <h2>What the AI does</h2>
      <p>
        Google’s Gemini rates each headline as positive, neutral or negative for the company it is about. A day’s tone
        is the average for that day, weighted by how clearly each story is about the company, and once a day is
        scored it is never changed. Tone describes the news, not where the price is going.
      </p>
      <p>
        Gemini also summarises annual reports. It only sees the report’s own text, every point must cite the pages it
        comes from, and any point using a figure that isn’t in the report is thrown away. Summaries can still miss
        things, so each one links to the full report.
      </p>

      <h2>How fresh it is</h2>
      <p>
        Prices, results and news update every weekday at 7:30 pm India time, after the market closes. News, filings
        and tone also update every hour from 9 am to 7 pm. You can refresh any company yourself from its page; a
        refresh from the last 15 minutes is reused rather than repeated.
      </p>
    </article>
  );
}
