#!/usr/bin/env python3
"""Find ROR ids for the institutions in data/institutions.tsv and write data/ror.tsv.

A name is accepted automatically only when exactly one active Swiss ROR record has a
name, alias or acronym equal to it (case and accents ignored). Everything else is
recorded as "ambiguous" or "not-found" with the top candidates, for review.

Decisions go in data/ror_overrides.tsv as name and ROR id, one per line. An empty ROR
id leaves the institution without one. Overrides win over the automatic result.

Usage: python3 find_ror.py
"""
import argparse
import os
import sys
import time

import requests

from crawl_sib import norm, read_tsv, write_tsv

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.ror.org/v2/organizations"
DELAY = 0.5  # seconds between requests
CANDIDATES = 5
INSTITUTIONS = os.path.join(HERE, "data", "institutions.tsv")
OVERRIDES = os.path.join(HERE, "data", "ror_overrides.tsv")
OUT = os.path.join(HERE, "data", "ror.tsv")
COLUMNS = ["name", "ror", "status", "candidates"]


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


def candidate_text(items):
    """One candidate per item for the TSV: ROR id, then its names separated by bars."""
    return "; ".join(f"{it['id']} {' | '.join(all_names(it)[:4])}" for it in items[:CANDIDATES])


def main():
    names = [row["name"] for row in read_tsv(INSTITUTIONS)]
    overrides = {row["name"]: row["ror"] for row in read_tsv(OVERRIDES)}

    session = requests.Session()
    records = []
    for name in names:
        items = search(session, name)
        record = decide(name, items)
        row = {"name": name, "ror": record["ror"] or "", "status": record["status"],
               "candidates": "" if record["ror"] else candidate_text(items)}
        if name in overrides:
            row["ror"] = overrides[name]
            row["status"] = "override" if overrides[name] else "excluded"
        records.append(row)

    write_tsv(OUT, COLUMNS, records)

    counts = {}
    for row in records:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    log(f"wrote {OUT}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
