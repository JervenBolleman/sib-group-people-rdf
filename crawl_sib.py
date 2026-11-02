#!/usr/bin/env python3
"""Crawl SIB groups, group directories, people, publications and courses into schema.org Turtle.

Sources:
  - https://www.sib.swiss/groups?sib_hub        group list (data from the page's search endpoint)
  - https://www.sib.swiss/directory/group/<slug> group members
  - https://www.sib.swiss/directory/person/<slug> person name and job title
  - https://www.sib.swiss/community/publications[/scientific-publications-<year>]
  - https://www.sib.swiss/training/past-training-courses and course pages (instructors)

Papers and courses are only linked to people that were found in a group directory.
Matching is by name: author "Barbie V" matches "Valerie Barbie" when the surname and
first initial agree. Common surnames can give false links, so review before use.

Usage: python3 crawl_sib.py [--out data/sib.ttl] [--cache cache] [--refresh] [--no-courses]
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import unicodedata
from urllib.parse import quote, urljoin

import requests
from lxml import html as lxml_html

HERE = os.path.dirname(os.path.abspath(__file__))
BASE = "https://www.sib.swiss"
ROR = "https://ror.org/002n09z45"
UA = "Mozilla/5.0 (sib-group-people-rdf crawler)"
DELAY = 0.5  # seconds between requests, to be polite to the site

DOI_RE = re.compile(r"doi\.org/(10\.\S+)")
YEAR_LINK_RE = re.compile(r"/community/publications/scientific-publications-(\d{4})")
COURSE_LINK_RE = re.compile(r"/training/course/([\w-]+)")


def log(msg):
    print(msg, file=sys.stderr)


class Fetcher:
    """GET with an on-disk cache, and POST for the site's JSON search endpoints."""

    def __init__(self, cache_dir, refresh):
        self.cache_dir = cache_dir
        self.refresh = refresh
        self.session = requests.Session()
        self.session.headers["User-Agent"] = UA
        os.makedirs(cache_dir, exist_ok=True)

    def _path(self, key):
        return os.path.join(self.cache_dir, hashlib.sha1(key.encode("utf-8")).hexdigest() + ".txt")

    def get(self, url):
        """Return the page text, or None if the page does not exist (404)."""
        path = self._path(url)
        if os.path.exists(path) and not self.refresh:
            with open(path, encoding="utf-8") as f:
                return f.read()
        time.sleep(DELAY)
        r = self.session.get(url, timeout=60)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        with open(path, "w", encoding="utf-8") as f:
            f.write(r.text)
        return r.text

    def post_json(self, url, payload):
        time.sleep(DELAY)
        r = self.session.post(
            url,
            json=payload,
            headers={"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"},
            timeout=60,
        )
        r.raise_for_status()
        return r.json()


