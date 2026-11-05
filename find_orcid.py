#!/usr/bin/env python3
"""Find ORCID iDs for the people in data/people.tsv and write data/orcid.tsv.

A person is accepted automatically only when exactly one ORCID search hit has the same
family and given name and lists "SIB Swiss Institute of Bioinformatics" as an institution.
Everything else is recorded as "ambiguous" or "not-found" with its name-matching
candidates, for review.

iDs listed in data/known_orcids.tsv are used as they are, and are not searched for.

Decisions go in data/orcid_overrides.tsv as slug and ORCID, one per line. An empty ORCID
leaves the person without an iD. Overrides win over the automatic result.

Usage: python3 find_orcid.py
"""
import os
import sys
import time

import requests

from crawl_sib import norm, read_known_orcids, read_tsv, write_tsv

HERE = os.path.dirname(os.path.abspath(__file__))
PEOPLE = os.path.join(HERE, "data", "people.tsv")
OUT = os.path.join(HERE, "data", "orcid.tsv")
OVERRIDES = os.path.join(HERE, "data", "orcid_overrides.tsv")
COLUMNS = ["slug", "name", "orcid", "status", "candidates", "error"]
SEARCH = "https://pub.orcid.org/v3.0/expanded-search/"
SIB_INSTITUTION = "swiss institute of bioinformatics"  # lowercase, matched case-insensitively
DELAY = 0.5  # seconds between requests
RETRIES = 4  # attempts per request before a person is recorded as "error"


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


def get_hits(session, q):
    """Run one ORCID search, retrying with a growing pause when the service is slow or down."""
    for attempt in range(RETRIES):
        time.sleep(DELAY)
        try:
            r = session.get(SEARCH, params={"q": q, "rows": 50}, headers={"Accept": "application/json"}, timeout=120)
            r.raise_for_status()
            return r.json().get("expanded-result") or []
        except requests.RequestException:
            if attempt == RETRIES - 1:
                raise
            time.sleep(10 * 2 ** attempt)


def search(session, name):
    """Search ORCID for each surname form of the person (e.g. "de Carvalho" and "Carvalho")."""
    tokens = name.split()
    given = tokens[0]
    surnames = {" ".join(tokens[1:]), tokens[-1]} - {""}
    hits = {}
    for surname in sorted(surnames):
        q = f'family-name:"{surname}" AND given-names:"{given}"'
        for hit in get_hits(session, q):
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


def candidate_text(candidates):
    """One line per candidate for the TSV: iD, name, then institutions in brackets."""
    return "; ".join(
        f"{c['orcid-id']} {c.get('given-names')} {c.get('family-names')} "
        f"({', '.join(c.get('institution-name') or [])})"
        for c in candidates
    )


def read_overrides():
    return {row["slug"]: row["orcid"] for row in read_tsv(OVERRIDES)}


def save(records):
    rows = [dict(records[slug], slug=slug) for slug in sorted(records)]
    write_tsv(OUT, COLUMNS, rows)


def main():
    people = read_tsv(PEOPLE)
    overrides = read_overrides()

    # Decisions from an earlier run are reused, so a rerun only searches people who
    # are new, changed name, or failed last time.
    previous = {row["slug"]: row for row in read_tsv(OUT)}
    known_slugs = {iri.rsplit("/", 1)[-1]: orcid for iri, orcid in read_known_orcids().items()}

    session = requests.Session()
    records = {}
    for i, person in enumerate(people, 1):
        slug, name = person["slug"], person["name"]
        old = previous.get(slug)
        if slug in known_slugs:
            # Listed in known_orcids.tsv, so no search is needed.
            record = {"orcid": known_slugs[slug], "status": "known", "name": name, "candidates": "", "error": ""}
        elif old and old["name"] == name and old["status"] != "error":
            record = dict(old)
        else:
            try:
                hits = search(session, name)
            except requests.RequestException as e:
                record = {"orcid": "", "status": "error", "name": name, "candidates": "", "error": str(e)}
                log(f"search failed for {name}: {e}")
            else:
                decided, candidates = decide(name, hits)
                record = {
                    "orcid": decided["orcid"] or "",
                    "status": decided["status"],
                    "name": name,
                    "candidates": "" if decided["orcid"] else candidate_text(candidates),
                    "error": "",
                }
        if slug in overrides:
            record["orcid"] = overrides[slug]
            record["status"] = "override" if overrides[slug] else "excluded"
        records[slug] = record
        if i % 25 == 0:
            save(records)
            log(f"{i}/{len(people)} done")

    save(records)

    counts = {}
    for record in records.values():
        counts[record["status"]] = counts.get(record["status"], 0) + 1
    log(f"wrote {OUT}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))


if __name__ == "__main__":
    main()
