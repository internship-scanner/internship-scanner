"""Amazon Jobs (includes AWS).

Public JSON: https://www.amazon.jobs/en/search.json?normalized_country_code[]=...
We pull all internship category roles in Europe.
"""

from __future__ import annotations

import requests

API = "https://www.amazon.jobs/en/search.json"

# ISO 3 country codes used by amazon.jobs.
EU_CODES = [
    "DEU", "GBR", "IRL", "FRA", "ESP", "ITA", "NLD", "POL", "ROU", "CZE",
    "SWE", "NOR", "FIN", "DNK", "AUT", "BEL", "PRT", "GRC", "HUN", "LUX",
    "CHE", "EST", "LVA", "LTU", "BGR", "HRV", "SVN", "SVK", "ISL", "CYP",
    "MLT",
]


def scrape(cfg, page, adapter):
    postings = []
    seen = set()

    offset = 0
    while offset < 800:  # safety
        params = [("normalized_country_code[]", c) for c in EU_CODES] + [
            ("category[]", "Software Development"),
            ("category[]", "Solutions Architect"),
            ("category[]", "Machine Learning Science"),
            ("category[]", "Research Science"),
            ("category[]", "Hardware Development"),
            ("category[]", "Data Science"),
            ("base_query", "intern"),
            ("offset", offset),
            ("result_limit", 100),
            ("sort", "recent"),
        ]
        try:
            r = requests.get(
                API,
                params=params,
                headers={
                    "User-Agent": "internship-scanner/1.0",
                    "Accept": "application/json",
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

        jobs = data.get("jobs") or []
        if not jobs:
            break

        for j in jobs:
            jid = j.get("id_icims") or j.get("id")
            if jid in seen:
                continue
            seen.add(jid)

            url = "https://www.amazon.jobs" + (j.get("job_path") or "")
            postings.append(
                adapter._mk(
                    title=j.get("title") or "",
                    url=url,
                    location_raw=j.get("location") or j.get("normalized_location") or "",
                    city=j.get("city") or "",
                    country=j.get("country_code") or "",
                    posted_at=(j.get("posted_date") or "")[:10],
                    description_snippet=(j.get("description_short") or j.get("basic_qualifications") or "")[:5000],
                )
            )

        offset += len(jobs)
        if len(jobs) < 100:
            break

    return postings
