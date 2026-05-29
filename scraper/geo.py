"""City and country normalization via the offline geonames database.

The data we get from career pages is messy:
  "Berlin, Germany"           -> [("Berlin", "Germany")]
  "London / Dublin"           -> [("London", "United Kingdom"), ("Dublin", "Ireland")]
  "Remote - Denmark"          -> [("", "Denmark")] (no city)
  "Multiple Locations"        -> []
  "EMEA"                      -> []
  "München, Germany"          -> [("Munich", "Germany")]  (canonical)

We build an in-memory index over the geonamescache database keyed by:
  - canonical city name (lowercased)
  - every alternate name in the local script

Plus a small allow-list of country names (English) for "Remote, Germany"
style strings where there is no city.

We *only* return locations we can resolve to a known Geonames city, with
ties broken by population (largest wins — Cambridge UK vs Cambridge MA).
Unknown tokens are silently dropped, so junk like "Multiple Locations"
yields an empty list and the posting can be filtered out at the orchestrator
level.
"""

from __future__ import annotations

import functools
import logging
import re
import unicodedata
from typing import Iterable

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# European country whitelist (must match what filters.is_european accepts)
# ---------------------------------------------------------------------------
# ISO-2 codes we consider European. Same set as filters.EUROPEAN_ISO2.
EUROPEAN_ISO2: set[str] = {
    "AL", "AD", "AT", "BY", "BE", "BA", "BG", "HR", "CY", "CZ", "DK", "EE",
    "FI", "FR", "DE", "GR", "HU", "IS", "IE", "IT", "XK", "LV", "LI", "LT",
    "LU", "MT", "MD", "MC", "ME", "NL", "MK", "NO", "PL", "PT", "RO", "SM",
    "RS", "SK", "SI", "ES", "SE", "CH", "UA", "GB", "VA",
}

# Country-name → ISO-2, for "Remote Germany" type strings. Includes common
# variants ("UK" / "Great Britain" / "United Kingdom" for GB).
_COUNTRY_NAME_TO_ISO2: dict[str, str] = {
    "albania": "AL", "andorra": "AD", "austria": "AT", "belarus": "BY",
    "belgium": "BE", "bosnia and herzegovina": "BA", "bulgaria": "BG",
    "croatia": "HR", "cyprus": "CY", "czechia": "CZ", "czech republic": "CZ",
    "denmark": "DK", "estonia": "EE", "finland": "FI", "france": "FR",
    "germany": "DE", "deutschland": "DE", "greece": "GR", "hungary": "HU",
    "iceland": "IS", "ireland": "IE", "italy": "IT", "italia": "IT",
    "kosovo": "XK", "latvia": "LV", "liechtenstein": "LI", "lithuania": "LT",
    "luxembourg": "LU", "malta": "MT", "moldova": "MD", "monaco": "MC",
    "montenegro": "ME", "netherlands": "NL", "nederland": "NL",
    "holland": "NL", "north macedonia": "MK", "macedonia": "MK",
    "norway": "NO", "poland": "PL", "polska": "PL", "portugal": "PT",
    "romania": "RO", "san marino": "SM", "serbia": "RS", "slovakia": "SK",
    "slovenia": "SI", "spain": "ES", "españa": "ES", "sweden": "SE",
    "sverige": "SE", "switzerland": "CH", "schweiz": "CH", "suisse": "CH",
    "ukraine": "UA", "united kingdom": "GB", "great britain": "GB",
    "uk": "GB", "england": "GB", "scotland": "GB", "wales": "GB",
    "northern ireland": "GB", "vatican": "VA",
}

# ISO-2 → display name (English) for the UI output
ISO2_TO_DISPLAY: dict[str, str] = {
    "AL": "Albania", "AD": "Andorra", "AT": "Austria", "BY": "Belarus",
    "BE": "Belgium", "BA": "Bosnia and Herzegovina", "BG": "Bulgaria",
    "HR": "Croatia", "CY": "Cyprus", "CZ": "Czechia", "DK": "Denmark",
    "EE": "Estonia", "FI": "Finland", "FR": "France", "DE": "Germany",
    "GR": "Greece", "HU": "Hungary", "IS": "Iceland", "IE": "Ireland",
    "IT": "Italy", "XK": "Kosovo", "LV": "Latvia", "LI": "Liechtenstein",
    "LT": "Lithuania", "LU": "Luxembourg", "MT": "Malta", "MD": "Moldova",
    "MC": "Monaco", "ME": "Montenegro", "NL": "Netherlands",
    "MK": "North Macedonia", "NO": "Norway", "PL": "Poland", "PT": "Portugal",
    "RO": "Romania", "SM": "San Marino", "RS": "Serbia", "SK": "Slovakia",
    "SI": "Slovenia", "ES": "Spain", "SE": "Sweden", "CH": "Switzerland",
    "UA": "Ukraine", "GB": "United Kingdom", "VA": "Vatican City",
}


# ---------------------------------------------------------------------------
# City index — built lazily on first call
# ---------------------------------------------------------------------------

