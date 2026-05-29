"""Google Careers (careers.google.com).

Their search URL accepts `employment_type=INTERN` and renders results
server-side enough that we can scrape pagination via the URL `page=` param.
"""

from __future__ import annotations

import re
import time
from urllib.parse import urlencode

from . import safe_goto, scroll_to_load

BASE = "https://www.google.com/about/careers/applications/jobs/results/"


def scrape(cfg, page, adapter):
    postings = []
    seen = set()

    # Iterate a handful of pages; Google paginates 20 per page.
    for pg in range(1, 11):
        params = {"employment_type": "INTERN", "page": pg}
        url = f"{BASE}?{urlencode(params)}"
        if not safe_goto(page, url, timeout=40_000):
            break

        # Wait for at least one job card.
        try:
            page.wait_for_selector("a[href*='/jobs/results/']", timeout=8000)
        except Exception:
            break

        scroll_to_load(page, max_scrolls=3)

        cards = page.locator("li:has(a[href*='/jobs/results/'])")
        n = cards.count()
        if n == 0:
            break

        new_this_page = 0
        for i in range(n):
            try:
                card = cards.nth(i)
                title_el = card.locator("h3, h2").first
                title = title_el.inner_text(timeout=1500).strip()
                href = card.locator("a[href*='/jobs/results/']").first.get_attribute("href") or ""
                if not href.startswith("http"):
                    href = "https://www.google.com" + href

                if href in seen:
                    continue
                seen.add(href)
                new_this_page += 1

                # Locations are listed under the title in spans.
                loc_text = ""
                try:
                    loc_text = card.locator("span:has-text(','), span:has-text(';')").first.inner_text(timeout=800)
                except Exception:
                    pass

                postings.append(
                    adapter._mk(
                        title=title,
                        url=href,
                        location_raw=loc_text,
                        city=loc_text.split(",")[0].strip() if loc_text else "",
                        country=loc_text.split(",")[-1].strip() if "," in loc_text else "",
                        remote="remote" in loc_text.lower(),
                    )
                )
            except Exception:
                continue

        if new_this_page == 0:
            break

        time.sleep(0.4)

    return postings
