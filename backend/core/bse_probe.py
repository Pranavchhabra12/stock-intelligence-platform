"""One-off check: can this server reach BSE's per-company announcements API?

GitHub's servers get "Access Denied" from it. Runs once at start-up, only when the
PROBE_BSE environment variable is "1", and writes what BSE answered to the log.
Remove once the question is settled.
"""

from __future__ import annotations

import logging
import os
import threading

import httpx

logger = logging.getLogger("backend.bse_probe")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/131.0 Safari/537.36")
URLS = {
    "announcements": "https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w?pageno=1&strCat=-1"
                     "&strPrevDate=20261101&strScrip=500180&strSearch=P&strToDate=20261122&strType=C&subcategory=-1",
    "annual_reports": "https://api.bseindia.com/BseIndiaAPI/api/AnnualReport_New/w?scripcode=500180",
}


def _probe() -> None:
    headers = {"User-Agent": UA, "Referer": "https://www.bseindia.com/", "Origin": "https://www.bseindia.com",
               "Accept": "application/json, text/plain, */*"}
    with httpx.Client(timeout=30, headers=headers) as client:
        for name, url in URLS.items():
            try:
                r = client.get(url)
                rows = None
                if "json" in r.headers.get("content-type", ""):
                    body = r.json()
                    rows = {k: len(v) for k, v in body.items() if isinstance(v, list)} if isinstance(body, dict) \
                        else len(body) if isinstance(body, list) else None
                logger.warning("bse_probe", extra={"probe": name, "status": r.status_code,
                                                   "content_type": r.headers.get("content-type"), "rows": rows,
                                                   "start": r.text[:300]})
            except Exception as exc:  # noqa: BLE001 - a probe reports, it never breaks start-up
                logger.warning("bse_probe", extra={"probe": name, "error": f"{type(exc).__name__}: {exc}"})


def maybe_start() -> None:
    if os.environ.get("PROBE_BSE") == "1":
        threading.Thread(target=_probe, name="bse-probe", daemon=True).start()
