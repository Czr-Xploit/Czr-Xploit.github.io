/**
 * Client-side filtering for the listing and arsenal pages.
 *
 * Every card is already in the DOM and already readable without JavaScript —
 * this only ever *hides* things, so a failure here leaves a complete, if
 * unfiltered, page. Searchable text is read once at init and cached: doing it
 * per keystroke would mean a full layout read on every character.
 */

import { qs, qsa, el, on, debounce } from './dom.js';

const MAX_QUERY = 64;
const FACETS = ['tag', 'difficulty', 'platform', 'system'];

function normalise(value) {
  return (value ?? '').toString().toLowerCase().trim();
}

function tagSet(node) {
  return new Set(
    (node.getAttribute('data-tags') ?? '')
      .split(',')
      .map((tag) => normalise(tag))
      .filter(Boolean),
  );
}

export function init(data) {
  const inputs = qsa('[data-filter="query"]');
  const chips = qsa('button[data-filter]');
  const grid = qs('#listing-grid');
  const status = qs('#filter-status');
  const items = [];
  const offs = [];

  const nodes = grid ? qsa('.card', grid) : [];
  const arsenal = qsa('.arsenal-item');
  const all = nodes.concat(arsenal.filter((node) => !nodes.includes(node)));
  if (all.length === 0 || (inputs.length === 0 && chips.length === 0)) return { destroy() {} };

  for (const node of all) {
    items.push({
      node,
      group: node.closest('.arsenal-group'),
      text: normalise(node.textContent).replace(/\s+/g, ' '),
      tags: tagSet(node),
      platform: normalise(node.getAttribute('data-platform')),
      difficulty: normalise(node.getAttribute('data-difficulty')),
      system: normalise(node.getAttribute('data-system')),
    });
  }

  const state = { query: '', tag: '', difficulty: '', platform: '', system: '' };
  const strings = data?.strings ?? {};
  const resultsWord = typeof strings.results === 'string' ? strings.results : 'results';
  const noResults = typeof strings.noResults === 'string' ? strings.noResults : 'No results.';
  let emptyNote = null;

  function matches(item) {
    if (state.tag && !item.tags.has(state.tag)) return false;
    if (state.difficulty && item.difficulty !== state.difficulty) return false;
    if (state.platform && item.platform !== state.platform) return false;
    if (state.system && item.system !== state.system) return false;
    if (state.query && !item.text.includes(state.query)) return false;
    return true;
  }

  function apply() {
    let shown = 0;
    const groups = new Map();
    for (const item of items) {
      const visible = matches(item);
      if (visible) shown += 1;
      item.node.hidden = !visible;
      item.node.classList.toggle('is-filtered-out', !visible);
      if (item.group) groups.set(item.group, (groups.get(item.group) ?? 0) + (visible ? 1 : 0));
    }
    // An arsenal category whose every entry is hidden should not leave its
    // heading stranded above an empty list.
    for (const [group, count] of groups) {
      group.hidden = count === 0;
    }

    for (const chip of chips) {
      const facet = chip.getAttribute('data-filter');
      if (!FACETS.includes(facet)) continue;
      const active = normalise(chip.getAttribute('data-value')) === state[facet];
      chip.classList.toggle('is-active', active);
      chip.setAttribute('aria-pressed', active ? 'true' : 'false');
    }

    const filtering = Boolean(state.query || state.tag || state.difficulty || state.platform || state.system);
    if (status) status.textContent = filtering ? (shown === 0 ? noResults : shown + ' ' + resultsWord) : '';

    if (grid) {
      if (shown === 0 && filtering) {
        if (!emptyNote) emptyNote = el('p', { class: 'empty filter-empty', text: noResults });
        if (!emptyNote.isConnected) grid.appendChild(emptyNote);
      } else if (emptyNote?.isConnected) {
        emptyNote.remove();
      }
    }
    syncUrl(filtering);
  }

  /**
   * Reflect the filter in the URL so a filtered view can be shared, using
   * replaceState so the back button still means "previous page".
   */
  function syncUrl(filtering) {
    if (typeof history.replaceState !== 'function') return;
    try {
      const url = new URL(location.href);
      url.searchParams.delete('q');
      url.searchParams.delete('tag');
      if (state.query) url.searchParams.set('q', state.query);
      if (state.tag) url.searchParams.set('tag', state.tag);
      history.replaceState(history.state, '', filtering ? url : url.pathname + url.hash);
    } catch {
      /* URL manipulation is a convenience, never a requirement */
    }
  }

  function setQuery(value) {
    state.query = normalise(value).slice(0, MAX_QUERY);
    apply();
  }

  const debouncedQuery = debounce(setQuery, 120);

  for (const input of inputs) {
    offs.push(on(input, 'input', () => debouncedQuery(input.value)));
    offs.push(on(input, 'search', () => setQuery(input.value)));
    offs.push(on(input, 'keydown', (event) => {
      if (event.key === 'Escape' && input.value) {
        event.stopPropagation();
        input.value = '';
        setQuery('');
      }
    }));
  }

  for (const chip of chips) {
    const facet = chip.getAttribute('data-filter');
    if (!FACETS.includes(facet)) continue;
    offs.push(on(chip, 'click', () => {
      const value = normalise(chip.getAttribute('data-value'));
      state[facet] = state[facet] === value ? '' : value;
      apply();
    }));
  }

  // Query string is untrusted: clamp the free-text field and accept a tag only
  // if the page actually offers a chip for it.
  try {
    const params = new URLSearchParams(location.search);
    const q = params.get('q');
    if (q) {
      state.query = normalise(q).slice(0, MAX_QUERY);
      for (const input of inputs) input.value = state.query;
    }
    const tag = normalise(params.get('tag'));
    if (tag && chips.some((chip) => normalise(chip.getAttribute('data-value')) === tag)) state.tag = tag;
  } catch {
    /* malformed query string: ignore it */
  }

  apply();

  return {
    setQuery,
    destroy() {
      debouncedQuery.cancel();
      while (offs.length) offs.pop()();
      for (const item of items) {
        item.node.hidden = false;
        item.node.classList.remove('is-filtered-out');
      }
    },
  };
}
