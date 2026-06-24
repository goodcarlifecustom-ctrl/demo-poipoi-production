import fs from 'node:fs';
import path from 'node:path';

export const DRAFT_STATUS = 'draft';
export const DEFAULT_NEW_ARTICLE_OPTIONS = Object.freeze({ wordpress_draft: true, status: DRAFT_STATUS });
export const REQUIRED_NEW_ARTICLE_FIELDS = Object.freeze([
  'target_media', 'article_type', 'main_keyword', 'related_keywords', 'target_reader', 'article_goal', 'wordpress_draft',
]);
const PLACEHOLDERS = new Set(['', '記事タイトル', 'example-seo-article', '仮タイトル', '仮キーワード', '<target_media>', '<main_keyword>']);
const SAFE_BLOCKS = ['wp:code', 'wp:html'];
const SAFE_TAGS = ['script', 'style', 'pre', 'code'];

export function stripFrontMatter(content = '') { return String(content).replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, ''); }
export function extractWpContent(content = '') { return stripFrontMatter(content).trimStart(); }
function valueAt(input, dotted) { return dotted.split('.').reduce((acc, key) => (acc == null ? acc : acc[key]), input); }
function isMissing(v) { return v === undefined || v === null || v === '' || (Array.isArray(v) && v.length === 0); }
function hasPlaceholder(v) { return typeof v === 'string' && (PLACEHOLDERS.has(v.trim()) || /^<[^>]+>$/.test(v.trim())); }
function htmlDecode(s = '') { return String(s).replace(/&#x([0-9a-f]+);/gi, (_, n) => String.fromCodePoint(parseInt(n, 16))).replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n))).replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;|&apos;/g, "'"); }
export function normalizeText(s = '') { return htmlDecode(String(s).replace(/<[^>]+>/g, '')).replace(/[\s\u3000]+/g, ' ').trim(); }

export function normalizeDraftSettings(input = {}, { requireDraftEnabled = false } = {}) {
  const hasWp = Object.hasOwn(input, 'wordpress_draft');
  const hasLegacy = Object.hasOwn(input, 'post_to_wp');
  const wordpressDraft = hasWp ? input.wordpress_draft : (hasLegacy ? input.post_to_wp : DEFAULT_NEW_ARTICLE_OPTIONS.wordpress_draft);
  if (typeof wordpressDraft !== 'boolean') throw new Error('wordpress_draft must be boolean');
  if (hasLegacy && typeof input.post_to_wp !== 'boolean') throw new Error('post_to_wp must be boolean when specified');
  if (hasWp && hasLegacy && input.wordpress_draft !== input.post_to_wp) throw new Error('wordpress_draft and post_to_wp must match when both are specified');
  const status = input.status ?? DRAFT_STATUS;
  if (status !== DRAFT_STATUS) throw new Error('Only draft status is allowed');
  if (requireDraftEnabled && wordpressDraft !== true) throw new Error('wordpress_draft must be true before WordPress posting');
  return { ...input, wordpress_draft: wordpressDraft, post_to_wp: wordpressDraft, status: DRAFT_STATUS };
}

export function normalizeCharCount(input = {}) {
  const source = input.char_count || input.word_count;
  if (!source) throw new Error('Missing required new article input: char_count.min, char_count.target, char_count.max');
  const min = Number(source.min), target = Number(source.target), max = Number(source.max);
  if (![min, target, max].every(Number.isFinite)) throw new Error('Character count settings must be numeric');
  if (!Number.isInteger(min) || !Number.isInteger(target) || !Number.isInteger(max)) throw new Error('Character count settings must be integers');
  if (!(min <= target && target <= max)) throw new Error('Character count settings must satisfy min <= target <= max');
  return { min, target, max };
}

export function validateNewArticleInput(input = {}, options = {}) {
  const missing = REQUIRED_NEW_ARTICLE_FIELDS.filter((field) => isMissing(valueAt(input, field)));
  const countMissing = !input.char_count && !input.word_count;
  if (missing.length || countMissing) throw new Error(`Missing required new article input: ${[...missing, ...(countMissing ? ['char_count.min', 'char_count.target', 'char_count.max'] : [])].join(', ')}`);
  const normalized = normalizeDraftSettings(input, options);
  const charCount = normalizeCharCount(normalized);
  const placeholders = ['title', 'slug', 'target_media', 'main_keyword', 'target_reader', 'article_goal'].filter((field) => hasPlaceholder(normalized[field]));
  if (placeholders.length) throw new Error(`Placeholder metadata remains: ${placeholders.join(', ')}`);
  return { ...normalized, char_count: charCount, word_count: normalized.word_count || charCount };
}

export function stripIgnoredRegionsForMarkdown(body = '') {
  let out = String(body);
  for (const block of SAFE_BLOCKS) out = out.replace(new RegExp(`<!--\\s*${block.replace(':', ':')}\\b[\\s\\S]*?<!--\\s*\\/${block.replace(':', ':')}\\s*-->`, 'gi'), '');
  for (const tag of SAFE_TAGS) out = out.replace(new RegExp(`<${tag}\\b[\\s\\S]*?<\\/${tag}>`, 'gi'), '');
  out = out.replace(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>/gi, '');
  return out;
}

export function visibleText(content = '') {
  return htmlDecode(extractWpContent(content)
    .replace(/<!--\s*wp:[\s\S]*?-->/g, '')
    .replace(/<!--\s*\/wp:[\s\S]*?-->/g, '')
    .replace(/<!--(?!\s*\/?wp:)[\s\S]*?-->/g, '')
    .replace(/<script\b[^>]*type=["']application\/ld\+json["'][^>]*>[\s\S]*?<\/script>/gi, '')
    .replace(/<script\b[\s\S]*?<\/script>/gi, '')
    .replace(/<style\b[\s\S]*?<\/style>/gi, '')
    .replace(/<[^>]+>/g, '')
    .replace(/[\s\u3000]+/g, ''));
}
export function visibleCharCount(content = '') { return Array.from(visibleText(content)).length; }

function parseBlockComment(raw) {
  const inner = raw.replace(/^<!--\s*/, '').replace(/\s*-->$/, '').trim();
  const close = inner.startsWith('/wp:');
  if (close) return { type: 'close', name: inner.slice(1).trim() };
  const selfClosing = /\/\s*$/.test(inner);
  const body = selfClosing ? inner.replace(/\/\s*$/, '').trim() : inner;
  const m = body.match(/^wp:([^\s]+)(?:\s+([\s\S]+))?$/);
  if (!m) return null;
  const name = `wp:${m[1]}`;
  const attrs = (m[2] || '').trim();
  if (attrs) JSON.parse(attrs);
  return { type: selfClosing ? 'self' : 'open', name };
}

function validateBlocks(body, errors) {
  const re = /<!--\s*(?:\/)?wp:[\s\S]*?-->/g;
  const stack = [];
  const comments = [...body.matchAll(re)];
  for (const m of comments) {
    let parsed;
    try { parsed = parseBlockComment(m[0]); } catch { errors.push(`Invalid JSON attributes in block comment: ${m[0].slice(0, 80)}`); continue; }
    if (!parsed) continue;
    if (parsed.type === 'self') continue;
    if (parsed.type === 'open') stack.push(parsed.name);
    if (parsed.type === 'close') {
      if (!stack.length) errors.push(`Closing block without opener: ${parsed.name}`);
      else {
        const top = stack.pop();
        if (top !== parsed.name) errors.push(`Gutenberg block mismatch: opened ${top} but closed ${parsed.name}`);
      }
    }
  }
  if (stack.length) errors.push(`Unclosed Gutenberg block(s): ${stack.join(', ')}`);
  if (comments.length === 2) {
    const first = parseBlockComment(comments[0][0]);
    const last = parseBlockComment(comments[1][0]);
    if (first?.name === 'wp:html' && first.type === 'open' && last?.name === 'wp:html' && last.type === 'close') errors.push('article must not be wrapped entirely in a single wp:html block');
  }
}

function headingAnchors(body, errors) {
  const headingBlocks = [...body.matchAll(/<!--\s*wp:heading\s+({[\s\S]*?})\s*-->\s*<h([23])\b([^>]*)>([\s\S]*?)<\/h\2>\s*<!--\s*\/wp:heading\s*-->/gi)];
  const h2s = [];
  for (const m of headingBlocks) {
    let attrs = {};
    try { attrs = JSON.parse(m[1]); } catch { errors.push('Invalid JSON attributes in heading block'); }
    const id = (m[3].match(/\bid=["']([^"']+)["']/i) || [])[1] || '';
    if (attrs.anchor && id && attrs.anchor !== id) errors.push(`Heading anchor and HTML id mismatch: ${attrs.anchor} !== ${id}`);
    if (m[2] === '2') h2s.push({ id, text: normalizeText(m[4]) });
  }
  return h2s;
}

export function validateGutenbergArticle(content, { title = '', metadata = null } = {}) {
  const errors = [];
  const body = extractWpContent(content);
  if (/^---\s*$/m.test(body)) errors.push('front matter remains in article body');
  if (/<\s*h1\b/i.test(body)) errors.push('article body must not contain H1');
  validateBlocks(body, errors);
  const markdownSource = stripIgnoredRegionsForMarkdown(body);
  if (/^#{1,6}\s+\S/m.test(markdownSource)) errors.push('Markdown heading remains in article body');
  if (/^\s*[-*+]\s+\S/m.test(markdownSource) || /^\s*\d+\.\s+\S/m.test(markdownSource)) errors.push('Markdown list remains in article body');
  if (/!\[[^\]]*\]\([^)]*\)/.test(markdownSource)) errors.push('Markdown image syntax remains in article body');
  if (/^\s*\|.+\|\s*$/m.test(markdownSource)) errors.push('Markdown table syntax remains in article body');
  if (/```/.test(markdownSource)) errors.push('Markdown code fence remains in article body');
  const h2s = headingAnchors(body, errors);
  const ids = [...body.matchAll(/\bid=["']([^"']+)["']/gi)].map((m) => m[1]);
  const dupes = ids.filter((id, i) => ids.indexOf(id) !== i);
  if (dupes.length) errors.push(`duplicate id detected: ${[...new Set(dupes)].join(', ')}`);
  h2s.forEach((h2, i) => { const expected = `sec-${String(i + 1).padStart(2, '0')}`; if (h2.id !== expected) errors.push(`H2 id must be stable sequential anchors (${expected}), found ${h2.id}`); });
  const tocStart = body.indexOf('この記事でわかること');
  const firstH2 = body.search(/<h2\b/i);
  if (tocStart < 0) errors.push('この記事でわかること section is required');
  if (tocStart >= 0 && firstH2 >= 0 && tocStart > firstH2) errors.push('この記事でわかること must appear before the first H2');
  const tocRegion = tocStart >= 0 && firstH2 >= 0 ? body.slice(tocStart, firstH2) : '';
  const tocLinks = [...tocRegion.matchAll(/<a\b[^>]*href=["']#([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)].map((m) => ({ id: m[1], text: normalizeText(m[2]) }));
  if (!tocLinks.length) errors.push('この記事でわかること must include anchor links');
  const h2ById = new Map(h2s.map((h) => [h.id, h.text]));
  tocLinks.forEach((link, i) => {
    if (!h2ById.has(link.id)) errors.push(`missing target for TOC link: #${link.id}`);
    else if (h2ById.get(link.id) !== link.text) errors.push(`TOC link text must match H2 text for #${link.id}`);
    if (h2s[i] && h2s[i].id !== link.id) errors.push(`TOC link order must match H2 order at #${link.id}`);
  });
  const titleText = normalizeText(title);
  if (titleText && normalizeText(body).includes(titleText)) errors.push('article title must not be duplicated in body');
  if (metadata) {
    const normalized = validateNewArticleInput(metadata);
    const count = visibleCharCount(body);
    if (count < normalized.char_count.min) errors.push(`Visible character count ${count} is below min ${normalized.char_count.min}`);
    if (count > normalized.char_count.max) errors.push(`Visible character count ${count} exceeds max ${normalized.char_count.max}`);
  }
  if (errors.length) throw new Error(errors.join('; '));
  return { body, h2s, tocLinks, visibleCharCount: visibleCharCount(body), targetCharCount: metadata ? normalizeCharCount(metadata).target : null };
}

export function assertPostableArticle({ slug, files, metadata }) {
  if (slug === '_template' || path.basename(files?.dir || '') === '_template') throw new Error('Template article directory is not postable');
  return validateNewArticleInput(metadata, { requireDraftEnabled: true });
}
export function validateGutenbergArticleFile(file, options = {}) { return validateGutenbergArticle(fs.readFileSync(file, 'utf8'), options); }
