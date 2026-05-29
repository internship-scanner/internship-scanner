"""Microsoft Careers.

Their site is fronted by a public JSON endpoint:
  https://gcsservices.careers.microsoft.com/search/api/v1/search

We can call it directly without Playwright. We still need Playwright-compatible
signature so the dispatcher can call us — but we ignore the page argument.
"""

from __future__ import annotations

import requests

API = "https://gcsservices.careers.microsoft.com/search/api/v1/search"
PAGE_SIZE = 20


def scrape(cfg, page, adapter):
    postings = []
    seen = set()

    for pg in range(1, 21):  # cap at ~400 results
        params = {
            "q": "intern",
            "l": "en_us",
            "pg": pg,
            "pgSz": PAGE_SIZE,
            "o": "Relevance",
            "flt": "true",
        }
        try:
            r = requests.get(
                API,
                params=params,
                headers={"User-Agent": "internship-scanner/1.0"},
                timeout=25,
            )
        except requests.RequestException:
            break
        if not r.ok:
            break
        data = r.json()
        jobs = (((data.get("operationResult") or {}).get("result")) or {}).get("jobs") or []
        if not jobs:
            break

        for j in jobs:
            jid = j.get("jobId")
            if jid in seen:
                continue
            seen.add(jid)

            title = j.get("title") or ""
            loc = j.get("primaryLocation") or ""
            locs = j.get("properties", {}).get("locations") or []
            if locs and not loc:
                loc = ", ".join(locs[:3])

            url = f"https://jobs.careers.microsoft.com/global/en/job/{jid}"

            postings.append(
                adapter._mk(
                    title=title,
                    url=url,
                    location_raw=loc,
                    city=loc.split(",")[0].strip() if loc else "",
                    country=loc.split(",")[-1].strip() if "," in loc else "",
                    remote="remote" in loc.lower(),
                    posted_at=(j.get("postingDate") or "")[:10],
                    description_snippet=(j.get("properties", {}).get("description") or "")[:5000],
                )
            )

    return postings
