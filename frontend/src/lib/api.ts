// Types for the FastAPI responses this site uses, and fetch helpers.
// Server components call the backend directly; the browser goes through /api (see next.config.ts).

export type Exchange = "NSE" | "BSE";
export type Sentiment = "positive" | "neutral" | "negative";

export interface Listing {
  listing_id: string;
  exchange: Exchange;
  symbol: string;
  exchange_code: string | null;
  isin: string | null;
}

export interface SearchResult {
  company_id: string;
  company_name: string;
  sector: string | null;
  industry: string | null;
  score: number;
  listings: Listing[];
}

export interface CompanyDetail {
  company_id: string;
  company_name: string;
  legal_name: string | null;
  sector: string | null;
  industry: string | null;
  description: string | null;
  website: string | null;
  listings: Listing[];
}

export interface SourceInfo {
  code: string;
  name: string;
  attribution: string | null;
}

export interface KeyMetric {
  code: string;
  label: string;
  unit: "INR" | "INR_PER_SHARE" | "RATIO" | "PERCENT" | string;
  value: number | null;
  basis: string | null;
  note: string | null;
}

export interface Summary {
  company_id: string;
  company_name: string;
  sector: string | null;
  industry: string | null;
  listing: Listing;
  price: {
    trade_date: string;
    close: number;
    previous_close: number | null;
    change: number | null;
    change_pct: number | null;
    high_52w: number | null;
    low_52w: number | null;
    source: string;
  } | null;
  metrics: KeyMetric[];
  sources: SourceInfo[];
  data_note: string;
}

export interface PriceRow {
  trade_date: string;
  close: number;
  high: number;
  low: number;
  open: number;
  volume: number;
  source: string;
}

export interface Prices {
  listing: Listing;
  price_basis: string | null;
  sources: SourceInfo[];
  count: number;
  prices: PriceRow[];
}

export interface FinancialPeriod {
  label: string;
  period_type: "quarterly" | "annual";
  period_end: string;
  metrics: Record<string, number | null>;
}

export interface Financials {
  period_type: "quarterly" | "annual";
  source: SourceInfo | null;
  metric_definitions: Record<string, { label: string; unit: string }>;
  periods: FinancialPeriod[];
}

export interface NewsArticle {
  article_id: string;
  headline: string;
  url: string;
  publisher: string | null;
  published_at: string | null;
  relevance: number;
  source: string;
  sentiment: Sentiment | null;
  sentiment_score: number | null;
}

export interface News {
  count: number;
  next_before: string | null;
  note: string;
  articles: NewsArticle[];
}

export interface SentimentDay {
  date: string;
  score: number;
  article_count: number;
  positive: number;
  neutral: number;
  negative: number;
}

export interface SentimentHistory {
  days: number;
  overall_score: number | null;
  overall_label: Sentiment | null;
  article_count: number;
  note: string;
  history: SentimentDay[];
}

export interface SummaryPoint {
  point: string;
  pages: number[];
}

export interface ReportSummary {
  document_id: string;
  title: string;
  url: string;
  fiscal_period: string | null;
  summary: string;
  key_points: SummaryPoint[];
  risks: SummaryPoint[];
  model: string;
  created_at: string;
}

export interface Analysis {
  count: number;
  note: string;
  reports: ReportSummary[];
}

export interface CompanyDocument {
  document_id: string;
  document_type: string;
  title: string;
  url: string;
  publication_date: string | null;
  extraction_status: string;
  page_count: number | null;
}

export interface Reports {
  count: number;
  documents: CompanyDocument[];
}

export interface JobStep {
  status: "running" | "completed" | "completed_with_errors" | "failed" | "skipped";
  detail: Record<string, unknown>;
}

export interface Job {
  job_id: string;
  company_id: string | null;
  job_type: string;
  status: "pending" | "running" | "completed" | "completed_with_errors" | "failed";
  steps: Record<string, JobStep>;
  error: string | null;
  requested_at: string;
  finished_at: string | null;
}

export interface RefreshResponse extends Job {
  created: boolean;
  poll_url: string;
}

export interface JobList {
  jobs: Job[];
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

const SERVER_API = (process.env.API_URL ?? "http://localhost:8000").replace(/\/$/, "");

/** Cache tag for everything shown about one company; cleared after a refresh finishes. */
export const companyTag = (ticker: string) => `stock:${ticker.toUpperCase()}`;
export const OVERVIEW_TAG = "overview";

/** Server-side fetch, cached for five minutes (or until its tag is cleared). */
export async function api<T>(path: string, revalidate = 300, tags: string[] = []): Promise<T> {
  const res = await fetch(`${SERVER_API}${path}`, { next: { revalidate, tags } });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new ApiError(res.status, body?.error?.message ?? `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

/** The same call, but a failure becomes null so one broken section can't break the page. */
export async function maybe<T>(path: string, revalidate = 300, tags: string[] = []): Promise<T | null> {
  try {
    return await api<T>(path, revalidate, tags);
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) throw err;
    return null;
  }
}

/** Browser-side fetch through the /api proxy. */
export async function browserApi<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  const body = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, body?.error?.message ?? `Request failed (${res.status})`);
  return body as T;
}
