import { readFileSync, writeFileSync, mkdirSync, rmSync, cpSync, copyFileSync, existsSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import esbuild from 'esbuild';
import { Parser } from 'n3';
import MarkdownIt from 'markdown-it';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const OUT = path.join(ROOT, '_site');
// The page text and the example queries live here, in Markdown.
const PAGE = path.join(ROOT, 'INDEX.md');

// Same client bundles as the SPARQL training site, loaded in this order from
// templates/layout.html.
const CLIENT_BUNDLES = [
  ['src/comunica-entry.js', 'assets/js/comunica-bundle.js'],
  ['src/graph-entry.js', 'assets/js/graph-bundle.js'],
  ['src/prism-entry.js', 'assets/js/prism-bundle.js'],
];

const PHOTO_DIR = 'photos';
const PHOTO_SOURCE = path.join(ROOT, 'data', 'photos');
const SIB_LOGO = 'https://www.sib.swiss/themes/custom/sib/logo_emblem.svg';

const SCHEMA = 'https://schema.org/';
const RDF_TYPE = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type';
const ROR = 'https://ror.org/002n09z45';
const TYPE_NAMES = { Person: 'person', CourseInstance: 'course', ScholarlyArticle: 'paper' };
const LINK_KINDS = ['memberOf', 'parentOrganization', 'author', 'instructor'];

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

// The graph in each RDF format, served as its own files under data/.
const DATA_FILES = ['sib.ttl', 'sib.nt', 'sib.jsonld', 'sib.rdf'];

function copyDataFiles() {
  const dataOut = path.join(OUT, 'data');
  mkdirSync(dataOut, { recursive: true });
  for (const file of DATA_FILES) {
    copyFileSync(path.join(ROOT, 'data', file), path.join(dataOut, file));
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
  // An organization that a group sits inside, other than SIB itself, is an institution.
  for (const q of quads) {
    if (q.predicate.value !== SCHEMA + 'parentOrganization') continue;
    if (typeOf.get(q.subject.value) === 'group' && q.object.value !== ROR) {
      typeOf.set(q.object.value, 'institution');
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
    let kind = q.predicate.value.slice(SCHEMA.length);
    if (!LINK_KINDS.includes(kind)) continue;
    if (!nodes.has(q.subject.value) || !nodes.has(q.object.value)) continue;
    // A group's membership of SIB is kept apart from a person's membership of a group.
    if (kind === 'memberOf' && nodes.get(q.object.value).type === 'sib') kind = 'sibMember';
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

// A runnable query box. The runner finds its data by data-fixture-id, so every
// query box points at the single "sib" fixture.
function exampleBlock(query) {
  return (
    `<div class="sparql-example" data-fixture-id="sib">` +
    `<pre class="sparql-query" contenteditable="true" spellcheck="false"><code class="language-sparql">${escapeHtml(query.replace(/\n$/, ''))}</code></pre>` +
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

function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^\w\s-]/g, '')
    .trim()
    .replace(/\s+/g, '-');
}

// Renders INDEX.md. Three fenced blocks are special:
//   ```sparql    becomes a runnable query box
//   ```sib-data  becomes the editable Turtle data box
//   ```sib-graph becomes the people graph
// Every other fence is a plain code block. Headings get ids, so a section can be linked.
function renderContent(turtle, graph) {
  const md = new MarkdownIt({ html: true, linkify: true });
  const defaultFence = md.renderer.rules.fence;

  md.core.ruler.push('heading_ids', (state) => {
    const seen = new Map();
    state.tokens.forEach((token, idx) => {
      if (token.type !== 'heading_open') return;
      let slug = slugify(state.tokens[idx + 1].content) || 'section';
      const count = seen.get(slug) || 0;
      seen.set(slug, count + 1);
      if (count > 0) slug = `${slug}-${count}`;
      token.attrSet('id', slug);
    });
  });

  md.renderer.rules.fence = (tokens, idx, options, env, self) => {
    const token = tokens[idx];
    const lang = token.info.trim().split(/\s+/, 1)[0];
    if (lang === 'sparql') return exampleBlock(token.content);
    if (lang === 'sib-data') return fixtureBlock(turtle);
    if (lang === 'sib-graph') return graphBlock(graph);
    return defaultFence(tokens, idx, options, env, self);
  };

  return md.render(readFileSync(PAGE, 'utf8'));
}

function renderPage(turtle, graph) {
  const layout = readFileSync(path.join(__dirname, 'templates/layout.html'), 'utf8');
  const values = {
    TITLE: 'SIB people and groups',
    BASE: '',
    NAV: '',
    NOTEBOOK: '',
    TOC: '',
    CONTENT: renderContent(turtle, graph),
  };
  return layout.replace(/\{\{(\w+)\}\}/g, (_, key) => values[key]);
}

// sib.swiss sends Cross-Origin-Resource-Policy: same-site on its photos, so the
// page cannot show them directly from GitHub Pages. fetch_photos.py keeps a copy
// of each one in data/photos/, and the build copies those into the site.
function copyImages(graph) {
  const photoOut = path.join(OUT, PHOTO_DIR);
  mkdirSync(photoOut, { recursive: true });

  const jobs = graph.nodes.filter((n) => n.image).map((node) => ({ node, url: node.image }));
  const sib = graph.nodes.find((n) => n.type === 'sib');
  if (sib) jobs.push({ node: sib, url: SIB_LOGO });

  // Institution logos come from Wikidata (fetch_logos.py). The SIB node keeps its emblem above.
  const logos = {};
  const logosPath = path.join(ROOT, 'data', 'logos.tsv');
  if (existsSync(logosPath)) {
    const [header, ...rows] = readFileSync(logosPath, 'utf8').split('\n').filter(Boolean);
    const columns = header.split('\t');
    for (const row of rows) {
      const cells = row.split('\t');
      const entry = Object.fromEntries(columns.map((c, i) => [c, cells[i]]));
      logos[entry.ror] = entry;
    }
  }
  mkdirSync(path.join(OUT, 'logos'), { recursive: true });
  for (const node of graph.nodes) {
    const logo = logos[node.id];
    if (!logo || node.type === 'sib') continue;
    const file = path.basename(logo.file);
    copyFileSync(path.join(ROOT, 'data', 'logos', file), path.join(OUT, 'logos', file));
    node.image = `logos/${file}`;
  }

  let copied = 0;
  let missing = 0;
  for (const { node, url } of jobs) {
    const file = new URL(url).pathname.split('/').pop();
    const source = path.join(PHOTO_SOURCE, file);
    if (!existsSync(source)) {
      console.warn(`no photo file for ${node.id}: run fetch_photos.py`);
      delete node.image;
      missing++;
      continue;
    }
    copyFileSync(source, path.join(photoOut, file));
    node.image = `${PHOTO_DIR}/${file}`;
    copied++;
  }
  console.log(`images: ${copied} copied, ${missing} missing`);
}

function main() {
  const turtle = readFileSync(path.join(ROOT, 'data/sib.ttl'), 'utf8');
  const graph = buildGraphData(turtle);
  rmSync(OUT, { recursive: true, force: true });
  mkdirSync(OUT, { recursive: true });
  buildClientBundles();
  copyStaticAssets();
  copyDataFiles();
  copyImages(graph);
  writeFileSync(path.join(OUT, 'index.html'), renderPage(turtle, graph));
}

main();