def norm(text):
    """Lowercase ASCII letters only, so 'Valérie Barbié' and 'valerie barbie' compare equal."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^a-z]", "", text.lower())


def clean(text):
    return " ".join(text.split())


# ---------------------------------------------------------------- groups

def crawl_groups(fetcher):
    """Return {slug: {"name": str, "hub": bool}} for every group on the groups page."""
    page = fetcher.get(BASE + "/groups?sib_hub")
    # The listing is filled in by Alpine.js from /index-search-ajax/; its settings are
    # embedded (HTML-escaped) in the page as the argument of indexSearch('groups', ...).
    m = re.search(r"indexSearch\('groups', (\{.*?\})\)\"", page)
    settings = json.loads(html.unescape(m.group(1)))
    fields = {"fields_of_activity": [], "fields_of_application": [], "city": []}

    first = fetcher.post_json(
        BASE + "/index-search-ajax/search/groups",
        {"query": "", "fields": fields, "settings": settings, "updated": "init"},
    )
    fragments = [first["results"]]
    for p in range(2, first["totalPages"] + 1):
        more = fetcher.post_json(
            BASE + "/index-search-ajax/paginate/groups",
            {"query": "", "fields": fields, "settings": settings, "page": p},
        )
        fragments.append(more["results"])

    groups = {}
    for fragment in fragments:
        tree = lxml_html.fromstring(fragment)
        for card in tree.xpath('//div[contains(@class,"group-search-result")]'):
            link = card.xpath('.//a[@href]')[0]
            slug = link.get("href").strip("/")
            groups[slug] = {
                "name": clean(card.xpath("string(.//h5)")),
                "hub": "sib-hub" in card.get("class").split(),
            }
    return groups


def group_member_slugs(fetcher, group_slug):
    """Return (leader slugs, member slugs) from the group directory page."""
    page = fetcher.get(f"{BASE}/directory/group/{group_slug}")
    if page is None:
        return [], []
    tree = lxml_html.fromstring(page)

    def slugs(section):
        hrefs = tree.xpath(
            '//div[contains(@class,"%s")]//a[contains(@class,"person-link")]/@href' % section
        )
        return [h.rstrip("/").rsplit("/", 1)[-1] for h in hrefs]

    return slugs("group-members--group_leaders"), slugs("group-members--group_members")


# ---------------------------------------------------------------- people

def crawl_person(fetcher, slug):
    page = fetcher.get(f"{BASE}/directory/person/{slug}")
    if page is None:
        return None
    tree = lxml_html.fromstring(page)
    name = clean(tree.xpath('string((//div[contains(@class,"directory-person")]//h1)[1])'))
    job = clean(tree.xpath('string((//div[contains(@class,"person-job-title")])[1])'))
    photo = tree.xpath('//img[starts-with(@alt,"Photo of")]/@src')
    image = urljoin(BASE, photo[0]) if photo else ""
    return {"slug": slug, "name": name, "jobTitle": job, "image": image}


# ---------------------------------------------------------------- publications

def parse_author(text):
    """'Laman Trip DS' -> ('Laman Trip', 'D'). Trailing all-caps tokens are initials."""
    tokens = text.split()
    initials = []
    while len(tokens) > 1 and re.fullmatch(r"[A-Z][A-Z.\-]*", tokens[-1]):
        initials.insert(0, tokens.pop())
    if not tokens or not initials:
        return None
    return " ".join(tokens), initials[0][0]


def parse_publication(li, year):
    links = li.xpath(".//a[@href]")
    if not links:
        return None
    title = clean(links[0].text_content())
    if not title:
        return None
    m = DOI_RE.search(links[0].get("href"))
    doi = m.group(1) if m else None
    full = clean(li.text_content())
    author_part = full.split(title, 1)[0].strip().rstrip(",").strip()
    authors = []
    for token in re.split(r",\s*|\s&\s", author_part):
        token = token.strip().rstrip(".")
        if token:
            parsed = parse_author(token)
            if parsed:
                authors.append(parsed)
    return {"title": title, "doi": doi, "year": year, "authors": authors}


def crawl_publications(fetcher):
    landing = fetcher.get(BASE + "/community/publications")
    years = sorted(set(YEAR_LINK_RE.findall(landing)))
    log(f"publication years: {', '.join(years)}")
    pubs = []
    for year in years:
        page = fetcher.get(f"{BASE}/community/publications/scientific-publications-{year}")
        if page is None:
            continue
        tree = lxml_html.fromstring(page)
        for li in tree.xpath('//div[contains(@class,"prose")]//ol/li'):
            pub = parse_publication(li, year)
            if pub:
                pubs.append(pub)
    return pubs


# ---------------------------------------------------------------- courses

def crawl_courses(fetcher):
    """Return [{"slug", "name", "instructors": [str]}] for past and upcoming courses."""
    slugs = set()
    past = fetcher.get(BASE + "/training/past-training-courses")
    slugs.update(COURSE_LINK_RE.findall(past))
    upcoming = json.loads(fetcher.get(BASE + "/training-api/upcoming-training-courses"))
    slugs.update(COURSE_LINK_RE.findall(upcoming["render"]))
    log(f"courses to read: {len(slugs)}")

    courses = []
    for slug in sorted(slugs):
        try:
            page = fetcher.get(f"{BASE}/training/course/{slug}")
        except requests.RequestException as e:
            log(f"skipping course {slug}: {e}")
            continue
        if page is None:
            continue
        tree = lxml_html.fromstring(page)
        name = clean(tree.xpath("string((//h1)[1])"))
        instructors = []
        for node in tree.xpath(
            '//img[contains(@src,"chalkboard-teacher")]/ancestor::div[contains(@class,"flex")][1]'
        ):
            for part in re.split(r",| and | & ", clean(node.text_content())):
                if part.strip():
                    instructors.append(part.strip())
        courses.append({"slug": slug, "name": name, "instructors": instructors})
    return courses


# ---------------------------------------------------------------- RDF output

def lit(text):
    text = text.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")
    return '"' + text + '"'


def ref(iri):
    return "<" + iri + ">"


class Graph:
    def __init__(self):
        self.subjects = {}  # subject IRI -> list of (predicate, object) strings

    def add(self, subject, predicate, obj):
        props = self.subjects.setdefault(subject, [])
        if (predicate, obj) not in props:
            props.append((predicate, obj))

    def serialize(self, path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("@prefix schema: <https://schema.org/> .\n\n")
            for subject, props in self.subjects.items():
                body = " ;\n    ".join(f"{p} {o}" for p, o in props)
                f.write(f"{ref(subject)}\n    {body} .\n\n")


def add_sib_organization(graph):
    graph.add(ROR, "a", "schema:Organization")
    graph.add(ROR, "schema:name", lit("SIB Swiss Institute of Bioinformatics"))
    graph.add(ROR, "schema:url", ref(BASE + "/"))
    graph.add(
        ROR,
        "schema:identifier",
        '[ a schema:PropertyValue ; schema:propertyID "ROR" ; schema:value %s ]' % ref(ROR),
    )


PERSON_IRI = {}  # person slug -> node IRI: the ORCID iD when known, else the directory URL


def directory_url(slug):
    return f"{BASE}/directory/person/{slug}"


def person_iri(slug):
    return PERSON_IRI.get(slug, directory_url(slug))


def write_people(people, memberships):
    rows = [dict(people[s], groups=sorted(memberships[s])) for s in sorted(people)]
    with open(os.path.join(HERE, "people.json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)


def load_orcids(people):
    """Use the ORCID iD as the node IRI for each person that has one in orcid.json."""
    path = os.path.join(HERE, "orcid.json")
    if not os.path.exists(path):
        return
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    taken = {}
    for slug in sorted(records):
        orcid = records[slug].get("orcid")
        if not orcid or slug not in people:
            continue
        if orcid in taken:
            log(f"duplicate ORCID {orcid} for {slug} and {taken[orcid]}; keeping directory URL for {slug}")
            continue
        taken[orcid] = slug
        PERSON_IRI[slug] = f"https://orcid.org/{orcid}"
    log(f"people with an ORCID node IRI: {len(PERSON_IRI)}")


def group_iri(slug):
    return f"{BASE}/{slug}"


def doi_iri(doi):
    return "https://doi.org/" + quote(doi, safe="/:()-._;<>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=os.path.join(HERE, "data", "sib.ttl"))
    ap.add_argument("--cache", default=os.path.join(HERE, "cache"))
    ap.add_argument("--refresh", action="store_true", help="ignore cached pages and refetch")
    ap.add_argument("--no-courses", action="store_true", help="skip the training course crawl")
    args = ap.parse_args()

    fetcher = Fetcher(args.cache, args.refresh)

    groups = crawl_groups(fetcher)
    log(f"groups: {len(groups)} ({sum(g['hub'] for g in groups.values())} at the SIB hub)")

    # person slug -> set of group slugs they belong to
    memberships = {}
    for slug in groups:
        leaders, members = group_member_slugs(fetcher, slug)
        for person in leaders + members:
            memberships.setdefault(person, set()).add(slug)
    log(f"people in group directories: {len(memberships)}")

    people = {}
    for slug in sorted(memberships):
        person = crawl_person(fetcher, slug)
        if person:
            people[slug] = person

    write_people(people, memberships)
    load_orcids(people)

    pubs = crawl_publications(fetcher)
    log(f"publications: {len(pubs)}")

    courses = [] if args.no_courses else crawl_courses(fetcher)
    log(f"courses: {len(courses)}")

    # Name index for matching authors and instructors to people.
    by_full_name = {}
    for slug, person in people.items():
        by_full_name.setdefault(norm(person["name"]), []).append(slug)

    def match_author(family, initial):
        hits = []
        for slug, person in people.items():
            tokens = person["name"].split()
            if not tokens or norm(tokens[0])[:1] != initial.lower():
                continue
            families = {norm(" ".join(tokens[1:])), norm(tokens[-1])}
            if norm(family) in families:
                hits.append(slug)
        return hits

    graph = Graph()
    add_sib_organization(graph)

    for slug, group in groups.items():
        iri = group_iri(slug)
        graph.add(iri, "a", "schema:Organization")
        graph.add(iri, "schema:name", lit(group["name"]))
        graph.add(iri, "schema:url", ref(iri))
        if group["hub"]:
            graph.add(iri, "schema:parentOrganization", ref(ROR))

    for slug, person in people.items():
        iri = person_iri(slug)
        graph.add(iri, "a", "schema:Person")
        graph.add(iri, "schema:name", lit(person["name"]))
        if person["image"]:
            graph.add(iri, "schema:image", ref(person["image"]))
        if person["jobTitle"]:
            graph.add(iri, "schema:jobTitle", lit(person["jobTitle"]))
        graph.add(iri, "schema:url", ref(directory_url(slug)))
        graph.add(iri, "schema:worksFor", ref(ROR))
        for group_slug in sorted(memberships[slug]):
            graph.add(iri, "schema:memberOf", ref(group_iri(group_slug)))

    linked_pubs = 0
    for pub in pubs:
        authors = set()
        for family, initial in pub["authors"]:
            authors.update(match_author(family, initial))
        if not authors:
            continue
        linked_pubs += 1
        iri = doi_iri(pub["doi"]) if pub["doi"] else f"{BASE}/community/publications#{hashlib.sha1(pub['title'].encode('utf-8')).hexdigest()[:12]}"
        graph.add(iri, "a", "schema:ScholarlyArticle")
        graph.add(iri, "schema:name", lit(pub["title"]))
        graph.add(iri, "schema:datePublished", lit(pub["year"]))
        if pub["doi"]:
            graph.add(iri, "schema:identifier", lit(pub["doi"]))
            graph.add(iri, "schema:url", ref(iri))
        for slug in sorted(authors):
            graph.add(iri, "schema:author", ref(person_iri(slug)))

    linked_courses = 0
    for course in courses:
        instructors = set()
        for name in course["instructors"]:
            instructors.update(by_full_name.get(norm(name), []))
        if not instructors:
            continue
        linked_courses += 1
        iri = f"{BASE}/training/course/{course['slug']}"
        graph.add(iri, "a", "schema:Course")
        graph.add(iri, "schema:name", lit(course["name"]))
        graph.add(iri, "schema:url", ref(iri))
        graph.add(iri, "schema:provider", ref(ROR))
        for slug in sorted(instructors):
            graph.add(iri, "schema:instructor", ref(person_iri(slug)))

    graph.serialize(args.out)
    log(
        f"wrote {args.out}: {len(groups)} groups, {len(people)} people, "
        f"{linked_pubs} publications with SIB authors, {linked_courses} courses with SIB instructors"
    )


if __name__ == "__main__":
    main()
