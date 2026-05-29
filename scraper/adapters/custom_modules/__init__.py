"""Shared helpers for company-specific Playwright scrapers.

Each module here exposes:

    def scrape(cfg: dict, page: Page, adapter) -> list[Posting]:
        ...

`page` is a Playwright page already opened, with sensible defaults.
`adapter._mk(title=..., url=..., ...)` creates a Posting with the company/tier
fields pre-filled.
"""

from __future__ import annotations

import logging
import time
from typing import Callable

log = logging.getLogger(__name__)


def safe_goto(page, url: str, wait_until: str = "domcontentloaded", timeout: int = 30_000) -> bool:
    """Navigate with a forgiving timeout, return False on failure."""
    try:
        page.goto(url, wait_until=wait_until, timeout=timeout)
        return True
    except Exception as e:  # noqa: BLE001
        log.warning("goto failed for %s: %s", url, e)
        return False


def scroll_to_load(page, *, max_scrolls: int = 8, pause: float = 0.6) -> None:
    """Scroll to the bottom repeatedly to trigger lazy-load."""
    last_height = -1
    for _ in range(max_scrolls):
        page.evaluate("window.scrollTo(0, document.body.scrollHeight);")
        time.sleep(pause)
        h = page.evaluate("document.body.scrollHeight")
        if h == last_height:
            break
        last_height = h


def click_until(page, selector: str, *, max_clicks: int = 20, pause: float = 0.6) -> int:
    """Click 'load more' style buttons until they disappear or max_clicks."""
    clicks = 0
    for _ in range(max_clicks):
        try:
            btn = page.locator(selector).first
            if not btn.is_visible(timeout=1500):
                break
            btn.click(timeout=3000)
            clicks += 1
            time.sleep(pause)
        except Exception:  # noqa: BLE001
            break
    return clicks


def collect_links(page, anchor_selector: str, *, attr: str = "href") -> list[tuple[str, str]]:
    """Return [(text, url), ...] for every matching anchor."""
    return page.eval_on_selector_all(
        anchor_selector,
        f"els => els.map(e => [e.innerText.trim(), e.getAttribute('{attr}') || ''])",
    ) or []
