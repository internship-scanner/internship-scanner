"""Filter logic for European tech internships.

Two filters applied in order:
1. is_european(location): only keep postings located in Europe.
2. matches_tech_focus(title, description): only keep SWE / systems / cloud /
   AI / fintech / distributed systems roles.

Both are intentionally conservative — when in doubt, KEEP the posting and let
the user filter in the UI. False negatives are worse than false positives here
because the user reviews the table anyway.
"""

from __future__ import annotations

import re
from typing import Iterable


# ---------------------------------------------------------------------------
# Europe detection
# ---------------------------------------------------------------------------

# Includes EU + EEA + UK + CH + candidate countries + small states.
# Each entry is matched case-insensitively as a whole word OR against ISO
# country codes / common variants.
EUROPEAN_COUNTRIES: set[str] = {
    # Country names (English + a few local variants used on careers pages)
    "albania", "andorra", "austria", "belarus", "belgium", "bosnia",
    "herzegovina", "bulgaria", "croatia", "cyprus", "czech republic", "czechia",
    "denmark", "estonia", "finland", "france", "germany", "deutschland",
    "greece", "hungary", "iceland", "ireland", "italy", "italia", "kosovo",
    "latvia", "liechtenstein", "lithuania", "luxembourg", "malta", "moldova",
    "monaco", "montenegro", "netherlands", "nederland", "holland",
    "north macedonia", "macedonia", "norway", "poland", "polska", "portugal",
    "romania", "san marino", "serbia", "slovakia", "slovenia", "spain",
    "españa", "sweden", "sverige", "switzerland", "schweiz", "suisse",
    "ukraine", "united kingdom", "uk", "great britain", "england", "scotland",
    "wales", "northern ireland", "vatican",
}

# ISO 3166-1 alpha-2 (without false friends — "PL" the language vs Poland is
# checked as a word-boundary token).
EUROPEAN_ISO2: set[str] = {
    "AL", "AD", "AT", "BY", "BE", "BA", "BG", "HR", "CY", "CZ", "DK", "EE",
    "FI", "FR", "DE", "GR", "HU", "IS", "IE", "IT", "XK", "LV", "LI", "LT",
    "LU", "MT", "MD", "MC", "ME", "NL", "MK", "NO", "PL", "PT", "RO", "SM",
    "RS", "SK", "SI", "ES", "SE", "CH", "UA", "GB", "VA",
}

# Major European cities — used as a positive signal when only a city is given.
EUROPEAN_CITIES: set[str] = {
    "amsterdam", "athens", "barcelona", "belfast", "belgrade", "berlin",
    "bratislava", "brussels", "bucharest", "budapest", "cambridge", "cologne",
    "copenhagen", "cork", "dublin", "düsseldorf", "dusseldorf", "edinburgh",
    "eindhoven", "frankfurt", "geneva", "glasgow", "hamburg", "helsinki",
    "istanbul", "kraków", "krakow", "lisbon", "ljubljana", "london", "lyon",
    "madrid", "manchester", "milan", "munich", "münchen", "muenchen",
    "oslo", "paris", "porto", "prague", "reykjavik", "riga", "rome", "roma",
    "rotterdam", "sofia", "stockholm", "stuttgart", "tallinn", "thessaloniki",
    "the hague", "valencia", "veldhoven", "vienna", "vilnius", "warsaw",
    "wroclaw", "wrocław", "zagreb", "zurich", "zürich",
}

# Strong NEGATIVE signals (override): if any of these appears we skip.
NON_EUROPEAN_STRONG: set[str] = {
    "united states", "usa", "u.s.", "u.s.a.", "canada", "brazil", "mexico",
    "argentina", "chile", "colombia", "india", "china", "japan", "korea",
    "south korea", "singapore", "australia", "new zealand", "south africa",
    "israel", "uae", "united arab emirates", "saudi arabia", "egypt",
    "remote - us", "remote (us)", "remote, us", "americas", "apac", "latam",
}

