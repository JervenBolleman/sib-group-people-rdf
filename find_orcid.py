#!/usr/bin/env python3
"""Find ORCID iDs for the people in people.json and write orcid.json.

A person is accepted automatically only when exactly one ORCID search hit has the same
family and given name and lists "SIB Swiss Institute of Bioinformatics" as an institution.
Everything else is recorded as "ambiguous" or "not-found" with its name-matching
candidates, for review.

Decisions go in orcid_overrides.json as {"<slug>": "0000-0000-0000-0000"}, or null to
leave a person without an iD. Overrides win over the automatic result.

Usage: python3 find_orcid.py [--people people.json] [--out orcid.json]
"""
import argparse
import json
import os
import sys
import time

import requests

from crawl_sib import norm

HERE = os.path.dirname(os.path.abspath(__file__))
SEARCH = "https://pub.orcid.org/v3.0/expanded-search/"
SIB_INSTITUTION = "swiss institute of bioinformatics"  # lowercase, matched case-insensitively
DELAY = 0.5  # seconds between requests


def log(msg):
    print(msg, file=sys.stderr)


def name_parts(name):
    """Return (normalized given name, normalized family name variants) for a directory name."""
    tokens = name.split()
    given = norm(tokens[0])
    families = {norm(" ".join(tokens[1:])), norm(tokens[-1])} - {""}
    return given, families


def name_matches(hit, name):
    given, families = name_parts(name)
    hit_given = (hit.get("given-names") or "").split()
    hit_family = norm(hit.get("family-names") or "")
    return bool(hit_given) and norm(hit_given[0]) == given and hit_family in families


def at_sib(hit):
    # Records spell it "SIB Swiss Institute of Bioinformatics", "Swiss Institute of
    # Bioinformatics Geneva", and so on.
    return any(SIB_INSTITUTION in inst.lower() for inst in hit.get("institution-name") or [])


def search(session, name):
    """Search ORCID for each surname form of the person (e.g. "de Carvalho" and "Carvalho")."""
    tokens = name.split()
    given = tokens[0]
    surnames = {" ".join(tokens[1:]), tokens[-1]} - {""}
    hits = {}
    for surname in sorted(surnames):
        q = f'family-name:"{surname}" AND given-names:"{given}"'
        time.sleep(DELAY)
        r = session.get(SEARCH, params={"q": q, "rows": 50}, headers={"Accept": "application/json"}, timeout=60)
        r.raise_for_status()
        for hit in r.json().get("expanded-result") or []:
            hits[hit["orcid-id"]] = hit
    return list(hits.values())


def decide(name, hits):
    matching = [h for h in hits if name_matches(h, name)]
    at = [h for h in matching if at_sib(h)]
    orcids = sorted({h["orcid-id"] for h in at})
    if len(orcids) == 1:
        return {"orcid": orcids[0], "status": "auto"}, matching
    if len(orcids) > 1:
        return {"orcid": None, "status": "ambiguous"}, matching
    return {"orcid": None, "status": "not-found"}, matching


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--people", default=os.path.join(HERE, "people.json"))
    ap.add_argument("--out", default=os.path.join(HERE, "orcid.json"))
    args = ap.parse_args()

    with open(args.people, encoding="utf-8") as f:
        people = json.load(f)
    overrides = {}
    override_path = os.path.join(HERE, "orcid_overrides.json")
    if os.path.exists(override_path):
        with open(override_path, encoding="utf-8") as f:
            overrides = json.load(f)

    session = requests.Session()
    records = {}
    for person in people:
        slug, name = person["slug"], person["name"]
        hits = search(session, name)
        record, candidates = decide(name, hits)
        record["name"] = name
        if not record["orcid"] and candidates:
            record["candidates"] = [
                {
                    "orcid": c["orcid-id"],
                    "name": f"{c.get('given-names')} {c.get('family-names')}",
                    "institutions": c.get("institution-name") or [],
                }
                for c in candidates
            ]
        if slug in overrides:
            record["orcid"] = overrides[slug]
            record["status"] = "override" if overrides[slug] else "excluded"
        records[slug] = record

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(records, f, ensure_ascii=False, indent=1, sort_keys=True)

    counts = {}
    for record in records.values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    log(f"wrote {args.out}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
