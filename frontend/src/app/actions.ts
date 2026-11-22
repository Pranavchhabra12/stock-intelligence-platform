"use server";

import { updateTag } from "next/cache";

import { api, type CompanyDetail, companyTag, type Job, OVERVIEW_TAG } from "@/lib/api";

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TICKER = /^[A-Za-z0-9&.\-]{1,20}$/;

/** After a refresh finishes, drop the cached copy of that company's data so the page shows
 * the new figures straight away. Only works for a real refresh of that company that finished
 * in the last ten minutes, so it can't be used to empty the cache at will. */
export async function showFreshData(ticker: string, jobId: string): Promise<boolean> {
  if (!TICKER.test(ticker) || !UUID.test(jobId)) return false;
  const [job, company] = await Promise.all([
    api<Job>(`/jobs/${jobId}`, 0).catch(() => null),
    api<CompanyDetail>(`/stocks/${encodeURIComponent(ticker)}`, 3600).catch(() => null),
  ]);
  if (!job || !company || job.company_id !== company.company_id) return false;
  if (job.status === "pending" || job.status === "running" || !job.finished_at) return false;
  if (Date.now() - Date.parse(job.finished_at) > 10 * 60 * 1000) return false;
  updateTag(companyTag(ticker));
  updateTag(OVERVIEW_TAG);
  return true;
}

/** After a company is added to Power BI, show it on the home page and its page at once.
 * Only for a company added in the last ten minutes, so it can't be used to empty the cache. */
export async function showTrackedCompany(ticker: string): Promise<boolean> {
  if (!TICKER.test(ticker)) return false;
  const company = await api<CompanyDetail>(`/stocks/${encodeURIComponent(ticker)}`, 0).catch(() => null);
  if (!company?.is_tracked || !company.tracked_at) return false;
  if (Date.now() - Date.parse(company.tracked_at) > 10 * 60 * 1000) return false;
  updateTag(companyTag(ticker));
  updateTag(OVERVIEW_TAG);
  return true;
}
