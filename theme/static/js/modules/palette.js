/**
 * Ctrl+K command palette. Loaded on demand, never on first paint.
 *
 * The input is an ARIA combobox driving a listbox: arrow keys move
 * `aria-selected` and `aria-activedescendant` while DOM focus stays in the
 * input, which is what lets a screen-reader user hear the active option
 * without losing their typing position. That is also why the options contain
 * no links — a listbox option with a focusable descendant is ambiguous to
 * assistive technology, so navigation happens on Enter instead.
 */

import { qs, qsa, el, clear, on, debounce, safePath, frag } from './dom.js';
import { createModal } from './modal.js';
import { loadIndex, search, tokenize, optionNode } from './search.js';
import { cycle as cycleTheme, apply as applyTheme, list as themeList } from './theme.js';
import { toggleMotion, motionOK } from './motion.js';

const LIMIT = 12;
const OPTION_ID = 'palette-opt-';

function navigate(url) {
  if (!safePath(url)) return;
  location.assign(url);
}

/** Static commands, derived from the DOM and #site-data rather than hardcoded. */
function buildCommands(data, api) {
  const commands = [];

  for (const link of qsa('#primary-nav .nav-list a[href]')) {
    const label = (link.textContent ?? '').replace(/^[\s/]+/, '').trim();
    const href = link.getAttribute('href') ?? '';
    if (label && safePath(href)) {
      commands.push({ label, hint: href, run: () => navigate(href) });
    }
  }

  const home = typeof data?.home === 'string' && safePath(data.home) ? data.home : '/';
  const searchUrl = home.endsWith('/') ? home + 'search/' : home + '/search/';
  commands.push({ label: 'search', hint: searchUrl, run: () => navigate(searchUrl) });

  const terminalLabel = qs('[data-action="open-terminal"]')?.getAttribute('aria-label') ?? 'terminal';
  commands.push({ label: terminalLabel, hint: '`', run: () => api.openTerminal() });

  for (const name of themeList()) {
    commands.push({
      label: (data?.strings?.themeSwitch ?? 'theme') + ': ' + name,
      hint: 'theme',
      run: () => applyTheme(name),
      keepOpen: true,
    });
  }
  commands.push({
    label: (data?.strings?.themeSwitch ?? 'theme') + ' →',
    hint: 'cycle',
    run: () => cycleTheme(),
    keepOpen: true,
  });

  commands.push({
    label: 'motion: ' + (motionOK() ? 'on' : 'off'),
    hint: 'prefers-reduced-motion',
    run: () => { toggleMotion(); },
    keepOpen: true,
  });

  const languages = Array.isArray(data?.languages) ? data.languages : [];
  for (const entry of languages) {
    const url = typeof entry?.url === 'string' ? entry.url : '';
    if (!safePath(url)) continue;
    commands.push({
      label: 'lang: ' + String(entry.native ?? entry.code ?? '').slice(0, 24),
      hint: url,
      run: () => navigate(url),
    });
  }

  return commands;
}

