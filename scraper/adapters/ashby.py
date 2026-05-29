"""Ashby public job board API.

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{slug}
Query: ?includeCompensation=true (compensation is sometimes present, harmless).
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Iterable

import requests

from ..base import AdapterError, BaseAdapter, Posting

log = logging.getLogger(__name__)

API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


class AshbyAdapter(BaseAdapter):
    name = "ashby"

    def fetch(self) -> Iterable[Posting]:
        slug = self.cfg.get("slug")
        if not slug:
            raise AdapterError(f"{self.company}: missing 'slug'")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        try:
            resp = requests.get(
                API.format(slug=slug),
                params={"includeCompensation": "true"},
                headers=headers,
                timeout=30,
            )
        except requests.RequestException as e:
            raise AdapterError(f"{self.company}: Ashby failed: {e}") from e

        if resp.status_code == 404:
            raise AdapterError(f"{self.company}: Ashby slug '{slug}' not found")
        if not resp.ok:
            raise AdapterError(f"{self.company}: Ashby returned {resp.status_code}")

        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"{self.company}: Ashby non-JSON: {e}") from e

        jobs = data.get("jobs", []) or []
        log.info("ashby: %s -> %d raw jobs", self.company, len(jobs))

        for j in jobs:
            yield self._convert(j)

    def _convert(self, j: dict) -> Posting:
        title = j.get("title", "").strip()
        url = j.get("jobUrl", "") or j.get("applyUrl", "")
        loc_raw = j.get("locationName", "") or ""

        desc_html = j.get("descriptionHtml", "") or j.get("descriptionPlain", "") or ""
        text = unescape(re.sub(r"<[^>]+>", " ", desc_html))
        snippet = re.sub(r"\s+", " ", text).strip()[:5000]

        city, country = loc_raw, ""
        if "," in loc_raw:
            parts = [x.strip() for x in loc_raw.split(",")]
            city = parts[0]
            country = parts[-1]

        return self._mk(
            title=title,
            url=url,
            location_raw=loc_raw,
            city=city,
            country=country,
            remote=bool(j.get("isRemote")) or "remote" in loc_raw.lower(),
            employment_type=j.get("employmentType", "") or "Internship",
            posted_at=(j.get("publishedDate") or "")[:10],
            description_snippet=snippet,
        )