_WORD = re.compile(r"[A-Za-zÀ-ÿ]+")


def _tokens(text: str) -> list[str]:
    return [t.lower() for t in _WORD.findall(text)]


def is_european(location: str | None) -> bool:
    """Return True if the location string looks European.

    Pure "Remote" without any country hint is treated as European to surface
    EU-remote roles; the UI lets the user filter these out.
    """
    if not location:
        return False

    raw = location.strip()
    low = raw.lower()

    # Strong negative match first.
    for needle in NON_EUROPEAN_STRONG:
        if needle in low:
            return False

    # ISO-2 codes (e.g. "Berlin, DE" or "London, GB").
    for m in re.finditer(r"\b([A-Z]{2})\b", raw):
        if m.group(1) in EUROPEAN_ISO2:
            return True

    # Country / city / variant names.
    toks = set(_tokens(low))
    # Multi-word names need substring check too.
    for needle in EUROPEAN_COUNTRIES:
        if needle in low:
            return True
    for needle in EUROPEAN_CITIES:
        if needle in low:
            return True
    if toks & {"europe", "emea", "eu"}:
        return True

    # Generic "Remote" with no other geography hint -> include, user can filter.
    if "remote" in low and "," not in low and len(low) < 20:
        return True

    return False


# ---------------------------------------------------------------------------
# Tech focus matching
# ---------------------------------------------------------------------------

# Keep the keyword set tight. Whole-word matching; case-insensitive.
TECH_KEYWORDS: list[str] = [
    # Core SWE
    "software engineer", "software engineering", "software developer",
    "swe", "backend", "back-end", "back end", "frontend", "front-end",
    "front end", "full stack", "full-stack", "fullstack", "developer intern",
    # Systems / architecture / distributed
    "systems engineer", "system architect", "systems architecture",
    "distributed systems", "distributed system", "networked systems",
    "networking", "low latency", "high performance", "performance engineering",
    "infrastructure", "platform engineer", "platform engineering",
    "site reliability", "sre", "reliability engineer", "kernel", "operating system",
    "compiler", "database engineer", "storage engineer",
    # Cloud
    "cloud", "kubernetes", "k8s", "devops", "aws", "gcp", "azure", "terraform",
    # AI / ML
    "machine learning", "deep learning", "artificial intelligence",
    "ai engineer", "ai researcher", "ml engineer", "ml researcher",
    "research engineer", "applied scientist", "research scientist",
    "computer vision", "nlp", "natural language", "llm", "large language",
    "generative ai", "genai", "reinforcement learning", "mlops",
    # Fintech / quant
    "quantitative", "quant ", "quant developer", "quant engineer",
    "trading systems", "trading platform", "fintech", "payments engineer",
    "blockchain", "crypto engineer",
    # Security (often overlaps with distributed systems work)
    "security engineer", "security research", "cybersecurity",
    # Data
    "data engineer", "data engineering", "data infrastructure",
    "data platform",
]

# If the title contains these we EXCLUDE even if a tech keyword also matched.
EXCLUDE_KEYWORDS: list[str] = [
    "sales", "account executive", "account manager", "recruiter",
    "marketing", "communications", "people partner", "legal", "paralegal",
    "finance & accounting", "accountant", "controller", "tax", "audit",
    "hr ", "human resources", "office manager", "executive assistant",
    "ux researcher", "user researcher", "content strategist",
    "graphic designer", "brand designer", "social media", "pr ",
    "talent acquisition", "customer success", "customer support",
    "supply chain", "procurement", "facilities",
]


def _contains_whole(text: str, needle: str) -> bool:
    """Whole-word/phrase substring match, ignoring case."""
    if not needle:
        return False
    # Use \b on both sides; needle may contain spaces.
    pattern = r"\b" + re.escape(needle) + r"\b"
    return re.search(pattern, text, flags=re.IGNORECASE) is not None


