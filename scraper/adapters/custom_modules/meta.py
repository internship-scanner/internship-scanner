"""Meta Careers (metacareers.com).

URL: https://www.metacareers.com/jobs/?roles[0]=Internship

Page is heavily JS but exposes job links as anchors with /jobs/<id>/ paths.
"""

from __future__ import annotations

from . import safe_goto, scroll_to_load, click_until


def scrape(cfg, page, adapter):
    if not safe_goto(page, cfg["careers_url"], timeout=45_000):
        return []

    # Accept cookies.
    for sel in [
        "button[data-cookiebanner='accept_button']",
        "button:has-text('Allow all cookies')",
        "button:has-text('Accept')",
    ]:
        try:
            page.locator(sel).first.click(timeout=1500)
            break
        except Exception:
            pass

    # Load more pages (Meta uses a "Show more" button on some viewports).
    scroll_to_load(page, max_scrolls=15)
    click_until(page, "button:has-text('Show more')", max_clicks=10)
    scroll_to_load(page, max_scrolls=10)

    rows = page.eval_on_selector_all(
        "a[href*='/jobs/']",
        """els => els.map(e => {
            const card = e.closest('div, li') || e;
            const txt = (e.innerText || '').trim();
            const loc = (card.querySelector('div[role="text"], span') || {}).innerText || '';
            return [txt, e.href, loc.trim()];
        })""",
    ) or []

    postings = []
    seen = set()
    for title, href, loc_raw in rows:
        if not title or not href or href in seen:
            continue
        seen.add(href)
        postings.append(
            adapter._mk(
                title=title[:200],
                url=href,
                location_raw=loc_raw[:200],
                city=loc_raw.split(",")[0].strip() if loc_raw else "",
                country=loc_raw.split(",")[-1].strip() if "," in loc_raw else "",
                remote="remote" in loc_raw.lower(),
            )
        )
    return postings
