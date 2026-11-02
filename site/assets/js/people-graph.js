(function () {
  'use strict';

  var G = window.SparqlGraph;
  var root = document.querySelector('.people-graph');
  var dataEl = document.getElementById('people-graph-data');
  if (!G || !root || !dataEl) return;

  var data = JSON.parse(dataEl.textContent);
  var SIB_LOGO = 'https://www.sib.swiss/themes/custom/sib/logo_emblem.svg';
  var TYPE_ORDER = ['sib', 'group', 'person', 'course', 'paper'];
  var TYPE_LABELS = { sib: 'SIB', group: 'Groups', person: 'People', course: 'Courses', paper: 'Papers' };
  var TYPE_NAMES = { sib: 'SIB', group: 'Group', person: 'Person', course: 'Course', paper: 'Paper' };
  var RADIUS = { sib: 26, group: 14, person: 16, course: 6, paper: 4 };
  var LIST_LIMIT = 20;

  var byId = new Map(data.nodes.map(function (n) { return [n.id, n]; }));
  var counts = {};
  data.nodes.forEach(function (n) {
    counts[n.type] = (counts[n.type] || 0) + 1;
  });

  var hiddenTypes = {};
  var focusId = null;
  var query = '';
  var simulation = null;
  var nodeSel = null;
  var linkSel = null;
  var visible = { nodes: [], links: [] };
  var resizeTimer = null;

  var filtersEl = root.querySelector('.people-graph-filters');
  var searchEl = root.querySelector('.people-graph-search');
  var canvasEl = root.querySelector('.people-graph-canvas');
  var detailsEl = root.querySelector('.people-graph-details');

  function endId(end) {
    return typeof end === 'object' ? end.id : end;
  }

  function nodeLabel(n) {
    return n.type === 'sib' ? 'SIB' : n.label || n.id;
  }

  function initials(name) {
    var parts = (name || '').split(/\s+/).filter(Boolean);
    if (parts.length === 0) return '';
    var last = parts.length > 1 ? parts[parts.length - 1].charAt(0) : '';
    return (parts[0].charAt(0) + last).toUpperCase();
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }

  function buildFilters() {
    TYPE_ORDER.forEach(function (type) {
      if (!counts[type]) return;
      var label = el('label', 'people-graph-filter ' + type);
      var box = el('input');
      box.type = 'checkbox';
      box.checked = true;
      box.addEventListener('change', function () {
        hiddenTypes[type] = !box.checked;
        draw();
      });
      label.appendChild(box);
      label.appendChild(el('span', '', TYPE_LABELS[type] + ' (' + counts[type] + ')'));
      filtersEl.appendChild(label);
    });
  }

  // Copies of the visible nodes and links, because d3 rewrites link ends and
  // adds positions to the objects it is given.
  function visibleData() {
    var nodes = data.nodes.filter(function (n) {
      return !hiddenTypes[n.type];
    });
    var ids = new Set(nodes.map(function (n) {
      return n.id;
    }));
    var links = data.links.filter(function (l) {
      return ids.has(l.source) && ids.has(l.target);
    });
    return {
      nodes: nodes.map(function (n) {
        return Object.assign({}, n);
      }),
      links: links.map(function (l) {
        return { source: l.source, target: l.target, kind: l.kind };
      }),
    };
  }

  function neighbourIds(id) {
    var ids = new Set([id]);
    visible.links.forEach(function (l) {
      var s = endId(l.source);
      var t = endId(l.target);
      if (s === id) ids.add(t);
      if (t === id) ids.add(s);
    });
    return ids;
  }

  // Dims nodes and links that are outside the hovered node's neighbourhood or
  // that do not match the search text.
  function updateLight() {
    if (!nodeSel) return;
    var around = focusId ? neighbourIds(focusId) : null;
    nodeSel.attr('opacity', function (d) {
      var focusOk = !around || around.has(d.id);
      var queryOk = !query || nodeLabel(d).toLowerCase().indexOf(query) !== -1;
      return focusOk && queryOk ? 1 : 0.12;
    });
    linkSel.attr('opacity', function (d) {
      if (focusId) {
        return endId(d.source) === focusId || endId(d.target) === focusId ? 0.9 : 0.04;
      }
      return 0.35;
    });
  }

  function draw() {
    if (simulation) simulation.stop();
    canvasEl.innerHTML = '';
    visible = visibleData();
    var width = canvasEl.clientWidth || 700;
    var height = canvasEl.clientHeight || 560;

    var svg = G.select(canvasEl)
      .append('svg')
      .attr('viewBox', [0, 0, width, height])
      .attr('preserveAspectRatio', 'xMidYMid meet')
      .on('click', hideDetails);
    var defs = svg.append('defs');
    var layer = svg.append('g');

    svg.call(
      G.zoom()
        .scaleExtent([0.2, 6])
        .on('zoom', function (event) {
          layer.attr('transform', event.transform);
        })
    );

    linkSel = layer
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(visible.links)
      .join('line')
      .attr('class', function (d) {
        return 'link ' + d.kind;
      });

    nodeSel = layer
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(visible.nodes)
      .join('g')
      .attr('class', function (d) {
        return 'node ' + d.type;
      })
      .on('click', function (event, d) {
        event.stopPropagation();
        showDetails(d);
      })
      .on('mouseenter', function (event, d) {
        focusId = d.id;
        updateLight();
      })
      .on('mouseleave', function () {
        focusId = null;
        updateLight();
      })
      .call(
        G.drag()
          .on('start', function (event, d) {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on('drag', function (event, d) {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on('end', function (event, d) {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // The base shape is always drawn. Photos (and the SIB logo) sit on top of
    // it, so a person without a photo still gets a coloured circle with their
    // initials.
    nodeSel.each(function (d, i) {
      var g = G.select(this);
      var r = RADIUS[d.type];
      if (d.type === 'group') {
        g.append('rect')
          .attr('class', 'base')
          .attr('x', -r)
          .attr('y', -r)
          .attr('width', 2 * r)
          .attr('height', 2 * r)
          .attr('rx', 4);
      } else {
        g.append('circle').attr('class', 'base').attr('r', r);
      }

      if (d.image || d.type === 'sib') {
        var clipId = 'people-graph-clip-' + i;
        defs.append('clipPath').attr('id', clipId).append('circle').attr('r', r);
        g.append('image')
          .attr('href', d.type === 'sib' ? SIB_LOGO : d.image)
          .attr('x', -r)
          .attr('y', -r)
          .attr('width', 2 * r)
          .attr('height', 2 * r)
          .attr('preserveAspectRatio', 'xMidYMid slice')
          .attr('clip-path', 'url(#' + clipId + ')');
      } else if (d.type === 'person') {
        g.append('text')
          .attr('class', 'initials')
          .attr('dy', '0.35em')
          .attr('text-anchor', 'middle')
          .text(initials(d.label));
      }

      if (d.type === 'sib' || d.type === 'group' || d.type === 'person') {
        g.append('text')
          .attr('class', 'label')
          .attr('y', r + 11)
          .attr('text-anchor', 'middle')
          .text(nodeLabel(d));
      }
      g.append('title').text(nodeLabel(d));
    });

    simulation = G.forceSimulation(visible.nodes)
      .force(
        'link',
        G.forceLink(visible.links)
          .id(function (d) {
            return d.id;
          })
          .distance(50)
          .strength(0.35)
      )
      .force('charge', G.forceManyBody().strength(-90))
      .force('center', G.forceCenter(width / 2, height / 2))
      .force(
        'collide',
        G.forceCollide().radius(function (d) {
          return RADIUS[d.type] + 4;
        })
      )
      .on('tick', function () {
        linkSel
          .attr('x1', function (d) {
            return d.source.x;
          })
          .attr('y1', function (d) {
            return d.source.y;
          })
          .attr('x2', function (d) {
            return d.target.x;
          })
          .attr('y2', function (d) {
            return d.target.y;
          });
        nodeSel.attr('transform', function (d) {
          return 'translate(' + d.x + ',' + d.y + ')';
        });
      });

    updateLight();
  }

  function hideDetails() {
    detailsEl.hidden = true;
    detailsEl.innerHTML = '';
  }

  // Everything linked to a node, grouped by the relation that links them.
  function relatedNodes(d) {
    var rel = { groups: [], members: [], parents: [], papers: [], courses: [], authors: [], instructors: [] };
    data.links.forEach(function (l) {
      var s = byId.get(l.source);
      var t = byId.get(l.target);
      if (l.kind === 'memberOf') {
        if (l.source === d.id) rel.groups.push(t);
        if (l.target === d.id) rel.members.push(s);
      } else if (l.kind === 'parentOrganization') {
        if (l.source === d.id) rel.parents.push(t);
      } else if (l.kind === 'author') {
        if (l.source === d.id) rel.authors.push(t);
        if (l.target === d.id) rel.papers.push(s);
      } else if (l.kind === 'instructor') {
        if (l.source === d.id) rel.instructors.push(t);
        if (l.target === d.id) rel.courses.push(s);
      }
    });
    return rel;
  }

  function addSection(title, nodes) {
    if (nodes.length === 0) return;
    var wrap = el('div', 'people-graph-section');
    wrap.appendChild(el('h4', '', title + ' (' + nodes.length + ')'));
    var list = el('ul');
    nodes.slice(0, LIST_LIMIT).forEach(function (n) {
      var item = el('li');
      if (n.url) {
        var link = el('a', '', nodeLabel(n));
        link.href = n.url;
        link.target = '_blank';
        link.rel = 'noopener';
        item.appendChild(link);
      } else {
        item.textContent = nodeLabel(n);
      }
      list.appendChild(item);
    });
    if (nodes.length > LIST_LIMIT) {
      list.appendChild(el('li', '', '... and ' + (nodes.length - LIST_LIMIT) + ' more'));
    }
    wrap.appendChild(list);
    detailsEl.appendChild(wrap);
  }

  function showDetails(d) {
    detailsEl.innerHTML = '';
    detailsEl.hidden = false;

    var close = el('button', 'sparql-btn sparql-btn-secondary people-graph-close', 'Close');
    close.type = 'button';
    close.addEventListener('click', hideDetails);
    detailsEl.appendChild(close);

    if (d.image) {
      var photo = el('img', 'people-graph-photo');
      photo.src = d.image;
      photo.alt = 'Photo of ' + nodeLabel(d);
      photo.loading = 'lazy';
      detailsEl.appendChild(photo);
    }

    detailsEl.appendChild(el('h3', '', nodeLabel(d)));
    detailsEl.appendChild(el('p', 'people-graph-type', TYPE_NAMES[d.type]));
    if (d.jobTitle) detailsEl.appendChild(el('p', 'people-graph-job', d.jobTitle));

    if (d.url) {
      var page = el('a', '', d.type === 'paper' ? 'Open the paper' : 'Open on sib.swiss');
      page.href = d.url;
      page.target = '_blank';
      page.rel = 'noopener';
      detailsEl.appendChild(page);
    }
    if (d.id.indexOf('https://orcid.org/') === 0) {
      var orcid = el('a', '', 'ORCID iD ' + d.id.slice('https://orcid.org/'.length));
      orcid.href = d.id;
      orcid.target = '_blank';
      orcid.rel = 'noopener';
      detailsEl.appendChild(orcid);
    }

    var rel = relatedNodes(d);
    addSection('Groups', rel.groups);
    addSection('Part of', rel.parents);
    addSection('Members', rel.members);
    addSection('Papers', rel.papers);
    addSection('Courses taught', rel.courses);
    addSection('Authors', rel.authors);
    addSection('Instructors', rel.instructors);
  }

  searchEl.addEventListener('input', function () {
    query = searchEl.value.trim().toLowerCase();
    updateLight();
  });

  window.addEventListener('resize', function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(draw, 200);
  });

  buildFilters();
  draw();
})();
