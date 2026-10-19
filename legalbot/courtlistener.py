"""Import recent opinions from CourtListener (Free Law Project) so coverage extends past the CAP cutoff.

Full opinion text requires a free API token: create an account at courtlistener.com, then
    export COURTLISTENER_API_TOKEN=...

    python -m legalbot.courtlistener --court del --court delch --filed-after 2018-01-01
    python -m legalbot.courtlistener --court pa --filed-after 2024-01-01 --query "books and records"

Court ids are CourtListener's (e.g. del = Delaware Supreme Court, delch = Court of Chancery,
pa = Pennsylvania Supreme Court, me = Maine Supreme Judicial Court).
"""
import argparse
import html
import os
import re
import time

import requests

from .citations import find_citations
from .config import COURTLISTENER_BASE_URL
from .db import connect
from .ingest import upsert_case

OPINION_TYPES = {
    "010combined": "majority", "015unamimous": "majority", "020lead": "majority", "025plurality": "plurality",
    "030concurrence": "concurrence", "035concurrenceinpart": "concurrence", "040dissent": "dissent",
    "050addendum": "addendum", "060remittitur": "remittitur", "070rehearing": "rehearing",
}
TEXT_FIELDS = ("plain_text", "html_with_citations", "html", "html_lawbox", "html_columbia", "xml_harvard")


class CourtListener:
    def __init__(self, token: str | None = None, session: requests.Session | None = None, pause: float = 0.8):
        self.session = session or requests.Session()
        token = token or os.environ.get("COURTLISTENER_API_TOKEN")
        if token:
            self.session.headers["Authorization"] = f"Token {token}"
        self.pause = pause  # stay well under the API's hourly rate limit

    def get(self, url: str, params: dict | None = None) -> dict:
        response = self.session.get(url, params=params, timeout=60)
        if response.status_code == 401:
            raise SystemExit("CourtListener needs an API token for opinion text: set COURTLISTENER_API_TOKEN.")
        response.raise_for_status()
        time.sleep(self.pause)
        return response.json()

    def search(self, court: str, filed_after: str | None = None, filed_before: str | None = None, query: str | None = None):
        """Yield opinion-cluster search results (newest first), following pagination."""
        params = {"type": "o", "court": court, "order_by": "dateFiled desc"}
        if filed_after:
            params["filed_after"] = filed_after
        if filed_before:
            params["filed_before"] = filed_before
        if query:
            params["q"] = query
        url = f"{COURTLISTENER_BASE_URL}search/"
        while url:
            page = self.get(url, params)
            yield from page.get("results", [])
            url, params = page.get("next"), None  # 'next' already carries the query string

    def opinion(self, opinion_id: int) -> dict:
        return self.get(f"{COURTLISTENER_BASE_URL}opinions/{opinion_id}/")


def opinion_text(opinion: dict) -> str:
    for field in TEXT_FIELDS:
        value = opinion.get(field)
        if value and value.strip():
            if field == "plain_text":
                return value
            text = re.sub(r"<(?:br|/p|/div|/h\d)[^>]*>", "\n", value, flags=re.IGNORECASE)
            return html.unescape(re.sub(r"<[^>]+>", "", text))
    return ""


def to_case(result: dict, opinions: list[dict]) -> dict:
    """Map a CourtListener search result plus its opinions onto the CAP case shape upsert_case expects."""
    bodies = []
    for op in opinions:
        text = opinion_text(op)
        if text.strip():
            bodies.append({"type": OPINION_TYPES.get(op.get("type"), op.get("type")), "author": op.get("author_str") or None, "text": text})
    cites = {c for body in bodies for c in find_citations(body["text"])}
    return {
        "id": result["cluster_id"],
        "name": result.get("caseNameFull") or result.get("caseName"),
        "name_abbreviation": result.get("caseName"),
        "decision_date": result.get("dateFiled"),
        "docket_number": result.get("docketNumber"),
        "citations": [{"type": "official" if i == 0 else "parallel", "cite": c} for i, c in enumerate(result.get("citation") or [])],
        "court": {"name": result.get("court"), "name_abbreviation": result.get("court_citation_string")},
        "jurisdiction": {"name_long": None},
        "url": f"https://www.courtlistener.com{result['absolute_url']}" if result.get("absolute_url") else None,
        "casebody": {"opinions": bodies},
        "cites_to": [{"cite": c} for c in sorted(cites)],
    }


# CourtListener court id -> jurisdiction name used by the CAP data, so filters cover both sources.
JURISDICTIONS = {
    "del": "Delaware", "delch": "Delaware", "delsuperct": "Delaware", "delfamct": "Delaware",
    "pa": "Pennsylvania", "pasuperct": "Pennsylvania", "pacommwct": "Pennsylvania",
    "me": "Maine", "ri": "Rhode Island", "dc": "District of Columbia", "md": "Maryland", "mdctspecapp": "Maryland",
    "nj": "New Jersey", "njsuperctappdiv": "New Jersey", "conn": "Connecticut", "connappct": "Connecticut",
    "vt": "Vermont", "nh": "New Hampshire", "mass": "Massachusetts", "massappct": "Massachusetts",
}


def import_court(cl: CourtListener, court: str, filed_after=None, filed_before=None, query=None, limit=None) -> int:
    conn = connect()
    count = 0
    for result in cl.search(court, filed_after, filed_before, query):
        opinions = [cl.opinion(op["id"]) for op in result.get("opinions", [])]
        case = to_case(result, opinions)
        case["jurisdiction"]["name_long"] = JURISDICTIONS.get(court)
        if not case["casebody"]["opinions"]:
            continue
        with conn:
            upsert_case(conn, case, source="courtlistener")
        count += 1
        if limit and count >= limit:
            break
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--court", action="append", required=True, help="CourtListener court id (repeatable)")
    parser.add_argument("--filed-after")
    parser.add_argument("--filed-before")
    parser.add_argument("--query")
    parser.add_argument("--limit", type=int, help="Stop after this many cases per court")
    args = parser.parse_args()
    cl = CourtListener()
    for court in args.court:
        n = import_court(cl, court, args.filed_after, args.filed_before, args.query, args.limit)
        print(f"{court}: imported {n} cases")
    print("Run `python -m legalbot.vectors` to embed the new passages.")


if __name__ == "__main__":
    main()
