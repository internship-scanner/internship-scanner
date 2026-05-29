"""Orchestrator: read companies.yaml, run each adapter, filter, write JSON.

Usage:
    python -m scraper.run                # full run
    python -m scraper.run --only Stripe  # filter to one company
    python -m scraper.run --dry-run      # parse config + smoke-test, no writes
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import re
import sys
import time
import traceback
from pathlib import Path
from typing import Any

import yaml

from .adapters import ADAPTERS
from .adapters.custom import CustomPlaywrightAdapter
from .base import AdapterError, Posting
from .filters import is_european, is_internship, matches_tech_focus
from .geo import parse_locations
from .keywords import build_idf, curated_matches, top_corpus_terms

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
CONFIG = ROOT / "scraper" / "companies.yaml"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("internship-scanner")


# ---- Duration / deadline parsing ----------------------------------------

_DURATION_RE = re.compile(
    # Required: at least one digit, optional decimal, then explicit unit.
    # Supports EN + DE: "12 weeks" / "6 months" / "6 Monate" / "12 Wochen" /
    # "3-6 months" (range). Also: "6mo", "12 wks".
    r"(\d+(?:[.,]\d+)?)\s*(?:[-–]\s*(\d+(?:[.,]\d+)?))?\s*"
    r"(weeks?|wks?|wochen?|months?|monate?|mos?|mon|years?|yrs?|jahre?)\b",
    re.IGNORECASE,
)


def parse_duration(text: str) -> tuple[int | None, str]:
    """Extract a verified (value, unit) duration from free text.

    Returns (value, unit) where unit is "weeks" or "months", or (None, "") if
    no clear duration with explicit unit is found.

    Recognizes English ("weeks", "months", "year") and German ("Wochen",
    "Monate", "Jahre"). Ranges like "3-6 months" use the midpoint.
    """
    if not text:
        return None, ""
    m = _DURATION_RE.search(text)
    if not m:
        return None, ""
    lo, hi, unit_raw = m.group(1), m.group(2), m.group(3).lower()
    try:
        lo_v = float(lo.replace(",", "."))
    except ValueError:
        return None, ""
    if hi:
        try:
            hi_v = float(hi.replace(",", "."))
            v = (lo_v + hi_v) / 2.0
        except ValueError:
            v = lo_v
    else:
        v = lo_v

    if unit_raw.startswith(("w", "woche")):
        return round(v), "weeks"
    if unit_raw.startswith(("mo", "monat")):
        return round(v), "months"
    if unit_raw.startswith(("y", "yr", "jahr")):
        return round(v * 12), "months"
    return None, ""


def parse_duration_weeks(text: str) -> int | None:
    """Backward-compat: weeks-only output. Returns None if no clear duration."""
    val, unit = parse_duration(text)
    if val is None:
        return None
    if unit == "weeks":
        return val
    if unit == "months":
        return round(val * 4.345)
    return None


_ISO_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")


def _normalize_date_field(s: str) -> str:
    """Keep only first ISO date if free text contains one, else return s."""
    if not s:
        return ""
    m = _ISO_DATE_RE.search(s)
    return m.group(0) if m else s


# -------------------------------------------------------------------------


def load_config() -> list[dict]:
    with CONFIG.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)["companies"]


def categorize_position(title: str, keywords: list[str]) -> str:
    """Bucket the role into a coarse category used for sorting/coloring."""
    blob = (title + " " + " ".join(keywords)).lower()
    if any(k in blob for k in ["machine learning", "ml engineer", "ml researcher",
                                "deep learning", "ai engineer", "ai researcher",
                                "nlp", "computer vision", "llm", "generative"]):
        return "AI/ML"
    if any(k in blob for k in ["quant", "trading", "fintech", "payments"]):
        return "Fintech/Quant"
    if any(k in blob for k in ["security", "cybersecurity"]):
        return "Security"
    if any(k in blob for k in ["distributed", "systems engineer", "kernel",
                                "infrastructure", "platform", "sre",
                                "site reliability", "compiler", "low latency"]):
        return "Systems/Infra"
    if any(k in blob for k in ["cloud", "kubernetes", "devops", "aws", "gcp", "azure"]):
        return "Cloud"
    if any(k in blob for k in ["data engineer", "data platform", "data infrastructure"]):
        return "Data"
    return "Software"


def _ensure_iso_date(s: str) -> str:
    """Normalize a date/datetime string to ISO. Returns "" if it can't parse."""
    if not s:
        return ""
    s = s.strip()
    # Already ISO date or datetime?
    if re.match(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?", s):
        return s
    # Try datetime.fromisoformat for fuzzy variants
    try:
        d = dt.datetime.fromisoformat(s)
        return d.isoformat(timespec="minutes")
    except (ValueError, TypeError):
        pass
    # Last resort: try common formats
    for fmt in ("%Y/%m/%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            d = dt.datetime.strptime(s, fmt)
            return d.date().isoformat()
        except ValueError:
            continue
    return ""


def filter_postings(raw: list[Posting]) -> tuple[list[Posting], dict[str, int]]:
    """Two-pass filter and enrichment.

    Pass 1: drop non-internships, non-EU postings, non-tech roles. Resolve
            locations, parse duration, extract curated keywords.
    Pass 2: build an IDF model over all kept descriptions, then add the
            top-IDF terms to each posting's keywords.
    """
    stats = {
        "raw": len(raw),
        "dropped_not_intern": 0,
        "dropped_no_eu_location": 0,
        "dropped_not_tech": 0,
        "kept": 0,
    }

    # ---------- Pass 1 -----------------------------------------------------
    kept: list[Posting] = []
    for p in raw:
        # Strict internship check.
        if not is_internship(p.title, p.employment_type):
            stats["dropped_not_intern"] += 1
            continue

        # Resolve location -> list of (city, country_iso_name).
        locs = parse_locations(p.location_raw)
        # Also try the title (some companies put location in title like
        # "Software Engineer Intern - London").
        if not locs and p.title:
            locs = parse_locations(p.title)
        if not locs:
            stats["dropped_no_eu_location"] += 1
            continue

        # Multi-city support: keep all distinct cities/countries.
        # cities[i] and city_countries[i] are parallel arrays so the UI can
        # show "Berlin, Germany · Paris, France" for cross-country postings.
        cities: list[str] = []
        city_countries: list[str] = []
        countries: list[str] = []
        for city, country in locs:
            if city and city not in cities:
                cities.append(city)
                city_countries.append(country)
            if country and country not in countries:
                countries.append(country)
        p.cities = cities
        p.city_countries = city_countries
        # The "primary" country is used for the country filter dropdown and
        # for stable sorting. For multi-country postings we pick the first.
        p.country = countries[0] if countries else ""

        # Tech filter — only after we've confirmed EU location, since it's
        # the more expensive check (regex over description).
        ok, hits = matches_tech_focus(p.title, p.description)
        if not ok:
            stats["dropped_not_tech"] += 1
            continue
        p.position_category = categorize_position(p.title, hits)

        # Duration: only set if we can verify (number + explicit unit).
        if p.duration_value is None:
            val, unit = parse_duration(p.description)
            if val is not None:
                p.duration_value = val
                p.duration_unit = unit
                # populate the numeric-weeks field used by the range filter
                if unit == "weeks":
                    p.duration_weeks = val
                elif unit == "months":
                    p.duration_weeks = round(val * 4.345)

        # Normalize date fields to ISO.
        p.posted_at = _ensure_iso_date(p.posted_at)
        p.deadline = _ensure_iso_date(p.deadline)
        p.start_date = _ensure_iso_date(p.start_date)

        # Curated keywords from title + description.
        haystack = f"{p.title}\n{p.description}"
        p.keywords = curated_matches(haystack)

        kept.append(p)

    stats["kept"] = len(kept)

    # ---------- Pass 2: corpus-weighted keyword boost ----------------------
    # Build IDF over all kept descriptions; for each posting, add top terms
    # that aren't already covered by the curated list.
    descs = [p.description for p in kept]
    if descs:
        idf = build_idf(descs)
        for p in kept:
            existing_lc = {k.lower() for k in p.keywords}
            corpus_terms = top_corpus_terms(p.description, idf, k=8)
            for term in corpus_terms:
                if term.lower() in existing_lc:
                    continue
                # Don't double-add unigrams already in a kept bigram (or vice versa).
                tokens = term.lower().split()
                if any(t in existing_lc for t in tokens):
                    continue
                p.keywords.append(term)
                existing_lc.add(term.lower())
            # Cap at 12 keywords per posting so the UI cell stays compact.
            p.keywords = p.keywords[:12]

    return kept, stats


def _build_page_factory():
    """Lazy-create a Playwright browser and return a factory for fresh pages."""
    from playwright.sync_api import sync_playwright

    pw = sync_playwright().start()
    browser = pw.chromium.launch(
        headless=True,
        args=["--disable-blink-features=AutomationControlled"],
    )
    context = browser.new_context(
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        viewport={"width": 1366, "height": 900},
        locale="en-US",
    )

    def factory():
        return context.new_page()

    def shutdown():
        try:
            context.close()
        finally:
            try:
                browser.close()
            finally:
                pw.stop()

    return factory, shutdown


def run(only: str | None = None, dry_run: bool = False) -> int:
    companies = load_config()
    if only:
        companies = [c for c in companies if c["name"].lower() == only.lower()]
        if not companies:
            log.error("No company matches --only=%s", only)
            return 2

    needs_playwright = any(c.get("adapter") == "custom_playwright" for c in companies)
    page_factory = shutdown = None
    if needs_playwright and not dry_run:
        try:
            page_factory, shutdown = _build_page_factory()
        except Exception as e:  # noqa: BLE001
            log.error("Could not start Playwright: %s -- custom modules will be skipped", e)
            page_factory = shutdown = None

    all_postings: list[Posting] = []
    per_company_stats: list[dict[str, Any]] = []

    try:
        for cfg in companies:
            name = cfg["name"]
            adapter_key = cfg.get("adapter")
            cls = ADAPTERS.get(adapter_key)
            if cls is None:
                log.error("%s: unknown adapter '%s'", name, adapter_key)
                per_company_stats.append(
                    {"company": name, "ok": False, "error": f"unknown adapter '{adapter_key}'"}
                )
                continue

            adapter = cls(cfg)

            # Inject page factory into custom playwright adapter.
            if isinstance(adapter, CustomPlaywrightAdapter):
                if page_factory is None:
                    log.warning("%s: playwright unavailable, skipping", name)
                    per_company_stats.append(
                        {"company": name, "ok": False, "error": "playwright unavailable"}
                    )
                    continue
                adapter.page_factory = page_factory

            log.info("---- %s (%s) ----", name, adapter_key)
            t0 = time.time()
            raw_for_company: list[Posting] = []
            try:
                if dry_run:
                    log.info("dry-run: skipping fetch")
                else:
                    raw_for_company = list(adapter.fetch())
            except AdapterError as e:
                log.warning("%s: adapter error: %s", name, e)
                per_company_stats.append(
                    {"company": name, "ok": False, "error": str(e), "duration_s": round(time.time() - t0, 1)}
                )
                continue
            except Exception as e:  # noqa: BLE001
                log.error("%s: unexpected error: %s\n%s", name, e, traceback.format_exc())
                per_company_stats.append(
                    {"company": name, "ok": False, "error": f"unexpected: {type(e).__name__}: {e}",
                     "duration_s": round(time.time() - t0, 1)}
                )
                continue

            kept, fstats = filter_postings(raw_for_company)
            all_postings.extend(kept)
            per_company_stats.append(
                {
                    "company": name,
                    "tier": cfg.get("tier"),
                    "ok": True,
                    "duration_s": round(time.time() - t0, 1),
                    **fstats,
                }
            )
            log.info(
                "%s: raw=%d kept=%d (not_intern=%d no_eu_loc=%d not_tech=%d) in %.1fs",
                name, fstats["raw"], fstats["kept"],
                fstats["dropped_not_intern"], fstats["dropped_no_eu_location"],
                fstats["dropped_not_tech"], time.time() - t0,
            )

    finally:
        if shutdown is not None:
            shutdown()

    # ---------- Write outputs ----------
    if dry_run:
        log.info("Dry-run complete. Companies parsed: %d", len(companies))
        return 0

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Dedup by id (different adapters could conceivably produce dupes, though
    # unlikely with our current mapping).
    by_id: dict[str, Posting] = {}
    for p in all_postings:
        by_id.setdefault(p.id, p)
    unique = sorted(
        by_id.values(),
        key=lambda p: (
            {"S+": 0, "S": 1, "A+": 2, "A": 3, "B": 4}.get(p.tier, 9),
            p.company.lower(),
            p.title.lower(),
        ),
    )

    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "total": len(unique),
        "companies_scraped": len(companies),
        "postings": [p.to_dict() for p in unique],
        "stats": per_company_stats,
    }

    out = DATA_DIR / "internships.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info("Wrote %d postings to %s", len(unique), out)

    # Status report as a small markdown file.
    rep = DATA_DIR / "last_run.md"
    lines = [
        f"# Last run — {payload['generated_at']}",
        "",
        f"- Total kept postings: **{len(unique)}**",
        f"- Companies attempted: {len(companies)}",
        "",
        "| Company | Tier | OK | Raw | Kept | Duration | Error |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in per_company_stats:
        err = (s.get("error") or "").replace("|", "/").replace("\n", " ")[:120]
        lines.append(
            f"| {s['company']} | {s.get('tier','')} | {'✅' if s.get('ok') else '❌'} "
            f"| {s.get('raw','')} | {s.get('kept','')} | {s.get('duration_s','')}s | {err} |"
        )
    rep.write_text("\n".join(lines), encoding="utf-8")
    log.info("Wrote run report to %s", rep)

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="Only scrape one company by name (case-insensitive)")
    ap.add_argument("--dry-run", action="store_true", help="Validate config, no fetch")
    args = ap.parse_args()
    return run(only=args.only, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
