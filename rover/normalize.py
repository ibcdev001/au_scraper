"""Value normalisation shared by the pairing step.

The two registers render the same kinds of value differently, so everything
has to be parsed before SEV and MRE rows can be compared:

    SEV build date range   "05/2011 - 09/2020"   zero-padded month
    MRE build date         "7/2017 - 3/2020"     not padded
    SEV/RAW expiry         "29/11/2026"          day/month/year
    list-grid raw date     "/Date(1483228800000)/"   epoch milliseconds
    open-ended range       "01/2023 - No end date"

Pure functions only, and deliberately no Scrapy import: the pairing step runs
over JSON on disk, long after the crawl.
"""

import re
from datetime import date, datetime, timezone

# A month is represented as (year, month) throughout. Comparing those tuples
# compares chronologically, which is all the build-date maths needs.
Month = tuple

OPEN_ENDED = re.compile(r"no\s*end\s*date|ongoing|current|present", re.I)
_DATAVERSE = re.compile(r"/Date\((-?\d+)\)/")
_RANGE_SPLIT = re.compile(r"\s*(?:-|–|—|to)\s*")
_PUNCT = re.compile(r"[.,'\"()/&]+")
_SPACE = re.compile(r"\s+")


def parse_month(value):
    """"7/2017" or "05/2011" -> (2017, 7). Also accepts a full d/m/Y date."""
    if not value:
        return None
    parts = [p for p in re.split(r"[/\-.]", str(value).strip()) if p]
    if len(parts) == 2:
        month, year = parts
    elif len(parts) == 3:
        # a full date; the month is the middle field in the portal's d/m/Y
        _, month, year = parts
    else:
        return None
    try:
        month, year = int(month), int(year)
    except ValueError:
        return None
    if not 1 <= month <= 12 or not 1900 <= year <= 2100:
        return None
    return (year, month)


def parse_bdr(value):
    """Build date range -> (start_month, end_month).

    `end` is None for an open-ended range ("01/2023 - No end date"), which the
    SEV register uses for models still in production. A single month with no
    separator is treated as a one-month range.
    """
    if not value:
        return (None, None)
    text = str(value).strip()
    if not text:
        return (None, None)
    parts = _RANGE_SPLIT.split(text, maxsplit=1)
    start = parse_month(parts[0])
    if len(parts) == 1:
        return (start, start)
    tail = parts[1].strip()
    if OPEN_ENDED.search(tail):
        return (start, None)
    return (start, parse_month(tail))


def parse_dmy(value):
    """"29/11/2026" or "1/01/2017" -> date."""
    if not value:
        return None
    text = str(value).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_dataverse_date(value):
    """"/Date(1483228800000)/" -> date (UTC), or ISO-8601 straight through."""
    if not value:
        return None
    text = str(value).strip()
    hit = _DATAVERSE.search(text)
    if hit:
        return datetime.fromtimestamp(int(hit.group(1)) / 1000, timezone.utc).date()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def parse_any_date(*values):
    """First parseable date from the arguments; raw epoch forms win over display
    strings because they are unambiguous, so pass them first."""
    for value in values:
        got = parse_dataverse_date(value) or parse_dmy(value)
        if got:
            return got
    return None


def month_str(month):
    """(2017, 7) -> "07/2017"; None -> None (open-ended or unknown)."""
    if not month:
        return None
    return f"{month[1]:02d}/{month[0]}"


def norm_name(value):
    """Upper-cased, punctuation- and space-squashed, for comparing makes,
    models and company names across the two registers ("GLAM GROUPS PTY. LTD."
    and "Glam Groups Pty Ltd" are the same workshop)."""
    if not value:
        return ""
    text = _PUNCT.sub(" ", str(value))
    return _SPACE.sub(" ", text).strip().upper()


def category_code(value):
    """"MA - Passenger Vehicle" -> "MA". The MRE register already stores the
    bare code, so this has to be idempotent."""
    if not value:
        return ""
    return str(value).split("-")[0].strip().upper()


def model_codes(value):
    """"ZVW40/ZVW41" -> ["ZVW40", "ZVW41"].

    The SEV register packs several chassis/model codes into one field,
    separated by slashes, commas or "and". Hyphens are kept, because codes
    like "B-G" contain one.
    """
    if not value:
        return []
    out = []
    for token in re.split(r"[/,;]|\band\b", str(value), flags=re.I):
        token = _SPACE.sub(" ", token).strip().upper()
        if token:
            out.append(token)
    return out


def vin_patterns(value):
    """"Typical VIN" field -> list of regexes.

    The field holds one or more space-separated specimen VINs in which the
    variable characters are written as X, Z or #, e.g. "6XXXXAHR20XXXXXXX".
    Advisory only: the register calls these typical, not definitive, so the
    pairing never gates on them.
    """
    if not value:
        return []
    out = []
    for token in str(value).split():
        token = token.strip().upper()
        if len(token) < 6:
            continue
        body = "".join(
            "." if ch in "XZ#*?" else re.escape(ch) for ch in token
        )
        out.append("^" + body + "$")
    return out


# The SEV register's free-text "Variant details" often narrows eligibility
# further than the structured build date range does, e.g.
#   "Eligible build date range limited to 1/03/2010 to 20/07/2010 ONLY"
#   "SEVS eligibility restricted to USF 40 and USF 41 (2WD) with build date
#    range of 1/09/2006 to 30/04/2007"
#   "2 door, K20A series motor, ONLY."
# so it has to be read before the structured range can be trusted.
RESTRICTION_HINT = re.compile(
    r"\bonly\b|restrict|limited|exclud|\bnot\b.*\beligible\b", re.I
)
_DATE_TOKEN = r"\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{1,2}[/-]\d{4}"
_PROSE_RANGE = re.compile(
    rf"({_DATE_TOKEN})\s*(?:to|-|–|—|until|through)\s*({_DATE_TOKEN})", re.I
)


def has_restriction_hint(text):
    """True when free text claims to narrow eligibility, whether or not any
    dates can be pulled out of it."""
    return bool(text) and bool(RESTRICTION_HINT.search(str(text)))


def parse_prose_range(text):
    """Pull a build-date restriction out of free text -> (start, end).

    Returns (None, None) when the text carries no parseable date pair, which
    includes the many restrictions that are about trim or engine rather than
    dates ("2 door, K20A series motor, ONLY") - those still need a human, and
    `has_restriction_hint` is what flags them.
    """
    if not text:
        return (None, None)
    hit = _PROSE_RANGE.search(str(text))
    if not hit:
        return (None, None)
    start, end = parse_month(hit.group(1)), parse_month(hit.group(2))
    if start is None or end is None or start > end:
        return (None, None)
    return (start, end)
