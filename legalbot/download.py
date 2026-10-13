"""Download Caselaw Access Project volume zips from static.case.law.

Zips are saved as data/raw/<reporter>/<volume>.zip. (Every reporter numbers its volumes from 1,
so saving them all as data/raw/<volume>.zip makes different reporters' volumes collide.)

    python -m legalbot.download --list                     # show available reporter slugs
    python -m legalbot.download a3d a2d                    # every volume of A.3d and A.2d
    python -m legalbot.download a3d --volumes 1-50
"""
import argparse
import re
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

from .config import CAP_BASE_URL, RAW_DIR

session = requests.Session()


def list_links(url: str) -> list[str]:
    response = session.get(url, timeout=60)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    return [requests.compat.urljoin(url, a["href"]) for a in soup.find_all("a", href=True)]


def list_reporters() -> list[str]:
    return sorted(
        link.rstrip("/").rsplit("/", 1)[-1]
        for link in list_links(CAP_BASE_URL)
        if link.startswith(CAP_BASE_URL) and link.endswith("/") and link != CAP_BASE_URL
    )


def volume_zips(reporter: str) -> dict[str, str]:
    """Map volume name -> zip URL for one reporter."""
    zips = {}
    for link in list_links(f"{CAP_BASE_URL}{reporter}/"):
        m = re.search(rf"/{re.escape(reporter)}/([^/]+)\.zip$", link)
        if m:
            zips[m.group(1)] = link
    return zips


def parse_volumes(spec: str | None) -> set[str] | None:
    if not spec:
        return None
    volumes = set()
    for part in spec.split(","):
        lo, _, hi = part.partition("-")
        volumes.update(str(v) for v in range(int(lo), int(hi or lo) + 1))
    return volumes


def download(reporter: str, volumes: set[str] | None = None, raw_dir: Path = RAW_DIR) -> None:
    dest_dir = raw_dir / reporter
    dest_dir.mkdir(parents=True, exist_ok=True)
    targets = {v: url for v, url in volume_zips(reporter).items() if volumes is None or v in volumes}
    for volume, url in tqdm(sorted(targets.items()), desc=reporter):
        dest = dest_dir / f"{volume}.zip"
        if dest.exists():
            continue
        tmp = dest.with_suffix(".part")
        with session.get(url, stream=True, timeout=120) as response:
            response.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in response.iter_content(chunk_size=1 << 16):
                    f.write(chunk)
        tmp.rename(dest)  # only complete downloads get the .zip name


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("reporters", nargs="*", help="Reporter slugs, e.g. a2d a3d")
    parser.add_argument("--volumes", help="Volume numbers, e.g. 1-20,35")
    parser.add_argument("--list", action="store_true", help="List reporter slugs and exit")
    args = parser.parse_args()
    if args.list or not args.reporters:
        print("\n".join(list_reporters()))
        return
    for reporter in args.reporters:
        download(reporter, parse_volumes(args.volumes))


if __name__ == "__main__":
    main()