def matches_tech_focus(title: str, description: str | None = None) -> tuple[bool, list[str]]:
    """Return (matches, matched_keywords).

    A posting matches when ANY tech keyword appears in title OR description
    AND no exclude keyword appears in the title.
    """
    title_l = (title or "").lower()
    haystack = f"{title or ''}\n{description or ''}"

    # Exclude first (only on title to avoid description false positives).
    for bad in EXCLUDE_KEYWORDS:
        if _contains_whole(title_l, bad):
            return False, []

    hits: list[str] = []
    for kw in TECH_KEYWORDS:
        if _contains_whole(haystack, kw):
            hits.append(kw)

    return (len(hits) > 0), sorted(set(hits))


# ---------------------------------------------------------------------------
# Internship detection
# ---------------------------------------------------------------------------

# Words/phrases that must match as a whole word — not as a substring.
# "intern" must hit "Software Intern" but NOT "Internal Tools" or "International".
_INTERN_PATTERNS = [
    r"\bintern(?:s|ship|ships)?\b",
    r"\bprakti(?:kum|kant(?:in)?|kanten)\b",
    r"\bwerkstudent(?:in|en)?\b",
    r"\bworking\s+student\b",
    r"\bstagiaire\b",
    r"\bstagista\b",
    r"\btirocinio\b",
    r"\bbecari[oa]\b",
    r"\bpr[aá]cticas\b",
    r"\bco[-\s]?op\b",
    r"\bapprentice(?:ship)?\b",
    r"\bthesis\s+(?:student|intern)\b",
    r"\bmaster\s+thesis\b",
    r"\bbachelor\s+thesis\b",
]

# Hard exclusions — if the title contains any of these as a whole word, it's
# NOT an internship even if "intern" appears elsewhere. Catches:
#   - "Internal Tools Engineer" (internal ≠ intern)
#   - "International Sales Manager"
#   - "Senior Software Engineer" / staff / principal / lead / manager
#   - "Junior Software Engineer" (junior full-time != internship)
#   - "Graduate Programme" without "intern"-ish word
_NOT_INTERN_PATTERNS = [
    r"\binternal\b",
    r"\binternational(?:ly)?\b",
    r"\bsenior\b",
    r"\bstaff\b",
    r"\bprincipal\b",
    r"\blead\b",
    r"\blearning\s+lead\b",
    r"\bmanager\b",
    r"\bjunior\b",            # junior FT roles aren't internships
    r"\bmid[-\s]level\b",
    r"\bgraduate(?:\s+program(?:me)?)?\b",  # graduate programs are FT, not intern
    r"\bfull[-\s]?time\b",
    r"\bpermanent\b",
]

_INTERN_RE = re.compile("|".join(_INTERN_PATTERNS), re.IGNORECASE)
_NOT_INTERN_RE = re.compile("|".join(_NOT_INTERN_PATTERNS), re.IGNORECASE)


def is_internship(title: str, employment_type: str | None = None) -> bool:
    """True if the role is unambiguously an internship/working-student role.

    Strategy:
      1. Title must contain a whole-word internship marker.
      2. Title must NOT contain a hard-exclusion word (senior/junior/manager/
         internal/international/...).
      3. employment_type is a weaker signal — used only when title is empty.
    """
    title_l = (title or "").strip()
    if not title_l:
        # Fall back to employment_type only.
        et = (employment_type or "").lower()
        return bool(_INTERN_RE.search(et)) and not bool(_NOT_INTERN_RE.search(et))

    if _NOT_INTERN_RE.search(title_l):
        return False
    if _INTERN_RE.search(title_l):
        return True

    # Title doesn't mention internship directly — only accept if the employment
    # type explicitly classifies it as such.
    et = (employment_type or "").lower()
    if _INTERN_RE.search(et) and not _NOT_INTERN_RE.search(et):
        return True
    return False
