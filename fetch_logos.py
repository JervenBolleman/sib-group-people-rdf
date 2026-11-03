#!/usr/bin/env python3
"""Find institution logos on Wikidata and download them into data/logos/.

Each institution has a ROR id (ror.json, plus SIB itself). Wikidata items carry the
ROR id as property P6782, and their logo as P154. Every logo that is found is
saved as data/logos/<ror id>.<ext>, and data/logos.json records the Wikidata item
and the Commons file name, so the page can credit the source.

Usage: python3 fetch_logos.py
"""
import json
import os
import sys
from urllib.parse import unquote, urlparse

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
LOGO_DIR = os.path.join(HERE, "data", "logos")
MAP_PATH = os.path.join(HERE, "data", "logos.json")
SIB_ROR = "002n09z45"
UA = "sib-group-people-rdf/1.0 (https://www.sib.swiss; jerven.bolleman@sib.swiss)"
SPARQL = "https://query.wikidata.org/sparql"


def log(msg):
    print(msg, file=sys.stderr)


def ror_ids():
    with open(os.path.join(HERE, "ror.json"), encoding="utf-8") as f:
        records = json.load(f)
    ids = {r["ror"].rsplit("/", 1)[-1] for r in records.values() if r.get("ror")}
    return sorted(ids | {SIB_ROR})


def find_logos(ids):
    values = " ".join(f'"{i}"' for i in ids)
    query = f"""SELECT ?ror ?item ?logo WHERE {{
  VALUES ?ror {{ {values} }}
  ?item wdt:P6782 ?ror .
  ?item wdt:P154 ?logo .
}}"""
    r = requests.get(SPARQL, params={"query": query, "format": "json"}, headers={"User-Agent": UA}, timeout=120)
    r.raise_for_status()
    found = {}
    for b in r.json()["results"]["bindings"]:
        ror = b["ror"]["value"]
        # Some items have several logos. The first one returned is kept.
        found.setdefault(ror, (b["item"]["value"].rsplit("/", 1)[-1], b["logo"]["value"]))
    return found


def download(session, url, dst):
    r = session.get(url, timeout=120, allow_redirects=True)
    r.raise_for_status()
    with open(dst, "wb") as f:
        f.write(r.content)
    return r.url


def main():
    ids = ror_ids()
    found = find_logos(ids)
    log(f"ROR ids: {len(ids)}, with a Wikidata logo: {len(found)}")

    os.makedirs(LOGO_DIR, exist_ok=True)
    session = requests.Session()
    session.headers["User-Agent"] = UA
    mapping = {}
    for ror_id in ids:
        if ror_id not in found:
            continue
        item, logo_url = found[ror_id]
        commons_name = unquote(urlparse(logo_url).path.rsplit("/", 1)[-1])
        ext = os.path.splitext(commons_name)[1].lower() or ".img"
        dst = os.path.join(LOGO_DIR, f"{ror_id}{ext}")
        if not (os.path.exists(dst) and os.path.getsize(dst) > 0):
            download(session, logo_url, dst)
        mapping[f"https://ror.org/{ror_id}"] = {
            "file": f"logos/{ror_id}{ext}",
            "wikidata": f"https://www.wikidata.org/wiki/{item}",
            "commons": f"https://commons.wikimedia.org/wiki/File:{commons_name.replace(' ', '_')}",
        }

    with open(MAP_PATH, "w", encoding="utf-8") as f:
        json.dump(mapping, f, ensure_ascii=False, indent=1, sort_keys=True)
    log(f"wrote {MAP_PATH} with {len(mapping)} logos")


if __name__ == "__main__":
    main()
