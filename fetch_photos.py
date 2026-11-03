#!/usr/bin/env python3
"""Download the people photos and the SIB logo into data/photos/.

sib.swiss sends Cross-Origin-Resource-Policy: same-site on its images, so the
graph page cannot show them directly from another site. The photos are kept in
the repository instead, and the site build copies them from data/photos/.

Files are named after the last part of their URL. Existing files are skipped,
so rerunning only fetches new photos.

Usage: python3 fetch_photos.py
"""
import json
import os
import sys
from urllib.parse import urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
PHOTO_DIR = os.path.join(HERE, "data", "photos")
LOGO = "https://www.sib.swiss/themes/custom/sib/logo_emblem.svg"


def log(msg):
    print(msg, file=sys.stderr)


def main():
    with open(os.path.join(HERE, "people.json"), encoding="utf-8") as f:
        people = json.load(f)
    urls = [p["image"] for p in people if p.get("image")] + [LOGO]

    names = {}
    for url in urls:
        name = urlparse(url).path.split("/")[-1]
        if name in names and names[name] != url:
            sys.exit(f"two different photos are called {name}: {names[name]} and {url}")
        names[name] = url

    os.makedirs(PHOTO_DIR, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = "sib-group-people-rdf photo fetch"
    fetched = skipped = 0
    for name, url in sorted(names.items()):
        dst = os.path.join(PHOTO_DIR, name)
        if os.path.exists(dst) and os.path.getsize(dst) > 0:
            skipped += 1
            continue
        r = session.get(url, timeout=60)
        r.raise_for_status()
        with open(dst, "wb") as f:
            f.write(r.content)
        fetched += 1
    log(f"photos in {PHOTO_DIR}: {fetched} fetched, {skipped} already there")


if __name__ == "__main__":
    main()
