import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import esbuild from 'esbuild';
import { Parser } from 'n3';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, '_site');

// Same client bundles as the SPARQL training site, loaded in this order from
// templates/layout.html.
const CLIENT_BUNDLES = [
  ['src/comunica-entry.js', 'assets/js/comunica-bundle.js'],
  ['src/graph-entry.js', 'assets/js/graph-bundle.js'],
  ['src/prism-entry.js', 'assets/js/prism-bundle.js'],
];

const SCHEMA = 'https://schema.org/';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const ROR = 'https://ror.org/002n09z45';
const TYPE_NAMES = { Person: 'person', Course: 'course', ScholarlyArticle: 'paper' };
const LINK_KINDS = ['memberOf', 'parentOrganization', 'author', 'instructor'];

const PREFIXES = 'PREFIX schema: <https://schema.org/>\n';

// Each example is one query box. The runner finds it by its data-fixture-id,
// so every example here points at the single "sib" fixture below.
const EXAMPLES = [
  {
    id: 'courses-per-person',
    title: 'Who gave the most courses?',
    text: 'Counts the distinct courses each person was an instructor for.',
    query: `${PREFIXES}
SELECT ?person ?name (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:Course ;
          schema:instructor ?person .
  ?person schema:name ?name .
}
GROUP BY ?person ?name
ORDER BY DESC(?courses)
`,
  },
  {
    id: 'groups-by-courses',
    title: 'Which groups train the most?',
    text: 'Counts the courses that had at least one instructor from each group.',
    query: `${PREFIXES}
SELECT ?groupName (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:Course ;
          schema:instructor ?person .
  ?person schema:memberOf ?group .
  ?group schema:name ?groupName .
}
GROUP BY ?groupName
ORDER BY DESC(?courses)
`,
  },
  {
    id: 'groups-co-training',
    title: 'Which groups co-train?',
    text: 'Pairs of different groups whose members taught the same course together.',
    query: `${PREFIXES}
SELECT ?groupA ?groupB (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:Course ;
          schema:instructor ?p1, ?p2 .
  ?p1 schema:memberOf ?a .
  ?p2 schema:memberOf ?b .
  ?a schema:name ?groupA .
  ?b schema:name ?groupB .
  FILTER(?p1 != ?p2 && STR(?groupA) < STR(?groupB))
}
GROUP BY ?groupA ?groupB
ORDER BY DESC(?courses)
`,
  },
  {
    id: 'groups-co-publishing',
    title: 'Which groups co-publish?',
    text: 'Pairs of different groups, with the number of papers that had an author from each group.',
    query: `${PREFIXES}
SELECT ?groupA ?groupB (COUNT(DISTINCT ?paper) AS ?papers) WHERE {
  ?paper a schema:ScholarlyArticle ;
         schema:author ?p1, ?p2 .
  ?p1 schema:memberOf ?a .
  ?p2 schema:memberOf ?b .
  ?a schema:name ?groupA .
  ?b schema:name ?groupB .
  FILTER(?p1 != ?p2 && STR(?groupA) < STR(?groupB))
}
GROUP BY ?groupA ?groupB
ORDER BY DESC(?papers)
LIMIT 50
`,
  },
  {
    id: 'people-co-teaching',
    title: 'Who taught together?',
    text: 'Pairs of people who were instructors on the same course.',
    query: `${PREFIXES}
SELECT ?nameA ?nameB (COUNT(DISTINCT ?course) AS ?courses) WHERE {
  ?course a schema:Course ;
          schema:instructor ?a, ?b .
  ?a schema:name ?nameA .
  ?b schema:name ?nameB .
  FILTER(STR(?nameA) < STR(?nameB))
}
GROUP BY ?nameA ?nameB
ORDER BY DESC(?courses)
LIMIT 50
`,
  },
  {
    id: 'papers-per-person',
    title: 'Who wrote the most papers?',
    text: 'Counts the distinct papers each person is an author of.',
    query: `${PREFIXES}
SELECT ?person ?name (COUNT(DISTINCT ?paper) AS ?papers) WHERE {
  ?paper a schema:ScholarlyArticle ;
         schema:author ?person .
  ?person schema:name ?name .
}
GROUP BY ?person ?name
ORDER BY DESC(?papers)
LIMIT 50
`,
  },
  {
    id: 'orcid-people',
    title: 'Who has an ORCID iD?',
    text: 'People whose node is their ORCID iD. Everyone else is still identified by their sib.swiss directory page.',
    query: `${PREFIXES}
SELECT ?person ?name WHERE {
  ?person a schema:Person ;
          schema:name ?name .
  FILTER(STRSTARTS(STR(?person), "https://orcid.org/"))
}
ORDER BY ?name
`,
  },
];

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function buildClientBundles() {
  for (const [entry, outfile] of CLIENT_BUNDLES) {
    esbuild.buildSync({
      entryPoints: [path.join(__dirname, entry)],
      bundle: true,
      minify: true,
      format: 'iife',
      platform: 'browser',
      target: 'es2020',
      outfile: path.join(OUT, outfile),
      logLevel: 'info',
    });
  }
}

function copyStaticAssets() {
  mkdirSync(path.join(OUT, 'assets/css'), { recursive: true });
  mkdirSync(path.join(OUT, 'assets/js'), { recursive: true });
  cpSync(path.join(__dirname, 'assets/css/style.css'), path.join(OUT, 'assets/css/style.css'));
  cpSync(path.join(__dirname, 'assets/js/sparql-runner.js'), path.join(OUT, 'assets/js/sparql-runner.js'));
  cpSync(path.join(__dirname, 'assets/js/people-graph.js'), path.join(OUT, 'assets/js/people-graph.js'));
  cpSync(path.join(__dirname, 'assets/css/people-graph.css'), path.join(OUT, 'assets/css/people-graph.css'));
}

