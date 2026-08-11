/**
 * Search: index loading, ranking, result rendering. Shared by the command
 * palette and the /search/ page so the two can never disagree about what
 * "best match" means.
 *
 * Security note, because this is where it matters most: every field in the
 * index is author-controlled text that ends up on screen — titles, summaries,
 * body extracts — and the highlighter has to interleave <mark> with it. It does
 * that by slicing the string and appending real element nodes. There is no
 * point in this file where markup is assembled from a string, which is the only
 * way to make "highlight the matched substring" safe by construction.
 */

import { el, qs, clear, on, debounce, safePath, frag } from './dom.js';

const TOKEN = /[a-z0-9_][a-z0-9_./-]*/g;
const MAX_TOKENS = 8;
const MAX_PREFIX_EXPANSIONS = 24;
const MAX_HIGHLIGHTS = 24;

const cache = new Map();

// -- loading ------------------------------------------------------------- //

function cleanDoc(raw) {
  if (!raw || typeof raw !== 'object') return null;
  const url = typeof raw.u === 'string' ? raw.u : '';
  // A document we cannot safely link to is worse than a missing result.
  if (!safePath(url.split('#')[0] || '/')) return null;
  return {
    i: Number(raw.i) || 0,
    t: String(raw.t ?? ''),
    u: url,
    s: String(raw.s ?? ''),
    k: String(raw.k ?? ''),
    d: String(raw.d ?? ''),
    g: Array.isArray(raw.g) ? raw.g.slice(0, 10).map((tag) => String(tag)) : [],
    r: Number(raw.r) || 0,
    x: String(raw.x ?? ''),
    p: raw.p ? String(raw.p) : '',
    f: raw.f ? String(raw.f) : '',
  };
}

function prepare(payload) {
  if (!payload || typeof payload !== 'object' || !Array.isArray(payload.docs)) return null;
  const docs = new Map();
  for (const raw of payload.docs) {
    const doc = cleanDoc(raw);
    if (doc) docs.set(doc.i, doc);
  }
  const terms = payload.terms && typeof payload.terms === 'object' ? payload.terms : {};
  // Sorted once so prefix lookups can binary-search. Object key order is not
  // dependable here: integer-like keys such as "2024" are hoisted by the engine.
  const keys = Object.keys(terms).sort();
  return { docs, terms, keys, count: docs.size, lang: String(payload.lang ?? '') };
}

/**
 * Fetch and memoise one index. Resolves to null on any failure — a search box
 * that says "index unavailable" is a working page; a thrown promise is not.
 */
export function loadIndex(url) {
  if (!safePath(url)) return Promise.resolve(null);
  if (cache.has(url)) return cache.get(url);
  const pending = fetch(url, { credentials: 'omit', cache: 'default' })
    .then((response) => (response.ok ? response.json() : null))
    .then((payload) => prepare(payload))
    .catch(() => null)
    .then((index) => {
      // Do not cache a failure: the visitor may just have been offline.
      if (!index) cache.delete(url);
      return index;
    });
  cache.set(url, pending);
  return pending;
}

// -- ranking ------------------------------------------------------------- //

export function tokenize(query) {
  const found = String(query ?? '').toLowerCase().match(TOKEN);
  return found ? found.slice(0, MAX_TOKENS) : [];
}

function lowerBound(keys, prefix) {
  let low = 0;
  let high = keys.length;
  while (low < high) {
    const middle = (low + high) >> 1;
    if (keys[middle] < prefix) low = middle + 1;
    else high = middle;
  }
  return low;
}

function addScore(scores, postings, weight) {
  if (!Array.isArray(postings)) return;
  for (const entry of postings) {
    if (!Array.isArray(entry)) continue;
    const id = Number(entry[0]);
    const count = Number(entry[1]) || 1;
    // Diminishing returns on repetition: a word used 40 times is not 40 times
    // more relevant than a word used once.
    scores.set(id, (scores.get(id) ?? 0) + weight * (1 + Math.log(1 + count) / 2.5));
  }
}

/** Subsequence match with bonuses for consecutive runs and word starts. */
export function fuzzy(haystack, needle) {
  if (!needle) return 0;
  let hi = 0;
  let ni = 0;
  let streak = 0;
  let bonus = 0;
  let matched = 0;
  while (hi < haystack.length && ni < needle.length) {
    if (haystack[hi] === needle[ni]) {
      matched += 1;
      streak += 1;
      bonus += streak * 0.7;
      if (hi === 0 || !/[a-z0-9]/.test(haystack[hi - 1])) bonus += 1.6;
      ni += 1;
    } else {
      streak = 0;
    }
    hi += 1;
  }
  if (ni < needle.length) return 0;
  return Math.min(1, (matched + bonus) / (needle.length * 3 + 2));
}

