#!/usr/bin/env python3
"""Compare each person's ORCID works with the publications the crawl linked to them.

For every person with an ORCID iD (orcid.json) this fetches the works and the
employments on their ORCID record, then compares the works with the papers that
data/sib.ttl links to the person. A paper matches on DOI, or on a normalized title
when there is no DOI.

Outputs:
  data/orcid_works.json   the ORCID works per person
  logs/orcid_works.log    the differences per person, and the status of each iD

A person is "verified" when they have at least one shared paper and a SIB
employment on the record. "Likely" is a shared paper without a SIB employment.
Anyone else with an iD stays "unverified" in the log. The known list
(data/known_orcids.tsv) is maintained by hand, based on this log.

Usage: python3 check_orcid_works.py
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://pub.orcid.org/v3.0"
SIB_NAME = "swiss institute of bioinformatics"
DELAY = 0.5
RETRIES = 4
EXAMPLES = 5


def log_line(fh, msg=""):
    fh.write(msg + "\n")


def norm_title(text):
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def get_json(session, url):
    for attempt in range(RETRIES):
        time.sleep(DELAY)
        try:
            r = session.get(url, timeout=120)
            r.raise_for_status()
            return r.json()
        except requests.RequestException:
            if attempt == RETRIES - 1:
                raise
            time.sleep(10 * 2 ** attempt)


def fetch_works(session, orcid):
    data = get_json(session, f"{API}/{orcid}/works")
    works = []
    for group in data.get("group", []):
        dois = [
            e["external-id-value"].lower()
            for e in (group.get("external-ids") or {}).get("external-id", [])
            if e.get("external-id-type") == "doi"
        ]
        for summary in group.get("work-summary", [])[:1]:
            title = ((summary.get("title") or {}).get("title") or {}).get("value") or ""
            year = ((summary.get("publication-date") or {}).get("year") or {}).get("value")
            works.append({"doi": dois[0] if dois else None, "title": title, "year": year})
    return works


def fetch_sib_employment(session, orcid):
    data = get_json(session, f"{API}/{orcid}/employments")
    for group in data.get("affiliation-group", []):
        for summary in group.get("summaries", []):
            org = (summary.get("employment-summary") or {}).get("organization") or {}
            if SIB_NAME in (org.get("name") or "").lower():
                return True
    return False


def load_sib_links():
    """Return {orcid-or-directory IRI: [(doi or None, normalized title, display title)]} from the Turtle."""
    links = {}
    text = open(os.path.join(HERE, "data", "sib.ttl"), encoding="utf-8").read()
    for block in text.split("\n\n"):
        if "schema:ScholarlyArticle" not in block:
            continue
        subject = re.search(r"^<([^>]+)>", block, re.M).group(1)
        doi_m = re.search(r'schema:identifier "([^"]+)"', block)
        doi = doi_m.group(1).lower() if doi_m else None
        title_m = re.search(r'schema:name "((?:[^"\\]|\\.)*)"', block)
        title = title_m.group(1).replace('\\"', '"') if title_m else ""
        for author in re.findall(r"schema:author <([^>]+)>", block):
            links.setdefault(author, []).append({"doi": doi, "title": title, "subject": subject})
    return links


def paper_key(p):
    return ("doi", p["doi"]) if p["doi"] else ("title", norm_title(p["title"]))


def describe(items, n=EXAMPLES):
    shown = [f"{i.get('title') or i.get('subject')} [{i.get('year') or ''}] {i.get('doi') or ''}".strip() for i in items[:n]]
    more = f" (+{len(items) - n} more)" if len(items) > n else ""
    return "; ".join(shown) + more


def main():
    people = json.load(open(os.path.join(HERE, "people.json"), encoding="utf-8"))
    orcid_records = json.load(open(os.path.join(HERE, "orcid.json"), encoding="utf-8"))
    sib_links = load_sib_links()
    session = requests.Session()
    session.headers["Accept"] = "application/json"

    works_out = {}
    statuses = {}
    os.makedirs(os.path.join(HERE, "logs"), exist_ok=True)
    with open(os.path.join(HERE, "logs", "orcid_works.log"), "w", encoding="utf-8") as log:
        log_line(log, f"ORCID works check, {date.today().isoformat()}")
        log_line(log, f"people: {len(people)}, with an ORCID iD: "
                      f"{sum(1 for r in orcid_records.values() if r.get('orcid'))}")
        log_line(log)
        for person in people:
            slug, name = person["slug"], person["name"]
            iD = (orcid_records.get(slug) or {}).get("orcid")
            if not iD:
                continue
            works = fetch_works(session, iD)
            has_sib_employment = fetch_sib_employment(session, iD)
            works_out[slug] = {"name": name, "orcid": iD, "works": works, "sib_employment": has_sib_employment}

            ours = sib_links.get(f"https://orcid.org/{iD}", [])
            ours_keys = {paper_key(p): p for p in ours}
            theirs_by_key = {}
            for w in works:
                key = ("doi", w["doi"]) if w["doi"] else ("title", norm_title(w["title"]))
                theirs_by_key[key] = w
            shared = [k for k in ours_keys if k in theirs_by_key]
            only_orcid = [w for k, w in theirs_by_key.items() if k not in ours_keys]
            only_sib = [p for k, p in ours_keys.items() if k not in theirs_by_key]

            if shared and has_sib_employment:
                status = "verified"
            elif shared:
                status = "likely"
            else:
                status = "unverified"
            statuses[status] = statuses.get(status, 0) + 1

            log_line(log, f"{name} ({iD}) - {status}")
            log_line(log, f"  ORCID works: {len(works)}, sib.swiss papers: {len(ours)}, shared: {len(shared)}")
            log_line(log, f"  SIB employment on record: {'yes' if has_sib_employment else 'no'}")
            if only_orcid:
                log_line(log, f"  only on ORCID ({len(only_orcid)}): {describe(only_orcid)}")
            if only_sib:
                log_line(log, f"  only on sib.swiss ({len(only_sib)}): {describe(only_sib)}")
            log_line(log)
            print(f"{name}: {status}", file=sys.stderr)

        log_line(log, "summary: " + ", ".join(f"{k} {v}" for k, v in sorted(statuses.items())))

    with open(os.path.join(HERE, "data", "orcid_works.json"), "w", encoding="utf-8") as f:
        json.dump(works_out, f, ensure_ascii=False, indent=1, sort_keys=True)
    print("wrote data/orcid_works.json and logs/orcid_works.log", file=sys.stderr)


if __name__ == "__main__":
    main()
