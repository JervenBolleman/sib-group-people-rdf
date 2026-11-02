#!/usr/bin/env python3
"""Find ROR ids for the institutions in institutions.json and write ror.json.

A name is accepted automatically only when exactly one active Swiss ROR record has a
name, alias or acronym equal to it (case and accents ignored). Everything else is
recorded as "ambiguous" or "not-found" with the top candidates, for review.

Decisions go in ror_overrides.json as {"<name>": "https://ror.org/..."}, or null to
leave an institution without a ROR id. Overrides win over the automatic result.

Usage: python3 find_ror.py [--institutions institutions.json] [--out ror.json]
"""
import argparse
import json
import os
import sys
import time

import requests

from crawl_sib import norm

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.ror.org/v2/organizations"
DELAY = 0.5  # seconds between requests
CANDIDATES = 5


def log(msg):
    print(msg, file=sys.stderr)


def search(session, name):
    time.sleep(DELAY)
    r = session.get(
        API,
        params={"query": name, "filter": "country.country_code:CH"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json().get("items") or []


def all_names(item):
    return [n["value"] for n in item.get("names") or []]


def decide(name, items):
    wanted = norm(name)
    exact = [
        it for it in items
        if it.get("status") == "active" and any(norm(v) == wanted for v in all_names(it))
    ]
    ids = sorted({it["id"] for it in exact})
    if len(ids) == 1:
        return {"ror": ids[0], "status": "auto"}
    if len(ids) > 1:
        return {"ror": None, "status": "ambiguous"}
    return {"ror": None, "status": "not-found"}


def candidates(items):
    return [
        {"ror": it["id"], "names": all_names(it)[:4]}
        for it in items[:CANDIDATES]
    ]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--institutions", default=os.path.join(HERE, "institutions.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "ror.json"))
    args = ap.parse_args()

    with open(args.institutions, encoding="utf-8") as f:
        names = json.load(f)
    overrides = {}
    override_path = os.path.join(HERE, "ror_overrides.json")
    if os.path.exists(override_path):
        with open(override_path, encoding="utf-8") as f:
            overrides = json.load(f)

    session = requests.Session()
    records = {}
    for name in names:
        items = search(session, name)
        record = decide(name, items)
        record["name"] = name
        if not record["ror"]:
            record["candidates"] = candidates(items)
        if name in overrides:
            record["ror"] = overrides[name]
            record["status"] = "override" if overrides[name] else "excluded"
        records[name] = record

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1, sort_keys=True)

    counts = {}
    for record in records.values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    log(f"wrote {args.out}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
