"""SmartRecruiters public postings API.

Endpoint: https://api.smartrecruiters.com/v1/companies/{slug}/postings
Pagination via offset.
"""

from __future__ import annotations

import logging
from typing import Iterable

import requests

from ..base import AdapterError, BaseAdapter, Posting

log = logging.getLogger(__name__)

API = "https://api.smartrecruiters.com/v1/companies/{slug}/postings"
PAGE_LIMIT = 100


class SmartRecruitersAdapter(BaseAdapter):
    name = "smartrecruiters"

    def fetch(self) -> Iterable[Posting]:
        slug = self.cfg.get("slug")
        if not slug:
            raise AdapterError(f"{self.company}: missing 'slug'")

        offset = 0
        total_seen = 0
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }

        while True:
            try:
                resp = requests.get(
                    API.format(slug=slug),
                    params={"limit": PAGE_LIMIT, "offset": offset},
                    headers=headers,
                    timeout=30,
                )
            except requests.RequestException as e:
                raise AdapterError(
                    f"{self.company}: SmartRecruiters failed: {e}"
                ) from e

            if resp.status_code == 404:
                raise AdapterError(
                    f"{self.company}: SmartRecruiters slug '{slug}' 404"
                )
            if not resp.ok:
                raise AdapterError(
                    f"{self.company}: SmartRecruiters {resp.status_code}"
                )

            data = resp.json()
            items = data.get("content", []) or []
            if not items:
                break

            for j in items:
                yield self._convert(j)

            total_seen += len(items)
            total = data.get("totalFound", total_seen)
            offset += PAGE_LIMIT
            if offset >= total:
                break

        log.info("smartrecruiters: %s -> %d raw jobs", self.company, total_seen)

    def _convert(self, j: dict) -> Posting:
        title = (j.get("name") or "").strip()
        ref = j.get("refNumber") or j.get("id")
        url = (
            f"https://jobs.smartrecruiters.com/{self.cfg['slug']}/{ref}"
            if ref
            else ""
        )

        loc = j.get("location", {}) or {}
        city = loc.get("city", "") or ""
        country = loc.get("country", "") or ""
        region = loc.get("region", "") or ""
        loc_raw = ", ".join(p for p in [city, region, country] if p)

        rs = j.get("releasedDate") or j.get("createdOn") or ""

        return self._mk(
            title=title,
            url=url,
            location_raw=loc_raw,
            city=city,
            country=country,
            remote=bool(loc.get("remote")),
            employment_type=(j.get("typeOfEmployment") or {}).get("label", "")
            or "Internship",
            posted_at=str(rs)[:10],
        )