// Turns the Turtle file into the nodes and links the people graph draws. Only
// typed resources and the four relations between them are kept, so literal
// values such as names stay on the nodes and do not become nodes themselves.
function buildGraphData(turtle) {
  const quads = new Parser().parse(turtle);
  const typeOf = new Map();
  for (const q of quads) {
    if (q.predicate.value !== RDF_TYPE || !q.object.value.startsWith(SCHEMA)) continue;
    const kind = q.object.value.slice(SCHEMA.length);
    if (kind === 'Organization') {
      typeOf.set(q.subject.value, q.subject.value === ROR ? 'sib' : 'group');
    } else if (TYPE_NAMES[kind]) {
      typeOf.set(q.subject.value, TYPE_NAMES[kind]);
    }
  }

  const nodes = new Map();
  for (const id of typeOf.keys()) nodes.set(id, { id, type: typeOf.get(id) });
  for (const q of quads) {
    const node = nodes.get(q.subject.value);
    if (!node || !q.predicate.value.startsWith(SCHEMA)) continue;
    const key = q.predicate.value.slice(SCHEMA.length);
    if (key === 'name') node.label = q.object.value;
    if (key === 'image') node.image = q.object.value;
    if (key === 'url') node.url = q.object.value;
    if (key === 'jobTitle') node.jobTitle = q.object.value;
  }

  const links = [];
  for (const q of quads) {
    if (!q.predicate.value.startsWith(SCHEMA)) continue;
    const kind = q.predicate.value.slice(SCHEMA.length);
    if (!LINK_KINDS.includes(kind)) continue;
    if (!nodes.has(q.subject.value) || !nodes.has(q.object.value)) continue;
    links.push({ source: q.subject.value, target: q.object.value, kind });
  }

  return { nodes: [...nodes.values()], links };
}

function fixtureBlock(turtle) {
  return (
    `<details class="sparql-fixture" data-fixture-id="sib">` +
    `<summary>Graph data (Turtle) <span class="sparql-editable-hint">- edit it, then re-run any query below</span></summary>` +
    `<pre class="sparql-fixture-data" contenteditable="true" spellcheck="false"><code class="language-turtle">${escapeHtml(turtle)}</code></pre>` +
    `<div class="sparql-fixture-toolbar">` +
    `<button type="button" class="sparql-btn sparql-btn-secondary sparql-reset" data-reset-target="fixture">&#8630; Reset data</button>` +
    `</div>` +
    `</details>`
  );
}

function exampleBlock(example) {
  return (
    `<h3 id="${example.id}">${escapeHtml(example.title)}</h3>\n` +
    `<p>${escapeHtml(example.text)}</p>\n` +
    `<div class="sparql-example" data-fixture-id="sib">` +
    `<pre class="sparql-query" contenteditable="true" spellcheck="false"><code class="language-sparql">${escapeHtml(example.query)}</code></pre>` +
    `<div class="sparql-example-toolbar">` +
    `<button type="button" class="sparql-btn sparql-run">&#9654; Run query</button>` +
    `<button type="button" class="sparql-btn sparql-btn-secondary sparql-reset" data-reset-target="query">&#8630; Reset query</button>` +
    `</div>` +
    `<div class="sparql-results"></div>` +
    `</div>`
  );
}

function graphBlock(graph) {
  const json = JSON.stringify(graph).replace(/</g, '\\u003c');
  return (
    '<h2>Graph</h2>\n' +
    '<p>Every person, group, paper and course in the data. People are shown with their sib.swiss photo. ' +
      'Hover a node to see its neighbours, click it for details.</p>\n' +
    '<div class="people-graph">' +
    '<div class="people-graph-controls">' +
    '<div class="people-graph-filters"></div>' +
    '<input type="search" class="people-graph-search" placeholder="Find a name or title" aria-label="Find a name or title">' +
    '</div>' +
    '<div class="people-graph-stage">' +
    '<div class="people-graph-canvas"></div>' +
    '<aside class="people-graph-details" hidden></aside>' +
    '</div>' +
    '</div>\n' +
    `<script type="application/json" id="people-graph-data">${json}</script>`
  );
}

function renderContent(turtle) {
  return [
    '<h1>SIB people and groups</h1>',
    '<p>This page holds a graph of SIB groups, the people in them, their papers and the courses they gave. ' +
      'It was built from public pages on sib.swiss and uses schema.org terms. The SIB itself is the ' +
      'organization <a href="https://ror.org/002n09z45">ROR 002n09z45</a>.</p>',
    '<p>A person with an ORCID iD is named by that iD. Everyone else is named by their sib.swiss directory page. ' +
      'Papers and courses are linked to people by name, so a few links may be wrong.</p>',
    '<h2>Data</h2>',
    fixtureBlock(turtle),
    graphBlock(buildGraphData(turtle)),
    '<h2>Questions</h2>',
    ...EXAMPLES.map(exampleBlock),
  ].join('\n');
}

function renderPage(turtle) {
  const layout = readFileSync(path.join(__dirname, 'templates/layout.html'), 'utf8');
  const values = {
    TITLE: 'SIB people and groups',
    BASE: '',
    NAV: '',
    NOTEBOOK: '',
    TOC: '',
    CONTENT: renderContent(turtle),
  };
  return layout.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key]);
}

function main() {
  const turtle = readFileSync(path.join(ROOT, 'data/sib.ttl'), 'utf8');
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  buildClientBundles();
  copyStaticAssets();
  writeFileSync(path.join(OUT, 'index.html'), renderPage(turtle));
}

main();
