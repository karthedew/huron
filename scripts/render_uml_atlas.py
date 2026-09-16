#!/usr/bin/env python
# ruff: noqa: E501  (embedded CSS/JS and hero copy are long by nature)
"""Render the `design/<name>-uml.md` UML atlases into self-contained HTML pages.

Each atlas is a Markdown file with Mermaid ``classDiagram`` fences. This script
renders every fence to SVG with Mermaid CLI 11 and assembles the browser edition:
sticky section navigation, class search, per-diagram zoom/expand/download, and
embedded SVGs, so the page needs no runtime library or network access.

Usage::

    uv run python scripts/render_uml_atlas.py            # every atlas in ATLASES
    uv run python scripts/render_uml_atlas.py auth rbac  # a subset

Requirements: ``markdown-it-py`` (a project dependency) and Mermaid CLI. Pass
``--mmdc`` to point at an installed ``mmdc`` binary; otherwise ``npx`` fetches
``@mermaid-js/mermaid-cli@11.17.0``. A Chrome or Chromium binary is needed; set
``--chrome`` (default ``/usr/bin/google-chrome``) or leave Puppeteer's own download.

Hero text, badges and top links per atlas live in ``ATLASES`` below; the section
navigation, snapshot line and diagram captions come from the Markdown itself.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

from markdown_it import MarkdownIt

REPO = Path(__file__).resolve().parents[1]
DESIGN = REPO / "design"
MERMAID_VERSION = "11.17.0"

# Rendering theme. The top-level fontFamily must equal the theme font: Mermaid measures
# member labels with the former and renders them with the latter, and a mismatch makes
# long members wrap onto a second line.
MERMAID_CONFIG = {
    "theme": "base",
    "themeVariables": {
        "fontFamily": "system-ui,sans-serif",
        "fontSize": "16px",
        "primaryColor": "#ecf6f4",
        "primaryBorderColor": "#4e8985",
        "primaryTextColor": "#1a343b",
        "lineColor": "#4a646f",
        "textColor": "#1a343b",
        "mainBkg": "#ecf6f4",
        "nodeBorder": "#4e8985",
        "classText": "#1a343b",
        "edgeLabelBackground": "#ecf6f4",
    },
    "class": {"useMaxWidth": True, "hideEmptyMembersBox": True},
    "maxTextSize": 200000,
    "markdownAutoWrap": False,
    "fontFamily": "system-ui,sans-serif",
    "fontSize": 16,
}

ATLASES: dict[str, dict[str, str]] = {
    "catalog": {
        "area": "catalog",
        "h1": "Catalog and its Collaborators",
        "lead": "Stable hierarchy identities meet Raw revisions, Security authority and Foundation values: domain-owned workflows, rules and the adapters that persist them.",
        "description": "A source-linked UML atlas of Huron's Catalog and related Raw, Security and Foundation values, workflows and adapter interfaces. Offline, searchable, zoomable.",
        "badges": "Explicit domain ownership|Rules and workflows colocated|{diagrams} UML views|Offline-ready",
        "toplinks": "catalog-search.html=Catalog design;architecture.html=Architecture",
        "nav_title": "Explore the catalog",
        "hints": "Dataset, Store, or Ingest",
        "placeholder": "e.g. Dataset, Ingest…",
    },
    "metastore": {
        "area": "metastore",
        "h1": "Inside the Metastore",
        "lead": "Adapters, ports, and the constraints that turn catalog, governance, and credential records into durable PostgreSQL rows, with the in-memory references they are measured against.",
        "description": "A source-linked UML atlas of Huron's core.metastore adapters: hierarchy, Raw ledger, Security facts, governance, credentials and maintenance, and their consumer-owned ports. Offline, searchable, zoomable.",
        "badges": "29 adapter declarations|PostgreSQL and memory adapters|{diagrams} UML views|Offline-ready",
        "toplinks": "architecture.html=Architecture;catalog-uml.html=Catalog atlas",
        "nav_title": "Explore the metastore",
        "hints": "Postgres, Hierarchy, or Rbac",
        "placeholder": "e.g. PostgresHierarchyStore, rows…",
    },
    "rawstore": {
        "area": "rawstore",
        "h1": "Inside the Rawstore",
        "lead": "Descriptors, candidates, and one exclusive rename: the classes and primitives that turn uploaded bytes into durable, sealed, verifiable Raw revisions on a single filesystem.",
        "description": "A source-linked UML atlas of Huron's core.rawstore adapter: POSIX publication, descriptor durability, Catalog generation writes and Integrity evidence storage. Offline, searchable, zoomable.",
        "badges": "4 rawstore classes|Descriptor-based durability|{diagrams} UML views|Offline-ready",
        "toplinks": "layer-raw.html=Raw layer design;catalog-uml.html=Catalog atlas",
        "nav_title": "Explore the rawstore",
        "hints": "PosixRawStore, Commit, or Staging",
        "placeholder": "e.g. PosixRawStore, commit…",
    },
    "auth": {
        "area": "authentication",
        "h1": "Security: Authentication",
        "lead": "Four credential paths, one frozen principal: Security owns resolution, login, persisted sessions, identity administration and self-access; the API owns browser transport.",
        "description": "A source-linked authentication view of core.security: credential mechanisms, complete authentication workflows, identity administration, Metastore adapters and API wiring. Offline, searchable, zoomable.",
        "badges": "Security owner|4 credential paths|{diagrams} UML views|Offline-ready",
        "toplinks": "auth.html=Authentication design;rbac-uml.html=RBAC atlas",
        "nav_title": "Explore authentication",
        "hints": "Principal, Session, or ApiKey",
        "placeholder": "e.g. Principal, OidcClient…",
    },
    "rbac": {
        "area": "RBAC",
        "h1": "Security: Authorization",
        "lead": "Principals, bindings, scopes, and the deny-by-default decision that stands between every authenticated actor and Huron's catalog.",
        "description": "A source-linked authorization view of core.security: roles, decisions, discovery, narrow catalog facts, AccessPolicy, governance workflows and persistence. Offline, searchable, zoomable.",
        "badges": "Security owner|Deny-by-default decisions|{diagrams} UML views|Offline-ready",
        "toplinks": "rbac.html=RBAC design;auth-uml.html=Authentication atlas",
        "nav_title": "Explore RBAC",
        "hints": "Scope, Binding, or AccessPolicy",
        "placeholder": "e.g. RoleBindingAuthorizer, Scope…",
    },
}

CSS = r"""
:root { color-scheme: light; --bg:#f7f8f7; --panel:#fff; --ink:#20343c; --muted:#5a6d74; --line:#d9e3e2; --accent:#086b64; --tint:#e9f4f1; --code:#eff3f2; --canvas:#fcfefd; --shadow:0 10px 35px #1a39400b; }
html[data-theme="dark"] { color-scheme:dark; --bg:#111a20; --panel:#18252d; --ink:#e2ebee; --muted:#a8bec6; --line:#354852; --accent:#80d9c8; --tint:#1f3d3d; --code:#22343e; --canvas:#17232b; --shadow:none; }
* { box-sizing:border-box; }
html { scroll-padding-top:1.5rem; }
body { margin:0; font:16px/1.65 system-ui,sans-serif; background:var(--bg); color:var(--ink); }
a { color:var(--accent); text-underline-offset:.2em; }
button, input { font:inherit; }
button { cursor:pointer; border:1px solid var(--line); border-radius:6px; color:var(--ink); background:var(--panel); padding:.32rem .7rem; min-height:36px; }
button:hover { border-color:var(--accent); background:var(--tint); }
button:disabled { cursor:default; opacity:.45; }
:focus-visible { outline:3px solid var(--accent); outline-offset:3px; }
.skip { position:absolute; top:-100px; left:1rem; padding:.8rem; z-index:10; background:var(--panel); }
.skip:focus { top:.7rem; }
.topbar { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:1rem; padding:.85rem 1.6rem; border-bottom:1px solid var(--line); background:var(--panel); }
.brand { font-weight:800; text-decoration:none; letter-spacing:.12em; }
.toplinks { display:flex; align-items:center; flex-wrap:wrap; gap:1.2rem; font-size:.85rem; }
.layout { display:grid; grid-template-columns:245px minmax(0,1fr); max-width:1680px; margin:auto; }
aside { padding:2rem 1.1rem 2rem 1.4rem; border-right:1px solid var(--line); }
.sidebar { position:sticky; top:1rem; max-height:calc(100vh - 2rem); overflow:auto; padding:.25rem; }
.sidebar h2 { font-size:.73rem; letter-spacing:.12em; text-transform:uppercase; margin:0 0 .9rem; border:0; padding:0; color:var(--muted); }
.sidebar ol { list-style:none; margin:0 0 1.8rem; padding:0; }
.sidebar li { margin:0; }
.sidebar nav a { display:block; border-radius:5px; font-size:.82rem; line-height:1.4; text-decoration:none; color:var(--muted); padding:.45rem .6rem; border-left:2px solid transparent; }
.sidebar nav a:hover, .sidebar nav a[aria-current] { color:var(--accent); background:var(--tint); border-color:var(--accent); }
.search-label { display:block; font-size:.8rem; font-weight:700; margin-bottom:.4rem; }
#class-search { width:100%; min-width:0; border:1px solid var(--line); border-radius:6px; color:var(--ink); background:var(--panel); padding:.5rem; }
#search-status { font-size:.75rem; color:var(--muted); margin:.5rem 0; }
#search-results { list-style:none; padding:0; margin:0; max-height:250px; overflow:auto; }
#search-results button { display:block; width:100%; text-align:left; font-size:.77rem; margin-bottom:.35rem; overflow-wrap:anywhere; }
#search-results small { display:block; color:var(--muted); font-size:.7rem; }
main { min-width:0; padding:2.2rem clamp(1rem,3vw,3rem) 5rem; }
.hero { padding:.5rem 0 1rem; }
.eyebrow { color:var(--accent); text-transform:uppercase; font-size:.75rem; letter-spacing:.13em; font-weight:750; }
h1 { font-size:clamp(2.1rem,4vw,3.5rem); line-height:1.12; letter-spacing:-.045em; margin:.6rem 0 1rem; }
.lead { font-size:1.12rem; line-height:1.65; color:var(--muted); max-width:73ch; }
.badges { display:flex; flex-wrap:wrap; gap:.5rem; margin:1.3rem 0 .2rem; }
.badges span { font-size:.73rem; color:var(--accent); background:var(--tint); padding:.25rem .65rem; border-radius:20px; }
main h2 { margin:3.4rem 0 1rem; padding-top:1rem; border-top:1px solid var(--line); font-size:1.5rem; line-height:1.35; letter-spacing:-.02em; scroll-margin-top:1rem; }
main p, main > ul, main > ol { max-width:95ch; }
main li { margin:.5rem 0; }
code { font: .87em ui-monospace,monospace; padding:.12em .25em; border-radius:3px; background:var(--code); overflow-wrap:anywhere; }
pre { overflow:auto; padding:1rem; background:var(--code); border-radius:6px; font-size:.82rem; line-height:1.6; }
pre code { padding:0; overflow-wrap:normal; }
.table-wrap { overflow:auto; margin:1.5rem 0; border:1px solid var(--line); border-radius:8px; }
table { border-collapse:collapse; width:100%; min-width:660px; font-size:.85rem; background:var(--panel); }
td, th { text-align:left; padding:.8rem; vertical-align:top; border-bottom:1px solid var(--line); }
th { background:var(--tint); font-size:.77rem; }
tr:last-child td { border-bottom:0; }
.diagram { margin:1.5rem 0 2rem; border:1px solid var(--line); border-radius:10px; background:var(--panel); overflow:hidden; box-shadow:var(--shadow); scroll-margin-top:1rem; }
figcaption { display:flex; align-items:center; gap:.75rem; padding:.9rem 1rem; font-size:.85rem; border-bottom:1px solid var(--line); }
figcaption > a { margin-left:auto; }
.diagram-number { font:700 .72rem ui-monospace,monospace; color:var(--accent); background:var(--tint); padding:.25rem .4rem; border-radius:4px; }
.diagram-toolbar { display:flex; align-items:center; gap:.4rem; flex-wrap:wrap; padding:.55rem .8rem; border-bottom:1px solid var(--line); font-size:.75rem; }
.diagram-toolbar output { min-width:3.3rem; text-align:center; color:var(--muted); font: .75rem ui-monospace,monospace; }
.viewport { height:clamp(340px,65vh,760px); overflow:auto; overscroll-behavior:contain; background:var(--canvas); padding:16px; }
.viewport > svg { display:block; max-width:none !important; margin:auto; }
html[data-theme="dark"] .viewport > svg { filter:invert(.9) hue-rotate(170deg); }
.viewport .node.search-match > rect, .viewport .node.search-match > polygon { stroke:#b35d00 !important; stroke-width:4px !important; fill:#fff1be !important; }
.diagram-source { border-top:1px solid var(--line); font-size:.8rem; }
.diagram-source summary { padding:.6rem 1rem; cursor:pointer; color:var(--muted); }
.diagram-source pre { margin:0; border-radius:0; max-height:360px; }
.help { background:var(--tint); border-left:3px solid var(--accent); padding:.85rem 1rem; border-radius:0 6px 6px 0; font-size:.85rem; }
dialog { width:calc(100vw - 32px); max-width:none; height:calc(100vh - 32px); max-height:none; padding:0; border:1px solid var(--line); border-radius:12px; color:var(--ink); background:var(--panel); }
dialog::backdrop { background:#061119bd; }
.dialog-header { padding:.6rem 1rem; display:flex; justify-content:space-between; align-items:center; gap:1rem; border-bottom:1px solid var(--line); font-size:.85rem; }
dialog .diagram { margin:0; border:0; border-radius:0; box-shadow:none; }
dialog .viewport { height:calc(100dvh - 255px); }
footer { color:var(--muted); font-size:.78rem; margin-top:3rem; padding-top:1rem; border-top:1px solid var(--line); }
@media(max-width:1000px) { .layout { grid-template-columns:205px minmax(0,1fr); } aside { padding-left:.7rem; } }
@media(max-width:760px) { .layout { display:block; } aside { border-right:0; border-bottom:1px solid var(--line); padding:1rem; } .sidebar { position:static; max-height:none; overflow:visible; } .sidebar nav ol { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); margin-bottom:1rem; } .topbar { padding:.8rem 1rem; } .toplinks { gap:.7rem; } main { padding:1.25rem 1rem 3rem; } h1 { font-size:2.5rem; } .viewport { height:430px; } .diagram-toolbar { gap:.3rem; } dialog { width:calc(100vw - 12px); height:calc(100vh - 12px); } }
@media print { .topbar, aside, .diagram-toolbar, .diagram-source, .skip, .help, dialog { display:none; } .layout { display:block; } main { padding:0; } .diagram { break-inside:avoid; box-shadow:none; } .viewport { height:auto; overflow:visible; padding:0; } .viewport > svg { width:100% !important; height:auto !important; filter:none !important; } :root, html[data-theme="dark"] { --bg:#fff; --panel:#fff; --ink:#111; --muted:#444; --line:#ccc; --accent:#075a52; --canvas:#fff; --tint:#f1f5f4; --code:#f4f4f4; } }
""".strip("\n")

SCRIPT = r"""
const themeButton = document.getElementById('theme-toggle');
let dark = matchMedia('(prefers-color-scheme: dark)').matches;
function setTheme() {
  document.documentElement.dataset.theme = dark ? 'dark' : 'light';
  themeButton.textContent = dark ? 'Light mode' : 'Dark mode';
}
setTheme();
themeButton.addEventListener('click', () => { dark = !dark; setTheme(); });
const cards = [...document.querySelectorAll('.diagram')];
const states = new Map();
const nodes = [];
const dialog = document.getElementById('diagram-dialog');
let expanded = null;
let placeholder = null;
let opener = null;
function setZoom(card, scale, fitting = false) {
  const state = states.get(card);
  const view = card.querySelector('.viewport');
  state.fitting = fitting;
  state.scale = Math.max(.08, Math.min(3, scale));
  state.svg.style.width = state.width * state.scale + 'px';
  state.svg.style.height = state.height * state.scale + 'px';
  card.querySelector('output').value = Math.round(state.scale * 100) + '%';
  card.querySelector('[data-action="out"]').disabled = state.scale <= .08;
  card.querySelector('[data-action="in"]').disabled = state.scale >= 3;
  if (fitting) { view.scrollTop = 0; view.scrollLeft = 0; }
}
function fit(card) {
  const view = card.querySelector('.viewport');
  setZoom(card, (view.clientWidth - 32) / states.get(card).width, true);
}
function closeExpanded() {
  if (!expanded) return;
  const card = expanded;
  placeholder.replaceWith(card);
  expanded = null;
  placeholder = null;
  card.querySelector('[data-action="expand"]').disabled = false;
  if (states.get(card).fitting) fit(card);
  opener.focus({ preventScroll: true });
}
dialog.addEventListener('close', closeExpanded);
document.getElementById('close-diagram').addEventListener('click', () => dialog.close());
for (const card of cards) {
  const svg = card.querySelector('svg');
  const box = svg.viewBox.baseVal;
  states.set(card, { svg, width:box.width, height:box.height, scale:1, fitting:true });
  card.querySelector('.diagram-toolbar').addEventListener('click', (event) => {
    const button = event.target.closest('button');
    if (!button) return;
    const action = button.dataset.action;
    const state = states.get(card);
    if (action === 'in') setZoom(card, state.scale * 1.3);
    if (action === 'out') setZoom(card, state.scale / 1.3);
    if (action === 'fit') fit(card);
    if (action === 'actual') setZoom(card, 1);
    if (action === 'expand') {
      expanded = card;
      opener = button;
      placeholder = document.createComment('expanded diagram');
      card.replaceWith(placeholder);
      document.getElementById('dialog-content').append(card);
      document.getElementById('dialog-title').textContent = card.dataset.title;
      button.disabled = true;
      dialog.showModal();
      if (state.fitting) fit(card);
      document.getElementById('close-diagram').focus();
    }
    if (action === 'download') {
      const copy = svg.cloneNode(true);
      copy.style.width = state.width + 'px';
      copy.style.height = state.height + 'px';
      const blob = new Blob([new XMLSerializer().serializeToString(copy)], {type:'image/svg+xml'});
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = '__SLUG__-' + card.id + '.svg';
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
  });
  for (const node of svg.querySelectorAll('g.node')) {
    const match = node.id.match(/(?:^|-)classId-(.+)-[0-9]+$/);
    if (match) nodes.push({ name:match[1], node, card });
  }
  setZoom(card, Math.max(.85, Math.min(1, (card.querySelector('.viewport').clientWidth - 32) / states.get(card).width)));
}
const observer = new ResizeObserver((entries) => {
  for (const entry of entries) {
    const card = entry.target.closest('.diagram');
    if (states.get(card).fitting) fit(card);
  }
});
cards.forEach(card => observer.observe(card.querySelector('.viewport')));
const input = document.getElementById('class-search');
const status = document.getElementById('search-status');
const results = document.getElementById('search-results');
input.addEventListener('input', () => {
  const query = input.value.trim().toLowerCase();
  results.replaceChildren();
  nodes.forEach(({node}) => node.classList.remove('search-match'));
  if (!query) { status.textContent = 'Find a class across all __COUNT__ diagrams.'; return; }
  const matches = nodes.filter(({name}) => name.toLowerCase().includes(query));
  matches.forEach(({node}) => node.classList.add('search-match'));
  status.textContent = matches.length ? matches.length + ' matches' + (matches.length > 40 ? ' · first 40 listed' : '') : 'No matching class. Try __HINTS__.';
  for (const item of matches.slice(0,40)) {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.append(document.createTextNode(item.name));
    const label = document.createElement('small');
    label.textContent = item.card.dataset.title;
    button.append(label);
    button.addEventListener('click', () => {
      setZoom(item.card, 1);
      history.replaceState(null, '', '#' + item.card.id);
      item.node.scrollIntoView({block:'center', inline:'center'});
      item.card.querySelector('.viewport').focus({preventScroll:true});
    });
    li.append(button);
    results.append(li);
  }
});
const sectionLinks = [...document.querySelectorAll('.sidebar nav a')];
const sectionObserver = new IntersectionObserver((entries) => {
  const entry = entries.find(item => item.isIntersecting);
  if (!entry) return;
  sectionLinks.forEach(link => {
    if (link.hash === '#' + entry.target.id) link.setAttribute('aria-current','location');
    else link.removeAttribute('aria-current');
  });
}, {rootMargin:'0px 0px -65% 0px'});
document.querySelectorAll('main h2').forEach(heading => sectionObserver.observe(heading));
""".strip("\n")

FENCE = re.compile(r"^```mermaid[ \t]*\n(.*?)^```[ \t]*$\n?", re.S | re.M)


def slugify(text: str) -> str:
    """Turn a heading into the anchor id used by the page and its sidebar."""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text).lower()
    text = re.sub(r"[^a-z0-9 -]", "", text)
    text = re.sub(r"\s+", "-", text.strip())
    return re.sub(r"-+", "-", text)


class Renderer:
    """Runs Mermaid CLI with the shared theme and Puppeteer configuration."""

    def __init__(self, mmdc: str | None, chrome: str | None, workdir: Path) -> None:
        """Write the theme and browser configuration files into ``workdir``."""
        self.command = (
            [mmdc] if mmdc else ["npx", "-y", f"@mermaid-js/mermaid-cli@{MERMAID_VERSION}"]
        )
        self.config = workdir / "mermaid-config.json"
        self.config.write_text(json.dumps(MERMAID_CONFIG))
        self.puppeteer: Path | None = None
        if chrome:
            self.puppeteer = workdir / "puppeteer.json"
            self.puppeteer.write_text(
                json.dumps(
                    {
                        "executablePath": chrome,
                        "args": ["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
                    }
                )
            )

    def render(self, source: str, svg_id: str) -> str:
        """Render one Mermaid source to an SVG string whose root id is ``svg_id``."""
        return render_svg(self, source, svg_id)


def render_svg(renderer: Renderer, source: str, svg_id: str) -> str:
    """Run Mermaid CLI on ``source`` in a temporary directory and return the SVG."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "d.mmd"
        out = Path(tmp) / "d.svg"
        src.write_text(source)
        cmd = [
            *renderer.command,
            "-c",
            str(renderer.config),
            "-i",
            str(src),
            "-o",
            str(out),
            "-b",
            "transparent",
            "--svgId",
            svg_id,
        ]
        if renderer.puppeteer:
            cmd += ["-p", str(renderer.puppeteer)]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if proc.returncode != 0 or not out.exists():
            raise RuntimeError(f"mmdc failed for {svg_id}:\n{proc.stdout}\n{proc.stderr}")
        return out.read_text()


def figure(number: int, title: str, source: str, svg: str) -> str:
    """Wrap a rendered diagram in the page's figure, toolbar and source drawer."""
    t = html.escape(title, quote=True)
    label = html.escape(f"{title} — class diagram {number}", quote=True)
    svg = svg.replace("<svg ", f'<svg aria-label="{label}" ', 1)
    # Mermaid measures long member labels a fraction too narrow and then lets the
    # browser wrap them (after a leading "-" or at a space); keep every member on one line.
    svg = svg.replace("white-space: break-spaces", "white-space: nowrap")
    svg = re.sub(r"\s*\n\s*", " ", svg).strip()
    return (
        f'<figure class="diagram" id="diagram-{number}" data-title="{t}">\n'
        f'<figcaption><span class="diagram-number">{number:02d}</span><strong>{t}</strong>'
        f'<a href="#diagram-{number}" aria-label="Link to diagram {number}">#</a></figcaption>\n'
        f'<div class="diagram-toolbar" role="group" aria-label="Diagram {number} controls">\n'
        f'<button type="button" data-action="out" aria-label="Zoom out diagram {number}">−</button>\n'  # noqa: RUF001
        f'<output aria-live="polite" aria-label="Diagram {number} zoom">Fit</output>\n'
        f'<button type="button" data-action="in" aria-label="Zoom in diagram {number}">+</button>\n'
        f'<button type="button" data-action="fit">Fit width</button><button type="button" data-action="actual">100%</button>\n'
        f'<button type="button" data-action="expand">Expand</button><button type="button" data-action="download">Save SVG</button>\n'
        f"</div>\n"
        f'<div class="viewport" tabindex="0" role="region" aria-label="Diagram {number}; use arrow keys to pan when zoomed">{svg}</div>\n'
        f'<details class="diagram-source"><summary>Mermaid source</summary><pre><code>{html.escape(source.rstrip())}</code></pre></details>\n'
        f"</figure>\n"
    )


def build(name: str, renderer: Renderer, date: str, commit: str, jobs: int) -> None:
    """Render ``design/<name>-uml.md`` into ``design/<name>-uml.html``."""
    spec = ATLASES[name]
    md_path = DESIGN / f"{name}-uml.md"
    out_path = DESIGN / f"{name}-uml.html"
    args = argparse.Namespace(
        md=str(md_path),
        out=str(out_path),
        slug=name,
        area=spec["area"],
        h1=spec["h1"],
        lead=spec["lead"],
        description=spec["description"],
        badges=spec["badges"],
        toplinks=spec["toplinks"],
        nav_title=spec["nav_title"],
        hints=spec["hints"],
        placeholder=spec["placeholder"],
        skip_label="Skip to class atlas",
        date=date,
        commit=commit,
        jobs=jobs,
    )
    md_path = Path(args.md)
    md = md_path.read_text()
    md_name = md_path.name

    m = re.match(r"#\s+(.+)\n", md)
    doc_title = m.group(1).strip()
    md = md[m.end() :]
    page_title = "Huron — " + re.sub(r"\s+—\s+UML class atlas$", "", doc_title) + " UML Class Atlas"

    # Swap the "open the browser edition" sentence for the Markdown-source pointer.
    md = re.sub(
        r"Open \[the browser edition\]\([^)]*\)[^.]*?Markdown viewer\.",
        f"The [editable Markdown source]({md_name}) contains all Mermaid diagrams and responsibility notes.",
        md,
        count=1,
        flags=re.S,
    )

    # Pull mermaid fences out, remember the section title each belongs to.
    diagrams: list[tuple[str, str]] = []

    def _take(match: re.Match) -> str:
        before = md[: match.start()]
        heads = re.findall(r"^##\s+(.+)$", before, re.M)
        title = heads[-1].strip() if heads else doc_title
        diagrams.append((title, match.group(1)))
        return f"\n@@DIAGRAM{len(diagrams)}@@\n\n"

    body_md = FENCE.sub(_take, md)

    mdit = MarkdownIt("commonmark").enable("table")
    body = mdit.render(body_md)

    # Headings with ids.
    def _h2(match: re.Match) -> str:
        inner = match.group(1)
        return f'<h2 id="{slugify(inner)}" tabindex="-1">{inner}</h2>'

    body = re.sub(r"<h2>(.*?)</h2>", _h2, body, flags=re.S)

    def _table(mt: re.Match) -> str:
        first = re.search(r"<th>(.*?)</th>", mt.group(1), re.S)
        label = html.escape(
            re.sub(r"<[^>]+>", "", first.group(1)) if first else "Reference", quote=True
        )
        return (
            f'<div class="table-wrap" tabindex="0" role="region" aria-label="{label} reference table"><table>'
            + mt.group(1)
            + "</table></div>"
        )

    body = re.sub(r"<table>(.*?)</table>", _table, body, flags=re.S)

    # Render SVGs in parallel.
    with cf.ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {
            n: pool.submit(renderer.render, src, f"{args.slug}-svg-{n}")
            for n, (_, src) in enumerate(diagrams, start=1)
        }
        svgs = {n: f.result() for n, f in futures.items()}
    for n, (title, src) in enumerate(diagrams, start=1):
        fig = figure(n, title, src, svgs[n])
        body = body.replace(f"<p>@@DIAGRAM{n}@@</p>", fig)
        assert f"@@DIAGRAM{n}@@" not in body

    nav_items = "".join(
        f'<li><a href="#{slugify(t)}">{t}</a></li>'
        for t in re.findall(r"<h2 id=\"[^\"]+\" tabindex=\"-1\">(.*?)</h2>", body, re.S)
    )
    badges = "".join(
        f"<span>{html.escape(b.strip())}</span>"
        for b in args.badges.format(diagrams=len(diagrams)).split("|")
    )
    toplinks = "".join(
        f'<a href="{href}">{label}</a>'
        for href, label in (p.split("=", 1) for p in args.toplinks.split(";") if p)
    )
    count = len(diagrams)
    script = (
        SCRIPT.replace("__SLUG__", args.slug)
        .replace("__COUNT__", str(count))
        .replace("__HINTS__", args.hints)
    )

    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="description" content="{html.escape(args.description, quote=True)}">
<title>{html.escape(page_title)}</title>
<!-- Generated by scripts/render_uml_atlas.py from {md_name} using Mermaid CLI {MERMAID_VERSION}. All diagrams are embedded SVG; no runtime library or network access required. -->
<style>
{CSS}
</style>
</head>
<body>
<a class="skip" href="#main">{html.escape(args.skip_label)}</a>
<nav class="topbar" aria-label="Design documents"><a class="brand" href="index.html">HURON</a><div class="toplinks">{toplinks}<a href="{md_name}">Markdown source</a><button type="button" id="theme-toggle">Dark mode</button></div></nav>
<div class="layout"><aside><div class="sidebar"><label class="search-label" for="class-search">Find a class</label><input type="search" id="class-search" placeholder="{html.escape(args.placeholder, quote=True)}" autocomplete="off" aria-describedby="search-status"><p id="search-status" role="status">Find a class across all {count} diagrams.</p><ul id="search-results" aria-label="Matching classes"></ul><nav aria-label="Atlas sections"><h2>{html.escape(args.nav_title)}</h2><ol>{nav_items}</ol></nav></div></aside>
<main id="main" tabindex="-1"><p class="help"><strong>Explore:</strong> choose a section or search for a class. Use <strong>100%</strong> for readable detail, <strong>Fit width</strong> for orientation, and <strong>Expand</strong> for a larger canvas. Scroll or focus a diagram and use arrow keys to pan; Escape closes an expanded view. Save any diagram as SVG.</p><header class="hero"><p class="eyebrow">Huron · Implementation atlas</p><h1>{html.escape(args.h1)}</h1><p class="lead">{html.escape(args.lead)}</p><div class="badges">{badges}</div></header>
{body.strip()}
<footer>Huron {html.escape(args.area)} implementation atlas · {html.escape(args.date)} · Working tree based on {html.escape(args.commit)}. Diagrams and interactions are embedded; source-file links expect this document to remain in the repository's design directory.</footer></main></div>
<dialog id="diagram-dialog" aria-labelledby="dialog-title"><div class="dialog-header"><strong id="dialog-title">Class diagram</strong><button type="button" id="close-diagram">Close · Esc</button></div><div id="dialog-content"></div></dialog>
<script>
{script}
</script>
</body></html>
"""
    Path(args.out).write_text(page)
    print(
        f"wrote {out_path.relative_to(REPO)}: {count} diagrams, {len(page)} bytes", file=sys.stderr
    )


def main() -> None:
    """Command-line entry point."""
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "atlases", nargs="*", help=f"atlas names among {', '.join(ATLASES)}; default all"
    )
    ap.add_argument("--mmdc", help="path to an installed Mermaid CLI binary (default: npx)")
    ap.add_argument(
        "--chrome",
        default="/usr/bin/google-chrome",
        help="Chrome/Chromium executable for Puppeteer; pass '' to use Puppeteer's own browser",
    )
    ap.add_argument(
        "--date",
        help="snapshot date for the footer (default: taken from the Markdown snapshot line)",
    )
    ap.add_argument(
        "--commit", help="commit for the footer (default: taken from the Markdown snapshot line)"
    )
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()
    names = args.atlases or list(ATLASES)
    unknown = [name for name in names if name not in ATLASES]
    if unknown:
        ap.error(f"unknown atlas: {', '.join(unknown)}")
    with tempfile.TemporaryDirectory() as tmp:
        renderer = Renderer(args.mmdc, args.chrome or None, Path(tmp))
        for name in names:
            md = (DESIGN / f"{name}-uml.md").read_text()
            snap = re.search(
                r"\*\*Implementation snapshot: (.+?), working tree based on `([0-9a-f]+)`", md
            )
            date = args.date or (snap.group(1) if snap else "unknown date")
            commit = args.commit or (snap.group(2) if snap else "unknown")
            build(name, renderer, date, commit, args.jobs)


if __name__ == "__main__":
    main()