function fieldScore(text, token, weight) {
  if (!text) return 0;
  const at = text.indexOf(token);
  if (at < 0) return 0;
  let score = weight;
  const before = at === 0 ? '' : text[at - 1];
  if (at === 0) score += weight * 0.75;
  else if (!/[a-z0-9]/.test(before)) score += weight * 0.5;
  const after = text[at + token.length];
  if (after === undefined || !/[a-z0-9]/.test(after)) score += weight * 0.25;
  return score;
}

function recency(iso) {
  if (!/^\d{4}-\d{2}-\d{2}/.test(iso)) return 0;
  const when = Date.parse(iso);
  if (Number.isNaN(when)) return 0;
  const days = (Date.now() - when) / 86400000;
  return 1.4 * Math.exp(-Math.max(0, days) / 900);
}

/**
 * @param {object} index from loadIndex
 * @param {string} query
 * @param {{limit?: number}} [options]
 * @returns {Array<{doc: object, score: number}>}
 */
export function search(index, query, options = {}) {
  const limit = options.limit ?? 20;
  const tokens = tokenize(query);
  if (!index || tokens.length === 0) return [];

  const scores = new Map();
  for (const token of tokens) {
    addScore(scores, index.terms[token], 3.4);
    if (token.length >= 2) {
      let position = lowerBound(index.keys, token);
      let expansions = 0;
      while (position < index.keys.length && expansions < MAX_PREFIX_EXPANSIONS) {
        const key = index.keys[position];
        if (!key.startsWith(token)) break;
        if (key !== token) addScore(scores, index.terms[key], 1.5 * (token.length / key.length));
        position += 1;
        expansions += 1;
      }
    }
  }

  // Candidates from the inverted index, plus every document when the index gave
  // us almost nothing — that is the case a typo produces, and it is exactly
  // when the fuzzy title match earns its keep.
  const candidates = scores.size >= 4 ? Array.from(scores.keys()) : Array.from(index.docs.keys());
  const phrase = tokens.join(' ');
  const results = [];

  for (const id of candidates) {
    const doc = index.docs.get(id);
    if (!doc) continue;
    const title = doc.t.toLowerCase();
    const tags = doc.g.join(' ').toLowerCase();
    const summary = doc.s.toLowerCase();
    const body = doc.x.toLowerCase();

    let score = scores.get(id) ?? 0;
    let hits = 0;
    for (const token of tokens) {
      const field = fieldScore(title, token, 9)
        + fieldScore(tags, token, 5.5)
        + fieldScore(summary, token, 2.5)
        + fieldScore(body, token, 1);
      if (field > 0) hits += 1;
      score += field;
    }

    // Whole-phrase hits: consecutive matched characters beat scattered ones.
    if (tokens.length > 1) {
      if (title.includes(phrase)) score += 14;
      else if (summary.includes(phrase)) score += 5;
      else if (body.includes(phrase)) score += 2.5;
    }

    const near = fuzzy(title, phrase.replace(/\s+/g, ''));
    score += near * 7;

    if (score <= 0 || (hits === 0 && near < 0.35 && (scores.get(id) ?? 0) === 0)) continue;
    // Every token matching something beats one token matching loudly.
    if (hits === tokens.length && tokens.length > 1) score += 4;
    score += recency(doc.d);
    results.push({ doc, score });
  }

  results.sort((left, right) => right.score - left.score || left.doc.t.localeCompare(right.doc.t));
  return results.slice(0, limit);
}

// -- rendering ----------------------------------------------------------- //

/**
 * Wrap every occurrence of `tokens` in <mark>, as nodes.
 * Returns a DocumentFragment; the caller decides where it goes.
 */
export function highlight(text, tokens) {
  const source = String(text ?? '');
  const output = document.createDocumentFragment();
  if (!source) return output;

  const lower = source.toLowerCase();
  const ranges = [];
  for (const token of tokens) {
    if (!token) continue;
    let at = lower.indexOf(token);
    while (at !== -1 && ranges.length < MAX_HIGHLIGHTS) {
      ranges.push([at, at + token.length]);
      at = lower.indexOf(token, at + token.length);
    }
  }
  if (ranges.length === 0) {
    output.appendChild(document.createTextNode(source));
    return output;
  }

  ranges.sort((left, right) => left[0] - right[0]);
  const merged = [ranges[0]];
  for (const range of ranges.slice(1)) {
    const last = merged[merged.length - 1];
    if (range[0] <= last[1]) last[1] = Math.max(last[1], range[1]);
    else merged.push(range);
  }

  let cursor = 0;
  for (const [start, end] of merged) {
    if (start > cursor) output.appendChild(document.createTextNode(source.slice(cursor, start)));
    output.appendChild(el('mark', { text: source.slice(start, end) }));
    cursor = end;
  }
  if (cursor < source.length) output.appendChild(document.createTextNode(source.slice(cursor)));
  return output;
}

