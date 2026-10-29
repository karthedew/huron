import { unified } from 'unified';
import remarkParse from 'remark-parse';
import remarkGfm from 'remark-gfm';
import remarkDirective from 'remark-directive';
import { visit } from 'unist-util-visit';
import { toString } from 'mdast-util-to-string';
import { toMarkdown } from 'mdast-util-to-markdown';
import { parseDocument, stringify } from 'yaml';
import { parseFragment } from 'parse5';
import { unified as astroUnified } from '@astrojs/markdown-remark';

const parser = unified().use(remarkParse).use(remarkGfm).use(remarkDirective);
const asideTypes = new Set(['note', 'tip', 'caution', 'danger']);
const renderer = await astroUnified({ smartypants: false }).createRenderer({ syntaxHighlight: false });
export const ast = (body) => parser.parse(body);

export function htmlWalk(node, visitor) {
  visitor(node);
  for (const child of node.childNodes ?? []) htmlWalk(child, visitor);
}

export function htmlIds(html) {
  const ids = [];
  htmlWalk(parseFragment(html), (node) => {
    for (const attr of node.attrs ?? []) if (attr.name === 'id' || (node.tagName === 'a' && attr.name === 'name')) ids.push(attr.value);
  });
  return ids;
}

export function validTitle(value) {
  return typeof value === 'string' && value.trim() === value && value.length > 0 && value.length <= 200 && !/[\r\n\x00-\x1f]/.test(value);
}

function frontmatter(text, title) {
  let data = {};
  let body = text;
  if (text.startsWith('---\n')) {
    const end = text.indexOf('\n---\n', 4);
    if (end < 0) throw new Error('Invalid frontmatter: unterminated');
    const doc = parseDocument(text.slice(4, end), { uniqueKeys: true });
    if (doc.errors.length) throw new Error(`Invalid frontmatter: ${doc.errors[0].message}`);
    data = doc.toJS({ maxAliasCount: 0 });
    if (!data || Array.isArray(data) || typeof data !== 'object') throw new Error('Invalid frontmatter: expected mapping');
    if (Object.keys(data).some((key) => !['title', 'status'].includes(key))) throw new Error('Invalid frontmatter: unsupported field');
    if (data.title !== undefined && (!validTitle(data.title) || data.title !== title)) throw new Error('Invalid frontmatter title');
    if (data.status !== undefined && data.status !== 'accepted') throw new Error('Invalid frontmatter status');
    body = text.slice(end + 5);
  }
  return { data, body };
}

// Temporary migration probe: preserve copied canonical bytes and normalize only
// the known PyMdown forms. Production authors should use native Starlight syntax.
function normalizeAsides(body) {
  const protectedLines = new Set();
  visit(ast(body), 'code', (node) => {
    // Indented prose following !!! is intentionally not a literal fenced block.
    const first = body.split('\n')[node.position.start.line - 1];
    if (!/^\s*(`{3,}|~{3,})/.test(first)) return;
    for (let line = node.position.start.line; line <= node.position.end.line; line++) protectedLines.add(line);
  });
  const lines = body.split('\n');
  const output = [];
  for (let i = 0; i < lines.length; i++) {
    if (protectedLines.has(i + 1) || !/^!!!/.test(lines[i])) {
      output.push(lines[i]);
      continue;
    }
    const match = /^!!! (info|note|warning|tip|danger)(?: "([^"\n]+)")?$/.exec(lines[i]);
    if (!match) throw new Error('Invalid legacy aside');
    const name = { info: 'note', warning: 'caution' }[match[1]] ?? match[1];
    const inner = [];
    while (i + 1 < lines.length && (!lines[i + 1].trim() || lines[i + 1].startsWith('    '))) {
      i++;
      inner.push(lines[i].startsWith('    ') ? lines[i].slice(4) : lines[i]);
    }
    if (!inner.some((line) => line.trim())) throw new Error('Invalid empty legacy aside');
    output.push(`:::${name}${match[2] ? `[${match[2]}]` : ''}`, ...inner, ':::', '');
  }
  const normalized = output.join('\n');
  visit(ast(normalized), (node) => {
    if (node.type.endsWith('Directive') && (node.type !== 'containerDirective' || !asideTypes.has(node.name))) throw new Error(`Invalid aside: ${node.name}`);
    if (node.type === 'containerDirective') {
      const source = normalized.slice(node.position.start.offset, node.position.end.offset);
      if (!/\n:{3,}\s*$/.test(source)) throw new Error('Invalid aside: unclosed');
    }
  });
  return normalized;
}

export async function view(text, title) {
  if (!validTitle(title)) throw new Error('Invalid manifest title');
  const { data, body } = frontmatter(text, title);
  const normalized = normalizeAsides(body);
  const original = await renderer.render(normalized);
  const originalIds = htmlIds(original.code);
  const tree = ast(normalized);
  const first = tree.children[0];
  let result = normalized;
  if (first?.type === 'heading' && first.depth === 1 && toString(first) === title) {
    const id = original.metadata.headings[0].slug;
    result = normalized.slice(0, first.position.start.offset) + `<a id="${id}"></a>` + normalized.slice(first.position.end.offset);
  }
  const ids = htmlIds((await renderer.render(result)).code);
  if (new Set(ids).size !== ids.length) throw new Error('Duplicate explicit or generated anchor');
  if (originalIds.some((id) => !ids.includes(id))) throw new Error('Anchor drift after title normalization');
  return { body: result, data: { ...data, title }, ids: new Set(ids), tree: ast(result) };
}

export function rewrite(body, tree, resolveLink) {
  const patches = [];
  visit(tree, (node) => {
    if (['link', 'image', 'definition'].includes(node.type)) {
      const result = resolveLink(node.url, node.type === 'image');
      if (result.url === node.url && !result.externalSource) return;
      const copy = { ...node, url: result.url };
      if (result.externalSource && copy.children) copy.children = [...copy.children, { type: 'text', value: ' (external source reference)' }];
      patches.push({ start: node.position.start.offset, end: node.position.end.offset, value: toMarkdown(copy).trimEnd() });
      return 'skip';
    }
    if (node.type !== 'html') return;
    const html = parseFragment(node.value, { sourceCodeLocationInfo: true });
    htmlWalk(html, (element) => {
      for (const attr of element.attrs ?? []) {
        if (!['href', 'src'].includes(attr.name)) continue;
        const result = resolveLink(attr.value, attr.name === 'src');
        if (result.externalSource) throw new Error('Use labelled Markdown links for external source references');
        const range = element.sourceCodeLocation?.attrs?.[attr.name];
        if (!range) throw new Error('Cannot safely rewrite HTML URL');
        patches.push({ start: node.position.start.offset + range.startOffset, end: node.position.start.offset + range.endOffset, value: `${attr.name}="${result.url.replaceAll('&', '&amp;').replaceAll('"', '&quot;')}"` });
      }
    });
  });
  let end = body.length;
  for (const patch of patches.sort((a, b) => b.start - a.start)) {
    if (patch.end > end) throw new Error('Overlapping AST rewrite');
    body = body.slice(0, patch.start) + patch.value + body.slice(patch.end);
    end = patch.start;
  }
  return body;
}

export function generated(page, parsed, body) {
  const origin = page.synthetic ? 'Synthetic fixture' : `Canonical source: \`${page.source}\`${page.excerpt ? `, verbatim lines ${page.excerpt.join('–')}` : ''}`;
  return `---\n${stringify(parsed.data)}---\n\n> **Throwaway prototype — not shipped documentation.** ${origin}. Generated rendering view; original source remains authoritative.\n\n${body.trim()}\n`;
}
