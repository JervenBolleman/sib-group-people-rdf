# SIB people and groups as RDF

This project builds a graph of SIB Swiss Institute of Bioinformatics groups, the people in them, their papers and the courses they gave. The data comes from public pages on [sib.swiss](https://www.sib.swiss/) and is written as RDF with [schema.org](https://schema.org/) terms.

The result is published as a static website. It shows the graph as an interactive network, and runs SPARQL queries in the browser with [Comunica](https://comunica.dev/). Nothing is sent to a server.

## SPARQL endpoint

The data can also be queried with SPARQL at https://sib-people-rdf.jerven-bolleman.workers.dev/sparql. The endpoint is built with [oxigraph-cloudflare-webworker](https://github.com/JervenBolleman/oxigraph-cloudflare-webworker).

For example, to count the people:

```sh
curl -H "Accept: application/sparql-results+json" \
  --data-urlencode 'query=PREFIX schema: <https://schema.org/> SELECT (COUNT(?p) AS ?people) WHERE { ?p a schema:Person }' \
  https://sib-people-rdf.jerven-bolleman.workers.dev/sparql
```

## What is in the graph

| Thing | schema.org type | Identified by |
|---|---|---|
| SIB | `schema:Organization` | its ROR id, https://ror.org/002n09z45 |
| Groups | `schema:Organization` | their sib.swiss group page |
| Partner institutions | `schema:Organization` | their ROR id, or a sib.swiss based IRI when there is none |
| People | `schema:Person` | their ORCID iD when it is known, otherwise their sib.swiss directory page |
| Papers | `schema:ScholarlyArticle` | their DOI, or a sib.swiss based IRI when there is none |
| Courses | `schema:Course` | their sib.swiss course page |

The links between them:

* A person is `schema:memberOf` a group.
* A group at the SIB Hub has SIB as its `schema:parentOrganization`.
* A partner group is `schema:memberOf` SIB, and its `schema:parentOrganization` is its own institution.
* A paper has people as `schema:author`.
* A course has people as `schema:instructor`.

Papers and courses are linked to people by name, so a few links may be wrong.

## Repository layout

* `crawl_sib.py` crawls sib.swiss and writes `data/sib.ttl`.
* `find_orcid.py`, `check_orcid_works.py` look up and check ORCID iDs.
* `find_ror.py` looks up ROR ids for partner institutions.
* `fetch_photos.py`, `fetch_logos.py` download people photos and institution logos.
* `export_rdf.py` writes the graph as N-Triples, JSON-LD and RDF/XML.
* `INDEX.md` is the text of the website, including the example queries.
* `site/` holds the website build, its scripts and styles.
* `data/` holds the graph, the lookup tables (TSV), photos and logos.
* `logs/` holds the report of the ORCID check.

## Setup

The Python scripts run in a virtual environment.

```sh
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

The website build needs Node.js 22.

```sh
npm ci
```

## Updating the data

Run the steps in this order. Each step reads what the earlier ones wrote.

1. Crawl sib.swiss. This writes `data/sib.ttl`, `data/people.tsv` and `data/institutions.tsv`. Fetched pages are cached in `cache/`.

   ```sh
   venv/bin/python crawl_sib.py
   ```

2. Look up ORCID iDs and check them against each person's papers.

   ```sh
   venv/bin/python find_orcid.py
   venv/bin/python check_orcid_works.py
   ```

   `find_orcid.py` writes `data/orcid.tsv`, with the candidates it found for each person. `check_orcid_works.py` compares each ORCID record with the papers on sib.swiss and writes the result to `logs/orcid_works.log`. Use the log to decide which iDs to trust, and add them to `data/known_orcids.tsv`. Only iDs in that file are used in the graph.

3. Look up ROR ids for partner institutions.

   ```sh
   venv/bin/python find_ror.py
   ```

   This writes `data/ror.tsv`. Names that do not match one ROR record exactly are left for review.

4. Crawl again, so the graph uses the ORCID iDs and ROR ids.

   ```sh
   venv/bin/python crawl_sib.py
   ```

5. Download photos and logos, and write the other RDF formats.

   ```sh
   venv/bin/python fetch_photos.py
   venv/bin/python fetch_logos.py
   venv/bin/python export_rdf.py
   ```

### Files kept by hand

These files hold decisions that a person made. The scripts read them, and never overwrite them.

| File | Columns | Use |
|---|---|---|
| `data/known_orcids.tsv` | `iri`, `orcid` | The ORCID iD of a person, by their sib.swiss directory page. These iDs are used without a search. |
| `data/orcid_overrides.tsv` | `slug`, `orcid` | Overrides the ORCID search for one person. An empty `orcid` means the person has none. |
| `data/ror_overrides.tsv` | `name`, `ror` | Overrides the ROR search for one institution. An empty `ror` means it has none. |

All TSV files are tab separated, with a header row.

## The website

Build the site into `_site/` and look at it locally:

```sh
npm run build
npm run serve
```

Then open http://localhost:3000.

The page text is in `INDEX.md`. Three kinds of fenced block have a special meaning there:

* A ` ```sparql ` block becomes a query box that runs in the browser.
* A ` ```sib-data ` block becomes the editable Turtle data box.
* A ` ```sib-graph ` block becomes the interactive network.

Any other fenced block is shown as plain code. To add a question, add a heading, a sentence and a ` ```sparql ` block to `INDEX.md`.

The page loads the photos and logos from its own copies. sib.swiss does not allow its photos to be shown on other sites, so they are kept in `data/photos/`. The logos come from Wikimedia Commons through Wikidata. `data/logos.tsv` lists the source of each one, so its licence can be checked.

## Publishing

A push to `main` builds the site and publishes it on GitHub Pages, with `.github/workflows/pages.yml`. In the repository settings, Pages must use "GitHub Actions" as its source.

## Presentation images

Two scripts draw the network as large PNG images for slides. The layout is computed once, so nodes stay in place while the layers are hidden one after another: papers, then courses, people, groups and institutions.

```sh
npm run build
node site/layout-presentation.mjs
venv/bin/python render_presentation.py
```

The images are written to `presentation/`, which is not kept in git.