/** A window of body text around the first match, for context. */
export function snippet(doc, tokens, length = 170) {
  const source = doc.s || doc.x || '';
  if (!source) return '';
  const lower = source.toLowerCase();
  let at = -1;
  for (const token of tokens) {
    const found = lower.indexOf(token);
    if (found !== -1 && (at === -1 || found < at)) at = found;
  }
  if (at <= 0) return source.slice(0, length) + (source.length > length ? '…' : '');
  const start = Math.max(0, source.lastIndexOf(' ', Math.max(0, at - 50)) + 1);
  const end = Math.min(source.length, start + length);
  return (start > 0 ? '…' : '') + source.slice(start, end).trim() + (end < source.length ? '…' : '');
}

function metaNodes(doc, strings) {
  const parts = [el('span', { class: 'result-kind', text: doc.k || 'doc' })];
  if (doc.d) parts.push(el('time', { class: 'result-date', datetime: doc.d, text: doc.d.slice(0, 10) }));
  if (doc.r > 0) parts.push(el('span', { class: 'result-read', text: doc.r + ' ' + (strings?.readingTime ?? 'min') }));
  if (doc.f) parts.push(el('span', { class: 'chip chip-difficulty', text: doc.f }));
  if (doc.p) parts.push(el('span', { class: 'chip chip-platform', text: doc.p }));
  return el('p', { class: 'result-meta' }, parts);
}

function bodyNodes(doc, tokens, strings) {
  const title = el('span', { class: 'result-title' });
  title.appendChild(highlight(doc.t, tokens));
  const text = snippet(doc, tokens);
  const nodes = [title, metaNodes(doc, strings)];
  if (text) {
    const line = el('p', { class: 'result-snippet' });
    line.appendChild(highlight(text, tokens));
    nodes.push(line);
  }
  if (doc.g.length) {
    nodes.push(el('p', { class: 'result-tags' }, doc.g.slice(0, 4).map((tag) => el('span', { class: 'tag', text: '#' + tag }))));
  }
  return nodes;
}

/** Palette option: a listbox option must not contain a focusable link. */
export function optionNode(doc, tokens, id, strings) {
  return el('li', {
    class: 'palette-result',
    id,
    role: 'option',
    'aria-selected': 'false',
    dataset: { url: doc.u },
  }, bodyNodes(doc, tokens, strings));
}

/** Search-page result: a real link, so it can be opened in a new tab. */
export function resultNode(doc, tokens, strings) {
  return el('li', { class: 'search-result' }, [
    el('a', { class: 'search-result-link', href: doc.u }, bodyNodes(doc, tokens, strings)),
  ]);
}

// -- standalone search page ---------------------------------------------- //

export function initPage(data) {
  const form = qs('#search-form');
  const input = qs('#search-input');
  const list = qs('#search-results');
  const status = qs('#search-status');
  if (!form || !input || !list) return { destroy() {} };

  const strings = data?.strings ?? {};
  const offs = [];
  let sequence = 0;

  function say(message) {
    if (status) status.textContent = message;
  }

  function render(results, tokens) {
    clear(list);
    if (results.length === 0) return;
    list.appendChild(frag(results.map((hit) => resultNode(hit.doc, tokens, strings))));
  }

  async function run(raw) {
    const query = String(raw ?? '').trim().slice(0, 120);
    const ticket = (sequence += 1);
    if (!query) {
      clear(list);
      say('');
      return;
    }
    say(strings.loading ?? '…');
    const index = await loadIndex(data?.searchIndex ?? '');
    // A slower earlier query must never overwrite a faster later one.
    if (ticket !== sequence) return;
    if (!index) {
      clear(list);
      say(strings.noResults ?? 'No results.');
      return;
    }
    const tokens = tokenize(query);
    const results = search(index, query, { limit: 40 });
    render(results, tokens);
    say(results.length === 0
      ? (strings.noResults ?? 'No results.')
      : results.length + ' ' + (strings.results ?? 'results'));
    updateUrl(query);
  }

  function updateUrl(query) {
    if (typeof history.replaceState !== 'function') return;
    try {
      const url = new URL(location.href);
      if (query) url.searchParams.set('q', query);
      else url.searchParams.delete('q');
      history.replaceState(history.state, '', url);
    } catch {
      /* cosmetic only */
    }
  }

  const debounced = debounce(run, 120);
  offs.push(on(input, 'input', () => debounced(input.value)));
  // The CSP sets form-action 'none', so a real submit would be blocked by the
  // browser: intercept it and search in place instead.
  offs.push(on(form, 'submit', (event) => {
    event.preventDefault();
    debounced.cancel();
    run(input.value);
  }));

  try {
    const initial = new URLSearchParams(location.search).get('q');
    if (initial) {
      input.value = initial.slice(0, 120);
      run(input.value);
    }
  } catch {
    /* ignore a malformed query string */
  }

  input.focus({ preventScroll: true });

  return {
    destroy() {
      debounced.cancel();
      while (offs.length) offs.pop()();
    },
  };
}
