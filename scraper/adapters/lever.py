"""Lever public postings API.

Endpoint: https://api.lever.co/v0/postings/{slug}?mode=json
"""

from __future__ import annotations

import logging
import re
from html import unescape
from typing import Iterable

import requests

from ..base import AdapterError, BaseAdapter, Posting

log = logging.getLogger(__name__)

API = "https://api.lever.co/v0/postings/{slug}"


class LeverAdapter(BaseAdapter):
    name = "lever"

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
                API.format(slug=slug), params={"mode": "json"},
                headers=headers, timeout=30,
            )
        except requests.RequestException as e:
            raise AdapterError(f"{self.company}: Lever request failed: {e}") from e

        if resp.status_code == 404:
            raise AdapterError(f"{self.company}: Lever slug '{slug}' not found (404)")
        if not resp.ok:
            raise AdapterError(f"{self.company}: Lever returned {resp.status_code}")

        try:
            postings = resp.json()
        except ValueError as e:
            raise AdapterError(f"{self.company}: Lever non-JSON: {e}") from e

        log.info("lever: %s -> %d raw jobs", self.company, len(postings))

        for p in postings:
            yield self._convert(p)

    def _convert(self, p: dict) -> Posting:
        title = p.get("text", "").strip()
        url = p.get("hostedUrl", "") or p.get("applyUrl", "")
        cats = p.get("categories") or {}
        loc_raw = cats.get("location", "") or ""
        commitment = cats.get("commitment", "") or ""

        desc_html = p.get("description", "") or ""
        text = unescape(re.sub(r"<[^>]+>", " ", desc_html))
        snippet = re.sub(r"\s+", " ", text).strip()[:5000]

        city, country = loc_raw, ""
        if "," in loc_raw:
            parts = [x.strip() for x in loc_raw.split(",")]
            city = parts[0]
            country = parts[-1]

        ts = p.get("createdAt")
        posted_at = ""
        if isinstance(ts, (int, float)):
            import datetime as _dt
            posted_at = _dt.datetime.utcfromtimestamp(ts / 1000).date().isoformat()

        return self._mk(
            title=title,
            url=url,
            apply_url=p.get("applyUrl", url),
            location_raw=loc_raw,
            city=city,
            country=country,
            remote="remote" in loc_raw.lower(),
            employment_type=commitment or "Internship",
            posted_at=posted_at,
            description_snippet=snippet,
        )
