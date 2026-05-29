"""Greenhouse public board API.

Endpoint: https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true

Returns all jobs for a public board. We pull `content=true` so we get the
job description for keyword matching. Auth-less.
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Iterable

import requests

from ..base import AdapterError, BaseAdapter, Posting

log = logging.getLogger(__name__)

API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"


class GreenhouseAdapter(BaseAdapter):
    name = "greenhouse"

    def fetch(self) -> Iterable[Posting]:
        slug = self.cfg.get("slug")
        if not slug:
            raise AdapterError(f"{self.company}: missing 'slug'")

        url = API.format(slug=slug)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Accept": "application/json",
        }
        try:
            resp = requests.get(url, params={"content": "true"}, headers=headers, timeout=30)
        except requests.RequestException as e:
            raise AdapterError(f"{self.company}: GH request failed: {e}") from e

        if resp.status_code == 404:
            raise AdapterError(f"{self.company}: GH board '{slug}' not found (404)")
        if not resp.ok:
            raise AdapterError(
                f"{self.company}: GH returned {resp.status_code} for slug '{slug}'"
            )

        try:
            data = resp.json()
        except ValueError as e:
            raise AdapterError(f"{self.company}: GH non-JSON response: {e}") from e

        jobs = data.get("jobs", []) or []
        log.info("greenhouse: %s -> %d raw jobs", self.company, len(jobs))

        for j in jobs:
            yield self._convert(j)

    # ------------------------------------------------------------------

    def _convert(self, j: dict) -> Posting:
        title = j.get("title", "").strip()
        url = j.get("absolute_url", "")
        loc_raw = (j.get("location") or {}).get("name", "") or ""

        # Description is HTML; strip tags for snippet.
        content_html = j.get("content", "") or ""
        text = unescape(re.sub(r"<[^>]+>", " ", content_html))
        text = re.sub(r"\s+", " ", text).strip()
        snippet = text[:5000]

        # Split "City, Country" if possible.
        city, country = "", ""
        if "," in loc_raw:
            parts = [p.strip() for p in loc_raw.split(",")]
            city = parts[0]
            country = parts[-1]
        else:
            city = loc_raw

        return self._mk(
            title=title,
            url=url,
            location_raw=loc_raw,
            city=city,
            country=country,
            remote="remote" in loc_raw.lower(),
            posted_at=(j.get("updated_at") or "")[:10],
            description_snippet=snippet,
        )
