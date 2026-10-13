"""Find and normalize reporter citations such as "1 A.3d 281" or "100 F. Supp. 2d 5"."""
import re

# volume, reporter abbreviation (one or more "Abbr." tokens, optional series like 2d/3d/4th), page
CITATION_RE = re.compile(
    r"\b(?P<volume>\d{1,4})\s+"
    r"(?P<reporter>(?:[A-Z][A-Za-z&']{0,9}\.\s?){1,5}(?:\s?\d(?:d|nd|rd|th)\b)?)"
    r"\s?(?P<page>\d{1,5})\b"
)

# Statute and regulation codes share the "volume Abbr. section" shape but are not case reporters.
STATUTE_CODES = {"U.S.C.", "C.F.R.", "Fed.Reg.", "Del.C.", "Pa.C.S.", "Pa.C.S.A.", "P.S.", "M.R.S.", "M.R.S.A.", "R.I.G.L.", "D.C.Code"}


def normalize_cite(cite: str) -> str:
    """Canonical form used for lookups: whitespace removed inside the reporter, single spaces elsewhere."""
    m = CITATION_RE.fullmatch(" ".join(cite.split()))
    if not m:
        return " ".join(cite.split())
    reporter = re.sub(r"\s+", "", m["reporter"])
    return f"{m['volume']} {reporter} {m['page']}"


def find_citations(text: str) -> list[str]:
    """Return citations in order of first appearance, as written in the text."""
    seen, found = set(), []
    for m in CITATION_RE.finditer(text):
        raw = " ".join(m.group(0).split())
        key = normalize_cite(raw)
        if key.split(" ")[1] in STATUTE_CODES:
            continue
        if key not in seen:
            seen.add(key)
            found.append(raw)
    return found