export function init(data, hooks = {}) {
  const root = qs('#palette');
  const input = qs('#palette-input');
  const list = qs('#palette-results');
  const status = qs('#palette-status');
  if (!root || !input || !list) return null;

  const strings = data?.strings ?? {};
  const offs = [];
  let items = [];
  let selected = -1;
  let sequence = 0;

  const api = {
    openTerminal: () => hooks.openTerminal?.(),
  };
  const commands = buildCommands(data, api);

  const modal = createModal(root, {
    initialFocus: () => input,
    onOpen() {
      input.setAttribute('aria-expanded', 'true');
      input.select?.();
      // Re-opening keeps the previous query: it is almost always what someone
      // who just closed the palette by accident wants back.
      if (input.value.trim()) runQuery(input.value);
      else renderCommands('');
    },
    onClose() {
      input.setAttribute('aria-expanded', 'false');
      input.removeAttribute('aria-activedescendant');
      clear(list);
      items = [];
      selected = -1;
      if (status) status.textContent = '';
    },
  });

  function say(message) {
    if (status) status.textContent = message ?? '';
  }

  function select(next) {
    if (items.length === 0) {
      selected = -1;
      input.removeAttribute('aria-activedescendant');
      return;
    }
    const total = items.length;
    selected = ((next % total) + total) % total;
    for (let index = 0; index < total; index += 1) {
      const node = items[index].node;
      const active = index === selected;
      node.setAttribute('aria-selected', active ? 'true' : 'false');
      node.classList.toggle('is-selected', active);
      if (active) {
        input.setAttribute('aria-activedescendant', node.id);
        node.scrollIntoView?.({ block: 'nearest' });
      }
    }
  }

  function paint(entries) {
    clear(list);
    items = entries;
    list.appendChild(frag(entries.map((entry) => entry.node)));
    select(entries.length ? 0 : -1);
  }

  function commandNode(command, index) {
    return el('li', {
      class: 'palette-result palette-command',
      id: OPTION_ID + index,
      role: 'option',
      'aria-selected': 'false',
    }, [
      el('span', { class: 'result-title', text: command.label }),
      command.hint ? el('span', { class: 'result-hint', text: command.hint }) : null,
    ]);
  }

  function matchCommands(query) {
    if (!query) return commands;
    const needle = query.toLowerCase();
    return commands.filter((command) => command.label.toLowerCase().includes(needle));
  }

  function commandEntries(matched) {
    return matched.map((command, index) => ({
      node: commandNode(command, index),
      activate: () => {
        command.run();
        if (!command.keepOpen) modal.close();
        else refreshMotionLabel();
      },
    }));
  }

  function renderCommands(query) {
    const matched = matchCommands(query).slice(0, LIMIT);
    paint(commandEntries(matched));
    say(query ? matched.length + ' ' + (strings.results ?? 'results') : '');
  }

  /** The motion command shows current state, so it has to be rebuilt in place. */
  function refreshMotionLabel() {
    for (const command of commands) {
      if (command.hint === 'prefers-reduced-motion') command.label = 'motion: ' + (motionOK() ? 'on' : 'off');
    }
    renderCommands(input.value.trim());
  }

  async function runQuery(raw) {
    const query = raw.trim().slice(0, 120);
    if (!query) {
      renderCommands('');
      return;
    }
    const ticket = (sequence += 1);
    const matched = matchCommands(query).slice(0, 4);

    // Matching commands are painted before the index is even requested: on the
    // first keystroke of a session that fetch is the slowest thing here, and
    // there is no reason to stare at an empty list while it happens.
    paint(commandEntries(matched));
    say(strings.loading ?? '…');

    const index = await loadIndex(data?.searchIndex ?? '');
    if (ticket !== sequence || !modal.isOpen()) return;

    if (!index) {
      // Index missing (offline, or a failed deploy): commands still work.
      say(strings.noResults ?? 'No results.');
      return;
    }

    const tokens = tokenize(query);
    const hits = search(index, query, { limit: LIMIT });
    const entries = commandEntries(matched);
    const base = entries.length;
    hits.forEach((hit, position) => {
      const node = optionNode(hit.doc, tokens, OPTION_ID + (base + position), strings);
      entries.push({ node, activate: () => navigate(hit.doc.u) });
    });
    paint(entries);
    say(hits.length === 0
      ? (strings.noResults ?? 'No results.')
      : hits.length + ' ' + (strings.results ?? 'results'));
  }

  const debounced = debounce(runQuery, 120);

  offs.push(on(input, 'input', () => {
    const value = input.value;
    // Commands respond instantly; only the index-backed search is debounced.
    if (!value.trim()) {
      debounced.cancel();
      renderCommands('');
    } else {
      debounced(value);
    }
  }));

  offs.push(on(input, 'keydown', (event) => {
    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        select(selected + 1);
        break;
      case 'ArrowUp':
        event.preventDefault();
        select(selected - 1);
        break;
      case 'Home':
        if (items.length) { event.preventDefault(); select(0); }
        break;
      case 'End':
        if (items.length) { event.preventDefault(); select(items.length - 1); }
        break;
      case 'Enter':
        event.preventDefault();
        items[selected]?.activate();
        break;
      default:
        break;
    }
  }));

  offs.push(on(list, 'click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const option = target.closest('[role="option"]');
    if (!option) return;
    const position = items.findIndex((entry) => entry.node === option);
    if (position >= 0) {
      select(position);
      items[position].activate();
    }
  }));

  offs.push(on(list, 'mousemove', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const option = target.closest('[role="option"]');
    if (!option) return;
    const position = items.findIndex((entry) => entry.node === option);
    if (position >= 0 && position !== selected) select(position);
  }, { passive: true }));

  input.setAttribute('aria-expanded', 'false');

  return {
    open(trigger) {
      modal.open(trigger);
    },
    close() {
      modal.close();
    },
    toggle(trigger) {
      if (modal.isOpen()) modal.close();
      else modal.open(trigger);
    },
    isOpen: () => modal.isOpen(),
    destroy() {
      debounced.cancel();
      while (offs.length) offs.pop()();
      modal.destroy();
    },
  };
}