def _normalize_key(s: str) -> str:
    """Lower-case, strip accents, collapse whitespace, drop punctuation."""
    nfkd = unicodedata.normalize("NFKD", s)
    ascii_only = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()


@functools.lru_cache(maxsize=1)
def _build_index() -> dict[str, list[dict]]:
    """Return key → list of city dicts.

    A key is the normalized form of any name or alternate the city goes by.
    Multiple cities can share a key (e.g. "Cambridge" → both UK and US);
    population breaks ties at lookup time.
    """
    try:
        import geonamescache
    except ImportError as e:
        raise RuntimeError(
            "geonamescache is required. Install with `pip install geonamescache`."
        ) from e

    gc = geonamescache.GeonamesCache()
    cities = gc.get_cities()

    index: dict[str, list[dict]] = {}
    for c in cities.values():
        # Only index European cities; we're filtering for Europe anyway.
        if c["countrycode"] not in EUROPEAN_ISO2:
            continue
        names = [c["name"], *(c.get("alternatenames") or [])]
        for n in names:
            if not n or len(n) < 2:
                continue
            key = _normalize_key(n)
            if not key:
                continue
            index.setdefault(key, []).append(c)
    log.info("built city index: %d keys, %d total city-keys",
             len(index), sum(len(v) for v in index.values()))
    return index


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

# Words/phrases to strip before tokenizing.
_NOISE_TOKENS = {
    "remote", "hybrid", "onsite", "on-site", "office", "fully", "partial",
    "or", "and", "in", "based", "headquarters", "hq", "anywhere",
    "multiple", "locations", "various", "several",
    "emea", "europe", "european", "eu", "eea",
}

# Separators on which we split a multi-city string.
_SPLITTERS = re.compile(r"\s*(?:[,;/|]|\bor\b|\band\b|\bvs\b|→|->|·| - )\s*",
                         re.IGNORECASE)

# Open/close parens we strip entirely.
_PARENS = re.compile(r"[()\[\]{}]")


def _candidate_tokens(raw: str) -> list[str]:
    """Split a free-text location into individual city candidates."""
    if not raw:
        return []
    s = _PARENS.sub(" ", raw)
    parts = _SPLITTERS.split(s)
    out = []
    for p in parts:
        p = p.strip()
        if not p:
            continue
        # Drop pure noise tokens.
        if _normalize_key(p) in _NOISE_TOKENS:
            continue
        out.append(p)
    return out


def _resolve_country_from_token(token: str) -> str | None:
    """If `token` is just a country name, return its ISO-2 — else None."""
    key = _normalize_key(token)
    return _COUNTRY_NAME_TO_ISO2.get(key)


# Extra cities not present in geonamescache's default >15k DB but relevant
# for our universe. Each entry: lowercased key → (canonical_name, ISO2).
# Mostly small EU tech hubs (HQs of single companies).
_EXTRA_CITIES: dict[str, tuple[str, str]] = {
    "veldhoven": ("Veldhoven", "NL"),
    "leuven": ("Leuven", "BE"),
    "delft": ("Delft", "NL"),
    "tampere": ("Tampere", "FI"),
    "espoo": ("Espoo", "FI"),
    "trondheim": ("Trondheim", "NO"),
    "linz": ("Linz", "AT"),
    "graz": ("Graz", "AT"),
    "lausanne": ("Lausanne", "CH"),
    "saarbrucken": ("Saarbrücken", "DE"),
    "saarbrücken": ("Saarbrücken", "DE"),
    "darmstadt": ("Darmstadt", "DE"),
    "karlsruhe": ("Karlsruhe", "DE"),
    "heidelberg": ("Heidelberg", "DE"),
    "leipzig": ("Leipzig", "DE"),
    "nuremberg": ("Nuremberg", "DE"),
    "nurnberg": ("Nuremberg", "DE"),
    "nürnberg": ("Nuremberg", "DE"),
    "aachen": ("Aachen", "DE"),
    "ulm": ("Ulm", "DE"),
    "freiburg": ("Freiburg", "DE"),
    "leiden": ("Leiden", "NL"),
    "groningen": ("Groningen", "NL"),
    "utrecht": ("Utrecht", "NL"),
    "the hague": ("The Hague", "NL"),
    "den haag": ("The Hague", "NL"),
}


def _resolve_city_from_token(token: str) -> tuple[str, str] | None:
    """Return (canonical English name, ISO-2 country) for the token, or None.

    Picks the most populous match for ambiguous names.
    """
    key = _normalize_key(token)
    if not key:
        return None
    # Manual override first (small cities not in Geonames default DB).
    if key in _EXTRA_CITIES:
        return _EXTRA_CITIES[key]
    index = _build_index()
    matches = index.get(key)
    if matches:
        # Best = highest population
        best = max(matches, key=lambda c: c.get("population", 0))
        return best["name"], best["countrycode"]
    # Last-ditch: token might be "city country" without a comma
    # (e.g. "Munich Germany" after parens were stripped). Try splitting on
    # whitespace and matching the LAST word as a country.
    words = token.split()
    if len(words) >= 2:
        tail = words[-1]
        if _normalize_key(tail) in _COUNTRY_NAME_TO_ISO2:
            head = " ".join(words[:-1])
            head_key = _normalize_key(head)
            if head_key in _EXTRA_CITIES:
                return _EXTRA_CITIES[head_key]
            head_match = index.get(head_key)
            if head_match:
                best = max(head_match, key=lambda c: c.get("population", 0))
                return best["name"], best["countrycode"]
    return None


