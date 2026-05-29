"""Generic fallback: open careers_url, scroll, harvest all anchor tags whose
text contains an intern-keyword. Crude but works as a safety net.

This is the module loaded when a company's specific module isn't worth
writing yet — but I still want SOMETHING from their careers page.
"""

from __future__ import annotations

from urllib.parse import urljoin

from . import safe_goto, scroll_to_load

INTERN_HINTS = ("intern", "internship", "praktik", "stagiaire", "stage", "becari", "practic", "student")


def scrape(cfg, page, adapter):
    careers = cfg.get("careers_url")
    if not careers or not safe_goto(page, careers, timeout=40_000):
        return []

    # Best-effort: dismiss cookie banners.
    for sel in [
        "button:has-text('Accept')",
        "button:has-text('Accept all')",
        "button:has-text('Alle akzeptieren')",
        "button:has-text('I agree')",
        "button#onetrust-accept-btn-handler",
    ]:
        try:
            page.locator(sel).first.click(timeout=1500)
            break
        except Exception:  # noqa: BLE001
            pass

    scroll_to_load(page, max_scrolls=10)

    # Get every anchor and filter by intern-hint in text.
    raw = page.eval_on_selector_all(
        "a",
        "els => els.map(e => [e.innerText.trim(), e.href || ''])",
    ) or []

    postings = []
    seen_urls = set()
    for text, href in raw:
        if not text or not href:
            continue
        low = text.lower()
        if not any(h in low for h in INTERN_HINTS):
            continue
        if href in seen_urls:
            continue
        seen_urls.add(href)

        postings.append(
            adapter._mk(
                title=text[:200],
                url=urljoin(careers, href),
                location_raw="",
                description_snippet="(scraped from career page link text only — visit URL for details)",
            )
        )

    return postings
