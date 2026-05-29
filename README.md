# internship-scanner

Weekly-refreshed, interactive table of European tech internships across ~60
companies from S+ to B tier (OpenAI, Anthropic, Google, Meta, NVIDIA,
Jane Street, Citadel, Databricks, Stripe, … down to Bolt).

Filtered to:

- **Location:** Europe (EU + EEA + UK + CH + candidate countries + "Remote")
- **Role:** Software, Systems/Distributed, Cloud, AI/ML, Fintech/Quant,
  Security, Data — non-technical roles (Marketing, Sales, HR, …) are
  filtered out automatically
- **Type:** Internship / Praktikum / Working Student / Co-op

## Quickstart (local)

```bash
# 1. Dependencies
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m playwright install chromium

# 2. Scrape (5–20 minutes depending on your network)
python -m scraper.run

# 3. View the table
python -m http.server 8000 --directory .
open http://localhost:8000/index.html
```

`index.html` loads `data/internships.json` directly — this only works through
an HTTP server, not via `file://` (CORS).

Test a single company:

```bash
python -m scraper.run --only Stripe
python -m scraper.run --only "Hudson River Trading"
```

Dry run (parse the config without making HTTP requests):

```bash
python -m scraper.run --dry-run
```

## Daily run via GitHub Actions

`.github/workflows/scrape.yml` runs every day at 03:00 UTC, scrapes all
companies, writes `data/internships.json`, and commits the result back to the
repo. You can also trigger the workflow manually under
"Actions → daily-scrape → Run workflow".

## Architecture

```
scraper/
  companies.yaml        ← List of all companies with ATS mapping
  run.py                ← Orchestrator: filter, dedup, JSON output
  filters.py            ← Europe detection + tech keyword matching
  base.py               ← Posting dataclass + BaseAdapter
  adapters/
    greenhouse.py       ← Greenhouse Board API
    lever.py            ← Lever Postings API
    ashby.py            ← Ashby Job Board API
    smartrecruiters.py  ← SmartRecruiters API
    workday.py          ← Workday CXS endpoint
    custom.py           ← Dispatcher for company-specific Playwright scrapers
    custom_modules/
      _generic.py       ← Fallback: anchor harvesting
      google.py         ← Google Careers
      meta.py           ← Meta Careers
      microsoft.py      ← Microsoft Careers JSON API
      apple.py          ← Apple Jobs API
      amazon.py         ← Amazon Jobs JSON API
      … (stubs for the rest)
data/
  internships.json      ← Scraping output (committed by the workflow)
  last_run.md           ← Per-company status report
index.html              ← Tabulator.js frontend
```

## Frontend features

- Per-column sorting (tier-aware: S+ → B)
- Per-column header filters + global search
- Multi-select dropdown filters (Tier, Category, Company, Country, City)
  with "Select all" checkboxes
- Date-range pickers for Deadline and Start
- Numeric range filter for Duration (weeks or months)
- Multi-row selection with CSV export
- Click a position title → opens the original job posting in a new tab
- Persisted sorting and column order (localStorage)

## Fixing or adding a company

1. **Open `scraper/companies.yaml`** and adjust the slug / adapter type.
2. The correct slug is usually visible in the URL of the company's public
   careers page, e.g. `https://boards.greenhouse.io/cloudflare` → slug
   `cloudflare`.
3. If the company doesn't use a standard ATS, set
   `adapter: custom_playwright` and create
   `scraper/adapters/custom_modules/<name>.py` with:

   ```python
   def scrape(cfg, page, adapter):
       # page = Playwright Page instance
       # adapter._mk(title=..., url=..., ...) → Posting
       ...
       return [postings]
   ```

4. Test: `python -m scraper.run --only "Company"`.

## Caveats

- ATS slugs are initial guesses and some will 404. The first run produces
  `data/last_run.md` with a per-company status — that's where you'll see
  which slugs need fixing.
- Career sites change their markup. The custom modules are stubs that
  delegate to `_generic.py`; this works for most companies with their own
  careers site, but dedicated per-company logic will always be more robust.
- robots.txt: Playwright does not respect robots.txt automatically. Sites
  with aggressive rate-limiting (LinkedIn etc., not included here) would
  require additional care.