# Strong negative signals — if any of these appears as a whole word in the
# raw location, we reject the whole posting. Covers US states (postal + full
# names) and well-known non-European countries that often produce false-positive
# fuzzy matches against Geonames alternate names.
_US_STATE_ABBREVS = {
    "al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia",
    "ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj",
    "nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx","ut","vt",
    "va","wa","wv","wi","wy","dc",
}
_US_STATE_NAMES = {
    "alabama","alaska","arizona","arkansas","california","colorado","connecticut",
    "delaware","florida","georgia","hawaii","idaho","illinois","indiana","iowa",
    "kansas","kentucky","louisiana","maine","maryland","massachusetts","michigan",
    "minnesota","mississippi","missouri","montana","nebraska","nevada",
    "new hampshire","new jersey","new mexico","new york","north carolina",
    "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
    "south carolina","south dakota","tennessee","texas","utah","vermont",
    "virginia","washington","west virginia","wisconsin","wyoming",
    # Major US cities that are unambiguous "obviously not Europe" signals
    "new york city","san francisco","los angeles","silicon valley","bay area",
    "redmond","mountain view","cupertino","palo alto","san jose","menlo park",
    "seattle","austin","boston","chicago","denver","atlanta","houston","dallas",
    "miami","philadelphia","san diego",
}
_NON_EU_COUNTRY_NAMES = {
    # countries whose alternate names cause Geonames false positives
    "usa","united states","united states of america","u.s.","u.s.a",
    "canada","mexico","brazil","argentina","chile","colombia","peru",
    "india","china","japan","korea","south korea","singapore","malaysia",
    "thailand","vietnam","indonesia","philippines","taiwan","hong kong",
    "australia","new zealand",
    "israel","united arab emirates","uae","saudi arabia","egypt","south africa",
    "nigeria","kenya","morocco",
    "russia","russian federation",
}
_NON_EU_SIGNALS = _US_STATE_ABBREVS | _US_STATE_NAMES | _NON_EU_COUNTRY_NAMES


def _has_non_eu_signal(raw: str) -> bool:
    """True if the raw location string contains an unambiguous non-EU marker.

    Tokenizes the raw string the same way parse_locations does, then checks
    each token against the non-EU signal set. Multi-word names are matched
    via the normalized key form.
    """
    # Split on comma/slash/etc. then check each segment.
    for tok in _candidate_tokens(raw):
        key = _normalize_key(tok)
        if key in _NON_EU_SIGNALS:
            return True
        # Also check the last word of multi-word tokens (catches "Cambridge MA"
        # which tokenizes to a single "Cambridge MA" after parens-stripping).
        words = key.split()
        if len(words) >= 2 and words[-1] in _NON_EU_SIGNALS:
            return True
    return False


def parse_locations(raw: str) -> list[tuple[str, str]]:
    """Parse a free-text location string into a list of (city, country).

    Returns a list because a posting can list multiple offices.
    Cities resolve to their canonical English name. Country is the
    English display name (from ISO2_TO_DISPLAY).

    Returns [] (rejecting the posting) for:
      - Locations explicitly outside Europe (US states, non-EU countries)
      - Strings we can't parse confidently ("Multiple Locations", "EMEA")

    Examples:
        "Berlin, Germany"          -> [("Berlin", "Germany")]
        "London / Dublin"          -> [("London", "United Kingdom"),
                                       ("Dublin", "Ireland")]
        "München, Germany"         -> [("Munich", "Germany")]
        "Remote - Denmark"         -> [("", "Denmark")]
        "Cambridge, MA"            -> []          (US — rejected)
        "Bangalore, India"         -> []          (India — rejected)
        "Multiple Locations"       -> []
        "EMEA"                     -> []
    """
    if not raw:
        return []

    # Pre-check: an unambiguous non-EU signal anywhere in the string
    # rejects the whole posting, even if there's a city name that happens
    # to also exist in Europe (Cambridge MA, Bangalore India, …).
    if _has_non_eu_signal(raw):
        return []

    tokens = _candidate_tokens(raw)
    found_cities: dict[tuple[str, str], None] = {}  # ordered set
    found_country_only: str | None = None

    for tok in tokens:
        # Try as a city first (most informative).
        hit = _resolve_city_from_token(tok)
        if hit:
            cname, iso2 = hit
            if iso2 in EUROPEAN_ISO2:
                country_display = ISO2_TO_DISPLAY.get(iso2, "")
                found_cities[(cname, country_display)] = None
            continue
        # Else: maybe a country name on its own?
        iso2 = _resolve_country_from_token(tok)
        if iso2 and iso2 in EUROPEAN_ISO2:
            found_country_only = ISO2_TO_DISPLAY.get(iso2, "")

    if found_cities:
        return list(found_cities.keys())
    if found_country_only:
        return [("", found_country_only)]
    return []
