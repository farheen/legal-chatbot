import json
import os
import tempfile
import zipfile
from pathlib import Path

# Point every module at a throwaway database before anything imports legalbot.config.
_tmp = Path(tempfile.mkdtemp(prefix="legalbot-test-"))
os.environ["LEGALBOT_DATA_DIR"] = str(_tmp)
os.environ["LEGALBOT_DB_PATH"] = str(_tmp / "test.db")
os.environ["LEGALBOT_DEV"] = "1"

import pytest  # noqa: E402

from legalbot.db import connect  # noqa: E402
from legalbot.ingest import upsert_case  # noqa: E402

SECTION_220 = (
    "JACOBS, Justice:\n"
    "Westland brought this action under Section 220 of the Delaware General Corporation Law to inspect "
    "books and records. A stockholder seeking inspection must show a proper purpose by a preponderance of "
    "the evidence. The stockholder must present some evidence to suggest a credible basis from which the "
    "court can infer possible mismanagement that would warrant further investigation. See 923 A.2d 810.\n"
    "We affirm the judgment of the Court of Chancery."
)

CASES = [
    {
        "id": 1001,
        "name": "CITY OF WESTLAND POLICE & FIRE RETIREMENT SYSTEM v. AXCELIS TECHNOLOGIES, INC.",
        "name_abbreviation": "City of Westland Police & Fire Retirement System v. Axcelis Technologies, Inc.",
        "decision_date": "2010-08-11",
        "docket_number": "No. 594, 2009",
        "first_page": "281", "last_page": "291",
        "citations": [{"type": "official", "cite": "1 A.3d 281"}],
        "court": {"name": "Delaware Supreme Court", "name_abbreviation": "Del."},
        "jurisdiction": {"name_long": "Delaware"},
        "casebody": {"head_matter": "Supreme Court of Delaware.", "opinions": [
            {"type": "majority", "author": "JACOBS, Justice:", "text": SECTION_220},
        ]},
        "cites_to": [{"cite": "923 A.2d 810", "case_ids": [1002]}],
    },
    {
        "id": 1002,
        "name": "SECURITY FIRST CORP. v. U.S. DIE CASTING",
        "name_abbreviation": "Security First Corp. v. U.S. Die Casting & Development Co.",
        "decision_date": "1997-01-07",
        "citations": [{"type": "official", "cite": "923 A.2d 810"}],
        "court": {"name": "Delaware Supreme Court", "name_abbreviation": "Del."},
        "jurisdiction": {"name_long": "Delaware"},
        "casebody": {"opinions": [
            {"type": "majority", "author": "WALSH, Justice:", "text": "A stockholder's books and records demand under Section 220 requires a credible basis to infer mismanagement."},
        ]},
        "cites_to": [],
    },
    {
        "id": 1003,
        "name": "COMMONWEALTH v. SMITH",
        "name_abbreviation": "Commonwealth v. Smith",
        "decision_date": "1985-03-02",
        "citations": [{"type": "official", "cite": "490 A.2d 1000"}],
        "court": {"name": "Supreme Court of Pennsylvania", "name_abbreviation": "Pa."},
        "jurisdiction": {"name_long": "Pennsylvania"},
        "casebody": {"opinions": [
            {"type": "majority", "author": "NIX, C.J.:", "text": "The search of the vehicle without a warrant violated the Fourth Amendment. Suppression of the evidence is required."},
            {"type": "dissent", "author": "HUTCHINSON, J.:", "text": "I would hold the automobile exception applies."},
        ]},
        "cites_to": [],
    },
    {
        "id": 1004,
        "name": "LATER v. CASE",
        "name_abbreviation": "Later v. Case",
        "decision_date": "2015-05-05",
        "citations": [{"type": "official", "cite": "110 A.3d 50"}],
        "court": {"name": "Delaware Supreme Court", "name_abbreviation": "Del."},
        "jurisdiction": {"name_long": "Delaware"},
        "casebody": {"opinions": [
            {"type": "majority", "author": "STRINE, C.J.:", "text": "To the extent Security First, 923 A.2d 810, suggested otherwise, it is overruled."},
        ]},
        "cites_to": [{"cite": "923 A.2d 810", "case_ids": [1002]}],
    },
]


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "cases.db")
    with c:
        for case in CASES:
            upsert_case(c, case)
    yield c
    c.close()


@pytest.fixture
def zip_dir(tmp_path):
    raw = tmp_path / "raw" / "a3d"
    raw.mkdir(parents=True)
    # Two volumes whose entries share file names: the old extract-to-one-directory approach lost one of them.
    for volume, case in (("1", CASES[0]), ("2", CASES[2])):
        with zipfile.ZipFile(raw / f"{volume}.zip", "w") as zf:
            zf.writestr("json/0001-01.json", json.dumps(case))
            zf.writestr("metadata/CasesMetadata.json", "[]")
    return tmp_path / "raw"
