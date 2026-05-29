"""Dispatch adapter for company-specific Playwright scrapers.

Each company in companies.yaml with adapter=custom_playwright references a
module name. We dynamically import scraper.adapters.custom_modules.<module>
and call its `scrape(cfg, page) -> list[Posting]` function.

Custom modules share a single Playwright browser instance for efficiency —
the orchestrator passes us a `page` factory via the context dict.
"""

from __future__ import annotations

import importlib
import logging
from typing import Iterable

from ..base import AdapterError, BaseAdapter, Posting

log = logging.getLogger(__name__)


class CustomPlaywrightAdapter(BaseAdapter):
    name = "custom_playwright"

    # The orchestrator sets this before calling fetch().
    page_factory = None  # type: ignore[assignment]

    def fetch(self) -> Iterable[Posting]:
        module_name = self.cfg.get("module")
        if not module_name:
            raise AdapterError(f"{self.company}: custom_playwright needs 'module'")

        if self.page_factory is None:
            raise AdapterError(
                f"{self.company}: page_factory not injected by orchestrator"
            )

        try:
            mod = importlib.import_module(
                f"scraper.adapters.custom_modules.{module_name}"
            )
        except ImportError as e:
            raise AdapterError(
                f"{self.company}: custom module '{module_name}' not found: {e}"
            ) from e

        scrape = getattr(mod, "scrape", None)
        if not callable(scrape):
            raise AdapterError(
                f"{self.company}: module '{module_name}' lacks scrape()"
            )

        page = self.page_factory()
        try:
            postings = scrape(self.cfg, page, self) or []
        except Exception as e:  # noqa: BLE001
            raise AdapterError(
                f"{self.company}: custom scraper raised: {type(e).__name__}: {e}"
            ) from e
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001
                pass

        log.info(
            "custom_playwright(%s): %s -> %d raw jobs",
            module_name,
            self.company,
            len(postings),
        )
        for p in postings:
            yield p
