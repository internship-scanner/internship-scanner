"""Shared types and the BaseAdapter that all scrapers implement."""

from __future__ import annotations

import abc
import dataclasses
import datetime as dt
import hashlib
import logging
from typing import Any, Iterable

log = logging.getLogger(__name__)


@dataclasses.dataclass
class Posting:
    """Normalized internship posting. All adapters must yield instances of this."""

    # Identity
    id: str                      # stable hash, used for dedup in the UI
    company: str
    tier: str

    # Role
    title: str
    position_category: str = ""
    employment_type: str = "Internship"

    # Location — cities[] and city_countries[] are parallel arrays so the UI
    # can render "Berlin, Germany · Paris, France" for cross-country postings.
    # country is the "primary" (first) country, used for the country filter.
    cities: list[str] = dataclasses.field(default_factory=list)  # e.g. ["London", "Dublin"]
    city_countries: list[str] = dataclasses.field(default_factory=list)  # parallel to cities
    country: str = ""            # primary country (English display name)
    location_raw: str = ""       # original string from the source for debugging
    remote: bool = False

    # Timing — all ISO dates internally; frontend renders DD-MM-YYYY.
    posted_at: str = ""          # ISO date or ISO datetime
    deadline: str = ""           # ISO date or ISO datetime
    start_date: str = ""         # ISO date or ISO datetime
    duration_value: int | None = None   # e.g. 12
    duration_unit: str = ""             # "weeks" or "months"
    duration_weeks: int | None = None   # normalized for numeric range filter

    # Content
    keywords: list[str] = dataclasses.field(default_factory=list)
    description: str = ""        # full plain-text description (for keyword extraction)

    # Links
    url: str = ""
    apply_url: str = ""

    # Metadata
    source_adapter: str = ""
    scraped_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def make_posting_id(company: str, url: str, title: str) -> str:
    """Stable id across runs. URL changes invalidate the id on purpose so we
    re-track if the canonical link changes."""
    h = hashlib.sha1(f"{company}|{url}|{title}".encode("utf-8")).hexdigest()
    return h[:16]


class AdapterError(Exception):
    """Raised by adapters on unrecoverable errors. The orchestrator catches
    these and moves on to the next company."""


class BaseAdapter(abc.ABC):
    """Subclass and implement fetch(). Return an iterable of Posting objects.

    Adapters do not filter — filtering happens centrally in run.py so the
    pipeline can report 'company X yielded N raw, M after filter'.
    """

    name: str = "base"

    def __init__(self, company_cfg: dict[str, Any]):
        self.cfg = company_cfg
        self.company = company_cfg["name"]
        self.tier = company_cfg.get("tier", "")

    @abc.abstractmethod
    def fetch(self) -> Iterable[Posting]:
        ...

    # ------------------------------------------------------------------ utils

    def _now(self) -> str:
        return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")

    def _mk(self, *, title: str, url: str, **kwargs: Any) -> Posting:
        # ----- backward-compat shims for older adapters ---------------------
        # Older adapters pass city=, country=, description_snippet=; we now
        # derive city/country from `location_raw` in the orchestrator, and
        # the full content goes into `description`. So we silently absorb
        # the legacy field names here.
        kwargs.pop("city", None)
        kwargs.pop("country", None)
        if "description_snippet" in kwargs and "description" not in kwargs:
            kwargs["description"] = kwargs.pop("description_snippet")
        else:
            kwargs.pop("description_snippet", None)
        # also drop deprecated `duration` (free-text) — duration_value/unit
        # are the new fields and the orchestrator derives them.
        if "duration" in kwargs and "duration_value" not in kwargs:
            # Keep the raw text on description so it can still be parsed.
            existing = kwargs.get("description", "") or ""
            kwargs["description"] = (existing + "\n" + str(kwargs.pop("duration"))).strip()
        else:
            kwargs.pop("duration", None)

        return Posting(
            id=make_posting_id(self.company, url, title),
            company=self.company,
            tier=self.tier,
            title=title,
            url=url,
            apply_url=kwargs.pop("apply_url", url),
            source_adapter=self.name,
            scraped_at=self._now(),
            **kwargs,
        )
