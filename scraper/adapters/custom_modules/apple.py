"""Apple Jobs.

Apple's site uses a search API at:
  https://jobs.apple.com/api/role/search

Filter for internships via team=internships-STDNT-INTRN.
"""

from __future__ import annotations

import requests

API = "https://jobs.apple.com/api/role/search"


def scrape(cfg, page, adapter):
    postings = []
    seen = set()

    for pg in range(1, 11):
        body = {
            "query": "",
            "filters": {
                "range": {"standardWeeklyHours": {"start": "0", "end": "40"}},
                "team": [{"teamCode": "STDNT", "teamName": "internships-STDNT-INTRN"}],
            },
            "page": pg,
            "locale": "en-us",
            "sort": "newest",
        }
        try:
            r = requests.post(
                API,
                json=body,
                headers={
                    "User-Agent": "internship-scanner/1.0",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                timeout=25,
            )
        except requests.RequestException:
            break

        if not r.ok:
            break

        try:
            data = r.json()
        except ValueError:
            break

        jobs = data.get("searchResults") or []
        if not jobs:
            break

        for j in jobs:
            pid = j.get("positionId")
            if pid in seen:
                continue
            seen.add(pid)

            title = j.get("postingTitle") or ""
            locs = j.get("locations") or []
            loc_strs = [l.get("name", "") for l in locs if isinstance(l, dict)]
            loc_raw = "; ".join(loc_strs[:3])

            slug = (j.get("transformedPostingTitle") or "").lower().replace(" ", "-")
            url = f"https://jobs.apple.com/en-us/details/{pid}/{slug}" if pid else ""

            postings.append(
                adapter._mk(
                    title=title,
                    url=url,
                    location_raw=loc_raw,
                    city=loc_strs[0].split(",")[0].strip() if loc_strs else "",
                    country=loc_strs[0].split(",")[-1].strip() if loc_strs and "," in loc_strs[0] else "",
                    posted_at=(j.get("postDateInGMT") or "")[:10],
                    description_snippet=(j.get("jobSummary") or "")[:5000],
                )
            )

    return postings
