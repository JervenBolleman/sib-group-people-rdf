// Computes the layout of the full network for the presentation images.
//
// The layout is computed once, and render_presentation.py reuses those positions for
// every image, so nodes never move between images. SVG images (the SIB emblem and
// some institution logos) are rasterised here, since Pillow cannot read SVG.
//
// Run `npm run build` first, since the graph data is read from _site/.
// Output goes to $TMPDIR/sib-presentation/.

import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { forceSimulation, forceLink, forceManyBody, forceCenter, forceCollide } from 'd3-force';
import { Resvg } from '@resvg/resvg-js';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, '..');
const SITE = path.join(ROOT, '_site');
// Intermediate files go to the scratch directory, not the repository.
const CACHE = path.join(process.env.TMPDIR || os.tmpdir(), 'sib-presentation');

const W = 4000;
const H = 3000;
const BAND = 500; // strip above the network for the legend
const RADIUS = { sib: 60, institution: 44, group: 34, person: 22, course: 12, paper: 10 };

function loadGraph() {
  const html = readFileSync(path.join(SITE, 'index.html'), 'utf8');
  const json = html.match(/<script type="application\/json" id="people-graph-data">([\s\S]*?)<\/script>/)[1];
  return JSON.parse(json);
}

// One layout for the full network, run to rest.
function layout(graph) {
  const nodes = graph.nodes.map((n) => ({ ...n }));
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const links = graph.links
    .filter((l) => byId.has(l.source) && byId.has(l.target))
    .map((l) => ({ source: l.source, target: l.target, kind: l.kind }));

  const simulation = forceSimulation(nodes)
    .force('link', forceLink(links).id((d) => d.id).distance(170).strength(0.2))
    .force('charge', forceManyBody().strength(-700))
    .force('center', forceCenter(W / 2, H / 2))
    .force('collide', forceCollide().radius((d) => RADIUS[d.type] + 6).iterations(4))
    .stop();
  for (let i = 0; i < 500; i++) simulation.tick();

  // Scale the layout to fill the canvas. The 1st and 99th percentiles set the bounds,
  // so a few far-out nodes do not shrink the rest. Those nodes are clamped to the edge.
  const margin = 160;
  const quantile = (values, q) => {
    const sorted = [...values].sort((a, b) => a - b);
    return sorted[Math.floor(q * (sorted.length - 1))];
  };
  const xs = nodes.map((n) => n.x);
  const ys = nodes.map((n) => n.y);
  const lox = quantile(xs, 0.005);
  const hix = quantile(xs, 0.995);
  const loy = quantile(ys, 0.005);
  const hiy = quantile(ys, 0.995);
  const scale = Math.min((W - 2 * margin) / (hix - lox), (H - 2 * margin) / (hiy - loy));
  const offsetX = (W - (hix - lox) * scale) / 2;
  const offsetY = (H - (hiy - loy) * scale) / 2;
  const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
  for (const n of nodes) {
    n.x = clamp(offsetX + (n.x - lox) * scale, margin / 2, W - margin / 2);
    n.y = clamp(offsetY + (n.y - loy) * scale, margin / 2, H - margin / 2);
  }
  return { nodes, links };
}

// Rasterise every SVG image that the nodes use into a PNG in the scratch directory.
function rasteriseSvgImages(nodes) {
  const outDir = path.join(CACHE, 'svg');
  mkdirSync(outDir, { recursive: true });
  const paths = {};
  for (const n of nodes) {
    if (!n.image || !n.image.endsWith('.svg')) continue;
    const source = path.join(SITE, n.image);
    if (!existsSync(source)) continue;
    const out = path.join(outDir, path.basename(n.image).replace(/\.svg$/, '.png'));
    if (!paths[n.image]) {
      const png = new Resvg(readFileSync(source, 'utf8'), { fitTo: { mode: 'width', value: 800 } })
        .render()
        .asPng();
      writeFileSync(out, png);
      paths[n.image] = out;
    }
  }
  return paths;
}

function main() {
  const graph = loadGraph();
  const laidOut = layout(graph);
  const svgPngs = rasteriseSvgImages(laidOut.nodes);

  const nodes = laidOut.nodes.map((n) => ({
    id: n.id,
    type: n.type,
    label: n.label || '',
    x: n.x,
    y: n.y,
    // Raster images are read from _site. SVG images use the cached PNG instead.
    image: !n.image ? null : n.image.endsWith('.svg') ? svgPngs[n.image] || null : path.join(SITE, n.image),
  }));
  const links = laidOut.links.map((l) => ({
    source: l.source.id ?? l.source,
    target: l.target.id ?? l.target,
    kind: l.kind,
  }));

  mkdirSync(CACHE, { recursive: true });
  const out = path.join(CACHE, 'layout.json');
  writeFileSync(out, JSON.stringify({ width: W, height: H, band: BAND, nodes, links }));
  console.log(`wrote ${out}: ${nodes.length} nodes, ${links.length} links`);
}

main();
