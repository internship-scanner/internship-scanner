"""Workday CXS (Customer Experience Self-service) jobs endpoint.

Most Workday-hosted boards expose:
  POST {host}/wday/cxs/{tenant}/{site}/jobs

Body: {"appliedFacets": {}, "limit": 20, "offset": N, "searchText": ""}

We filter for internships server-side via the "Job Family" / "Job Type" facets
when the search text "intern" works; if not, we pull more pages and filter in
Python.
"""

from __future__ import annotations

import logging
from typing import Iterable

import requests

from ..base import AdapterError, BaseAdapter, Posting

log = logging.getLogger(__name__)

PAGE = 20
MAX_PAGES = 25  # safety cap = 500 listings per company


class WorkdayAdapter(BaseAdapter):
    name = "workday"

    def fetch(self) -> Iterable[Posting]:
        host = self.cfg.get("host", "").rstrip("/")
        tenant = self.cfg.get("tenant")
        site = self.cfg.get("site")
        if not (host and tenant and site):
            raise AdapterError(
                f"{self.company}: workday needs host/tenant/site in config"
            )

        url = f"{host}/wday/cxs/{tenant}/{site}/jobs"
        session = requests.Session()
        session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "internship-scanner/1.0 (+github actions)",
            }
        )

        seen = 0
        for page in range(MAX_PAGES):
            offset = page * PAGE
            body = {
                "appliedFacets": {},
                "limit": PAGE,
                "offset": offset,
                "searchText": "intern",
            }
            try:
                resp = session.post(url, json=body, timeout=30)
            except requests.RequestException as e:
                raise AdapterError(
                    f"{self.company}: Workday request failed: {e}"
                ) from e

            if resp.status_code == 404:
                raise AdapterError(f"{self.company}: Workday endpoint 404 {url}")
            if not resp.ok:
                raise AdapterError(
                    f"{self.company}: Workday {resp.status_code} on page {page}"
                )

            data = resp.json()
            postings = data.get("jobPostings", []) or []
            if not postings:
                break

            for j in postings:
                yield self._convert(j, host)

            seen += len(postings)
            total = data.get("total", seen)
            if seen >= total:
                break

        log.info("workday: %s -> %d raw jobs", self.company, seen)

    def _convert(self, j: dict, host: str) -> Posting:
        title = (j.get("title") or "").strip()
        path = j.get("externalPath") or ""
        url = f"{host}{path}" if path else host
        loc_raw = j.get("locationsText") or j.get("location") or ""
        posted = j.get("postedOn", "") or ""

        city, country = loc_raw, ""
        if "," in loc_raw:
            parts = [p.strip() for p in loc_raw.split(",")]
            city = parts[0]
            country = parts[-1]

        return self._mk(
            title=title,
            url=url,
            location_raw=loc_raw,
            city=city,
            country=country,
            remote="remote" in loc_raw.lower(),
            posted_at=posted[:10] if isinstance(posted, str) else "",
        )
