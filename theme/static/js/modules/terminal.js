/**
 * The in-page terminal.
 *
 * It walks a virtual filesystem fetched from /fs-<lang>.json, which the build
 * generates from the same document list that produced the pages — so `ls` and
 * `cat` cannot drift out of sync with what was actually published, and there is
 * no second copy of the site's structure to maintain.
 *
 * Two rules hold everywhere below:
 *  1. Every line of output is a text node. The terminal echoes whatever the
 *     visitor types, so a single innerHTML here would be self-XSS on request.
 *  2. Anything that navigates goes through safePath() first. URLs arrive from
 *     JSON, and JSON is input.
 */

import { qs, el, clear, on, safePath } from './dom.js';
import { createModal } from './modal.js';
import { session, KEYS } from './store.js';
import { banner, shouldRun as shouldBoot, run as runBoot } from './boot.js';
import { apply as applyTheme, list as themeList, current as currentTheme } from './theme.js';

const MAX_LINES = 320;
const MAX_HISTORY = 60;
const DIRS = ['blog', 'writeups', 'arsenal', 'pages'];

// -- argument parsing ---------------------------------------------------- //

/** Split a command line, honouring single and double quotes and backslashes. */
export function parseArgs(line) {
  const args = [];
  let current = '';
  let quote = '';
  let started = false;
  for (let index = 0; index < line.length; index += 1) {
    const char = line[index];
    if (char === '\\' && index + 1 < line.length) {
      current += line[index + 1];
      started = true;
      index += 1;
    } else if (quote) {
      if (char === quote) quote = '';
      else current += char;
    } else if (char === '"' || char === "'") {
      quote = char;
      started = true;
    } else if (/\s/.test(char)) {
      if (started) args.push(current);
      current = '';
      started = false;
    } else {
      current += char;
      started = true;
    }
  }
  if (started) args.push(current);
  return args;
}

/** Levenshtein distance, capped: only used for "did you mean". */
function distance(left, right) {
  if (left === right) return 0;
  if (Math.abs(left.length - right.length) > 3) return 9;
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let i = 1; i <= left.length; i += 1) {
    const row = [i];
    for (let j = 1; j <= right.length; j += 1) {
      row[j] = Math.min(
        previous[j] + 1,
        row[j - 1] + 1,
        previous[j - 1] + (left[i - 1] === right[j - 1] ? 0 : 1),
      );
    }
    previous = row;
  }
  return previous[right.length];
}

/** Turn a shell-ish glob into a regex without letting the pattern be code. */
function globToRegExp(pattern) {
  const escaped = pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\\\*/g, '.*').replace(/\\\?/g, '.');
  try {
    return new RegExp(escaped, 'i');
  } catch {
    return null;
  }
}

function pad(text, width) {
  const value = String(text ?? '');
  return value.length >= width ? value : value + ' '.repeat(width - value.length);
}

// -- module ------------------------------------------------------------- //

export function init(data, hooks = {}) {
  const root = qs('#term');
  const output = qs('#term-output');
  const form = qs('#term-form');
  const input = qs('#term-input');
  const promptNode = qs('#term-prompt');
  if (!root || !output || !form || !input) return null;

  const handle = String(data?.handle ?? 'czr').toLowerCase().slice(0, 20).replace(/[^a-z0-9_.-]/g, '') || 'czr';
  const offs = [];
  let fs = null;
  let fsPending = null;
  let cwd = [];
  let booted = false;
  let cancelBoot = null;
  let historyIndex = -1;
  let draft = '';

  const history = session.getJSON(
    KEYS.history,
    (value) => Array.isArray(value) && value.every((entry) => typeof entry === 'string'),
    [],
  ).slice(-MAX_HISTORY);

  // -- output ----------------------------------------------------------- //

  function trim() {
    // role="log" plus an unbounded child list is a memory leak with a screen
    // reader attached; keep the transcript finite.
    while (output.childElementCount > MAX_LINES) output.removeChild(output.firstChild);
  }

  function print(text, kind) {
    const line = el('div', {
      class: kind ? 'term-line term-' + kind : 'term-line',
      text: String(text ?? ''),
    });
    output.appendChild(line);
    trim();
    output.scrollTop = output.scrollHeight;
    return line;
  }

  function printAll(lines, kind) {
    for (const line of lines) print(line, kind);
  }

  function promptLabel() {
    return handle + '@czr:' + (cwd.length ? '~/' + cwd.join('/') : '~') + '$';
  }

  function syncPrompt() {
    if (promptNode) promptNode.textContent = promptLabel();
  }

  // -- filesystem ------------------------------------------------------- //

  function validNode(raw) {
    if (!raw || typeof raw !== 'object') return null;
    const name = String(raw.name ?? '').slice(0, 120);
    const url = String(raw.url ?? '');
    if (!name || !safePath(url.split('#')[0] || '/')) return null;
    return {
      name,
      title: String(raw.title ?? name),
      url,
      date: String(raw.date ?? ''),
      size: Number(raw.size) || 0,
      tags: Array.isArray(raw.tags) ? raw.tags.slice(0, 8).map((tag) => String(tag)) : [],
      summary: String(raw.summary ?? ''),
    };
  }

  function prepare(payload) {
    if (!payload || typeof payload !== 'object') return null;
    const dirs = {};
    for (const name of DIRS) {
      const entries = Array.isArray(payload.dirs?.[name]) ? payload.dirs[name] : [];
      dirs[name] = entries.map(validNode).filter(Boolean);
    }
    const langs = Array.isArray(payload.langs) ? payload.langs : [];
    return {
      dirs,
      stats: payload.stats && typeof payload.stats === 'object' ? payload.stats : {},
      langs: langs
        .map((entry) => ({
          code: String(entry?.code ?? '').slice(0, 8),
          url: String(entry?.url ?? ''),
          name: String(entry?.name ?? ''),
        }))
        .filter((entry) => entry.code && safePath(entry.url)),
    };
  }

  /**
   * Fetch the index at most once at a time. A failure is *not* remembered
   * forever: the visitor may simply have been offline for a second, and a
   * terminal that stays broken until reload would be worse than one that
   * retries on the next command.
   */
  function ensureFs() {
    if (fs) return Promise.resolve(fs);
    if (fsPending) return fsPending;
    const url = data?.fsIndex ?? '';
    if (!safePath(url)) return Promise.resolve(null);
    fsPending = fetch(url, { credentials: 'omit' })
      .then((response) => (response.ok ? response.json() : null))
      .then((payload) => prepare(payload))
      .catch(() => null)
      .then((result) => {
        fs = result;
        fsPending = null;
        return result;
      });
    return fsPending;
  }

  function requireFs() {
    if (fs) return true;
    print('filesystem not mounted — fetching, try again in a moment', 'error');
    ensureFs();
    return false;
  }

  /** Resolve a raw path string to a normalised segment array. */
  function resolve(raw) {
    const text = String(raw ?? '');
    const absolute = text.startsWith('/') || text.startsWith('~');
    const parts = absolute ? [] : cwd.slice();
    for (const segment of text.replace(/^~/, '').split('/')) {
      if (!segment || segment === '.') continue;
      if (segment === '..') parts.pop();
      else parts.push(segment);
    }
    return parts.slice(0, 4);
  }

  function findFile(dirName, fileName) {
    const entries = fs?.dirs?.[dirName] ?? [];
    const needle = fileName.toLowerCase();
    return entries.find((node) => node.name.toLowerCase() === needle)
      ?? entries.find((node) => node.name.toLowerCase().replace(/\.md$/, '') === needle.replace(/\.md$/, ''))
      ?? null;
  }

  /** @returns {{kind:'root'}|{kind:'dir',dir:string}|{kind:'file',dir:string,node:object}|null} */
  function lookup(parts) {
    if (parts.length === 0) return { kind: 'root' };
    const [first, second] = parts;
    if (!DIRS.includes(first)) return null;
    if (parts.length === 1) return { kind: 'dir', dir: first };
    const node = findFile(first, second);
    return node ? { kind: 'file', dir: first, node } : null;
  }

  function allFiles() {
    const files = [];
    for (const dir of DIRS) for (const node of fs?.dirs?.[dir] ?? []) files.push({ dir, node });
    return files;
  }

  // -- commands --------------------------------------------------------- //

  const commands = {};

  function define(name, desc, run, usage) {
    commands[name] = { name, desc, run, usage: usage ?? name };
  }

  define('help', 'this list', () => {
    print('comandos disponibles / available commands:', 'dim');
    for (const name of Object.keys(commands).sort()) {
      print('  ' + pad(commands[name].usage, 22) + commands[name].desc);
    }
    print('  tab = completar · ↑↓ = historial · esc = cerrar', 'dim');
  });

  define('ls', 'list a directory', (args) => {
    if (!requireFs()) return;
    const long = args.includes('-l') || args.includes('-la');
    const target = args.find((arg) => !arg.startsWith('-')) ?? '.';
    const place = lookup(resolve(target));
    if (!place) return print('ls: ' + target + ': no such file or directory', 'error');
    if (place.kind === 'file') return print(place.node.name);
    if (place.kind === 'root') {
      for (const dir of DIRS) {
        print('drwxr-xr-x  ' + pad(String((fs.dirs[dir] ?? []).length), 5) + dir + '/');
      }
      return;
    }
    const entries = fs.dirs[place.dir] ?? [];
    if (entries.length === 0) return print('(empty)', 'dim');
    for (const node of entries) {
      if (long) print('-rw-r--r--  ' + pad(node.size + 'w', 8) + pad(node.date.slice(0, 10), 12) + node.name);
      else print(node.name);
    }
  }, 'ls [-l] [dir]');

  define('cd', 'change directory', (args) => {
    if (!requireFs()) return;
    const target = args[0] ?? '~';
    const parts = resolve(target);
    const place = lookup(parts);
    if (!place || place.kind === 'file') return print('cd: ' + target + ': not a directory', 'error');
    cwd = place.kind === 'root' ? [] : [place.dir];
    syncPrompt();
  }, 'cd <dir>');

  define('pwd', 'print working directory', () => print('/' + cwd.join('/')));

  define('cat', 'show a document', (args) => {
    if (!requireFs()) return;
    if (!args[0]) return print('cat: missing operand', 'error');
    const place = lookup(resolve(args[0]));
    if (!place || place.kind !== 'file') return print('cat: ' + args[0] + ': no such file', 'error');
    const node = place.node;
    print('--- ' + node.name + ' ---', 'dim');
    print('title:   ' + node.title);
    if (node.date) print('date:    ' + node.date.slice(0, 10));
    print('words:   ' + node.size);
    if (node.tags.length) print('tags:    ' + node.tags.map((tag) => '#' + tag).join(' '));
    print('url:     ' + node.url);
    if (node.summary) {
      print('');
      printAll(wrap(node.summary, 78));
    }
    print('');
    print('open ' + node.name + '  → leer completo / read in full', 'dim');
  }, 'cat <file>');

  define('open', 'navigate to a document', (args) => {
    if (!requireFs()) return;
    const place = args[0] ? lookup(resolve(args[0])) : null;
    if (!place || place.kind !== 'file') return print('open: ' + (args[0] ?? '') + ': no such file', 'error');
    if (!safePath(place.node.url.split('#')[0])) return print('open: refusing unsafe path', 'error');
    print('→ ' + place.node.url, 'ok');
    location.assign(place.node.url);
  }, 'open <file>');

  define('find', 'find files by name', (args) => {
    if (!requireFs()) return;
    const pattern = args[0];
    if (!pattern) return print('find: missing pattern', 'error');
    const matcher = globToRegExp(pattern);
    if (!matcher) return print('find: bad pattern', 'error');
    let count = 0;
    for (const { dir, node } of allFiles()) {
      if (matcher.test(node.name) || matcher.test(node.title)) {
        print('./' + dir + '/' + node.name);
        count += 1;
      }
      if (count >= 80) break;
    }
    if (count === 0) print('find: nothing matched ' + pattern, 'dim');
  }, 'find <pattern>');

  define('grep', 'search titles and summaries', (args) => {
    if (!requireFs()) return;
    const pattern = args.find((arg) => !arg.startsWith('-'));
    if (!pattern) return print('grep: missing pattern', 'error');
    const needle = pattern.toLowerCase();
    let count = 0;
    for (const { dir, node } of allFiles()) {
      const haystack = (node.title + ' ' + node.summary + ' ' + node.tags.join(' ')).toLowerCase();
      const at = haystack.indexOf(needle);
      if (at === -1) continue;
      const start = Math.max(0, at - 24);
      print(dir + '/' + node.name + ': …' + haystack.slice(start, start + 72) + '…');
      count += 1;
      if (count >= 60) break;
    }
    if (count === 0) print('grep: no matches', 'dim');
  }, 'grep <pattern>');

  define('tree', 'show the whole tree', () => {
    if (!requireFs()) return;
    print('.');
    for (let index = 0; index < DIRS.length; index += 1) {
      const dir = DIRS[index];
      const lastDir = index === DIRS.length - 1;
      print((lastDir ? '`-- ' : '|-- ') + dir + '/');
      const entries = (fs.dirs[dir] ?? []).slice(0, 40);
      entries.forEach((node, position) => {
        const lastFile = position === entries.length - 1;
        print((lastDir ? '    ' : '|   ') + (lastFile ? '`-- ' : '|-- ') + node.name);
      });
      const hidden = (fs.dirs[dir] ?? []).length - entries.length;
      if (hidden > 0) print((lastDir ? '    ' : '|   ') + '... ' + hidden + ' more', 'dim');
    }
  });

  define('whoami', 'who is behind this', () => {
    printAll([
      handle,
      'uid=1000(' + handle + ') gid=1000(research) groups=redteam,reversing,ctf',
      'shell=/bin/curiosity  trackers=0  cookies=0',
    ]);
  });

  define('date', 'current date and time', () => {
    const now = new Date();
    print(now.toISOString());
    try {
      print(now.toLocaleString(data?.lang === 'en' ? 'en-US' : 'es-ES'));
    } catch {
      /* Intl data missing: the ISO line is enough */
    }
  });

  define('history', 'command history', () => {
    if (history.length === 0) return print('(empty)', 'dim');
    history.forEach((entry, index) => print('  ' + pad(String(index + 1), 5) + entry));
  });

  define('clear', 'clear the screen', () => clear(output));

  define('banner', 'print the banner', () => printAll(banner(handle, 'terminal'), 'accent'));

  define('theme', 'switch theme', (args) => {
    const themes = themeList();
    if (!args[0]) {
      print('themes: ' + themes.join(' '), 'dim');
      return print('current: ' + currentTheme());
    }
    const applied = applyTheme(args[0].toLowerCase());
    if (applied) print('theme → ' + applied, 'ok');
    else print('theme: unknown theme ' + args[0] + ' (try: ' + themes.join(', ') + ')', 'error');
  }, 'theme [name]');

  define('lang', 'switch language', (args) => {
    const langs = fs?.langs ?? [];
    if (!args[0]) {
      if (langs.length === 0) return print('lang: filesystem not mounted', 'error');
      for (const entry of langs) print('  ' + pad(entry.code, 6) + entry.name + '  ' + entry.url);
      return;
    }
    const wanted = args[0].toLowerCase().slice(0, 8);
    const match = langs.find((entry) => entry.code.toLowerCase() === wanted);
    if (!match) return print('lang: unknown language ' + args[0], 'error');
    print('→ ' + match.url, 'ok');
    location.assign(match.url);
  }, 'lang [code]');

  define('matrix', 'toggle the rain', async (args) => {
    const mode = (args[0] ?? '').toLowerCase();
    try {
      const module = await import('./matrix.js');
      if (mode === 'off') {
        module.stop();
        return print('matrix: off', 'ok');
      }
      if (!module.eligible()) return print('matrix: declined (small viewport or low-power device)', 'dim');
      const started = module.start();
      print(started ? 'matrix: on' : 'matrix: static frame only (reduced motion)', started ? 'ok' : 'dim');
    } catch {
      print('matrix: module unavailable', 'error');
    }
  }, 'matrix [on|off]');

  define('stats', 'site statistics', () => {
    if (!requireFs()) return;
    const stats = fs.stats ?? {};
    for (const key of ['posts', 'writeups', 'tools', 'tags', 'words']) {
      if (stats[key] !== undefined) print('  ' + pad(key, 10) + String(stats[key]));
    }
  });

  define('echo', 'print arguments', (args) => print(args.join(' ')));

  define('exit', 'close the terminal', () => {
    print('logout', 'dim');
    setTimeout(() => modal.close(), 140);
  });

  // Easter eggs. Neither does anything, which is the joke.
  define('sudo', 'nice try', (args) => {
    printAll([
      handle + ' is not in the sudoers file.',
      'This incident has been logged to /dev/null.',
    ], 'error');
    if (args.length) print('(' + args.join(' ') + ' — denied)', 'dim');
  });

  define('rm', 'refuse to delete things', (args) => {
    const joined = args.join(' ');
    if (/-{1,2}[rf]{1,2}f?\s*\/?$/.test(joined) || joined.includes('-rf /')) {
      printAll([
        'rm: descending into /',
        'rm: removing /dev/null ... failed (already empty)',
        'rm: removing /var/log/hubris ... 0 bytes freed',
        'rm: it is a static site. There is nothing here to delete.',
      ], 'dim');
      return;
    }
    print('rm: read-only filesystem', 'error');
  });

  define('uname', 'system info', () => print('czrxplo1t-ssg static ' + (data?.lang ?? 'es') + ' javascript/esm'));

  // -- word wrap -------------------------------------------------------- //

  function wrap(text, width) {
    const words = String(text ?? '').split(/\s+/).filter(Boolean);
    const lines = [];
    let line = '';
    for (const word of words) {
      if (line.length + word.length + 1 > width) {
        if (line) lines.push(line);
        line = word;
      } else {
        line = line ? line + ' ' + word : word;
      }
    }
    if (line) lines.push(line);
    return lines.slice(0, 20);
  }

  // -- execution -------------------------------------------------------- //

  async function execute(raw) {
    const line = String(raw ?? '').slice(0, 400);
    print(promptLabel() + ' ' + line, 'echo');
    const trimmed = line.trim();
    if (!trimmed) return;

    remember(trimmed);
    const args = parseArgs(trimmed);
    const name = (args.shift() ?? '').toLowerCase();
    const command = Object.prototype.hasOwnProperty.call(commands, name) ? commands[name] : null;

    if (!command) {
      print(name + ': command not found', 'error');
      const near = Object.keys(commands)
        .map((key) => [key, distance(key, name)])
        .filter(([, score]) => score <= 2)
        .sort((left, right) => left[1] - right[1])[0];
      if (near) print('did you mean: ' + near[0] + ' ?', 'dim');
      else print("type 'help' for the command list", 'dim');
      return;
    }

    try {
      await command.run(args);
    } catch (error) {
      // A broken command prints an error; it does not take the terminal down.
      print('internal error in ' + name, 'error');
      if (typeof console !== 'undefined') console.error(error);
    }
  }

  function remember(entry) {
    if (history[history.length - 1] !== entry) {
      history.push(entry);
      while (history.length > MAX_HISTORY) history.shift();
      session.setJSON(KEYS.history, history);
    }
    historyIndex = -1;
    draft = '';
  }

  // -- completion ------------------------------------------------------- //

  function completions(text) {
    const parts = parseArgs(text);
    const trailingSpace = /\s$/.test(text);
    if (parts.length === 0 || (parts.length === 1 && !trailingSpace)) {
      const prefix = (parts[0] ?? '').toLowerCase();
      return { prefix, matches: Object.keys(commands).filter((name) => name.startsWith(prefix)).sort() };
    }
    const prefix = trailingSpace ? '' : (parts[parts.length - 1] ?? '');
    const parent = prefix.includes('/') ? prefix.slice(0, prefix.lastIndexOf('/') + 1) : '';
    const leaf = prefix.slice(parent.length).toLowerCase();
    const place = lookup(resolve(parent || '.'));
    const names = [];
    if (place?.kind === 'root') names.push(...DIRS.map((dir) => dir + '/'));
    else if (place?.kind === 'dir') names.push(...(fs?.dirs?.[place.dir] ?? []).map((node) => node.name));
    return { prefix, parent, matches: names.filter((name) => name.toLowerCase().startsWith(leaf)).sort() };
  }

  function commonPrefix(values) {
    if (values.length === 0) return '';
    let result = values[0];
    for (const value of values.slice(1)) {
      let index = 0;
      while (index < result.length && index < value.length && result[index].toLowerCase() === value[index].toLowerCase()) index += 1;
      result = result.slice(0, index);
    }
    return result;
  }

  function complete() {
    const text = input.value;
    const { prefix, parent, matches } = completions(text);
    if (matches.length === 0) return;
    const shared = matches.length === 1 ? matches[0] : commonPrefix(matches);
    // parseArgs() has already removed the quotes, so the offset arithmetic
    // below would corrupt a quoted argument. List the candidates instead.
    if (shared && !/["'\\]/.test(text)) {
      const head = text.slice(0, text.length - prefix.length);
      const suffix = matches.length === 1 && !shared.endsWith('/') ? ' ' : '';
      input.value = head + (parent ?? '') + shared + suffix;
    }
    if (matches.length > 1) {
      print(promptLabel() + ' ' + text, 'echo');
      printAll([matches.slice(0, 40).join('  ')], 'dim');
    }
  }

  // -- history keys ----------------------------------------------------- //

  function recall(direction) {
    if (history.length === 0) return;
    if (historyIndex === -1) {
      draft = input.value;
      historyIndex = history.length;
    }
    historyIndex = Math.min(history.length, Math.max(0, historyIndex + direction));
    input.value = historyIndex >= history.length ? draft : history[historyIndex];
    // Caret to the end, so up-arrow behaves like a real shell.
    requestAnimationFrame(() => input.setSelectionRange(input.value.length, input.value.length));
  }

  // -- opening ---------------------------------------------------------- //

  function greet() {
    printAll(banner(handle, 'terminal'), 'accent');
    print(qs('#term-hint')?.textContent?.trim() || "type 'help'", 'dim');
    print('');
  }

  const modal = createModal(root, {
    initialFocus: () => input,
    onOpen() {
      fitToViewport();
      if (!booted) {
        booted = true;
        const mounting = print('mounting /fs …', 'dim');
        // The boot log quotes real document counts, so it waits for the index —
        // but only for the index, and it degrades to a plain banner if the
        // fetch fails rather than leaving an empty panel.
        ensureFs().then((mounted) => {
          mounting.remove();
          if (!mounted) print('warning: /fs unavailable — ls, cat and find are offline', 'error');
          if (mounted && shouldBoot()) {
            cancelBoot = runBoot((text, kind) => print(text, kind), {
              stats: mounted.stats,
              onDone: () => {
                cancelBoot = null;
                greet();
              },
            });
          } else {
            greet();
          }
        });
      }
      syncPrompt();
      output.scrollTop = output.scrollHeight;
    },
    onClose() {
      cancelBoot?.();
      cancelBoot = null;
    },
  });

  /**
   * The on-screen keyboard shrinks the *visual* viewport, not the layout
   * viewport, so a panel sized in vh ends up half-covered on a phone. The
   * custom property lets CSS use the real available height.
   */
  function fitToViewport() {
    const viewport = window.visualViewport;
    const height = viewport ? viewport.height : window.innerHeight;
    root.style.setProperty('--term-vh', Math.round(height) + 'px');
    const panel = root.querySelector('.term-panel');
    if (panel) {
      // A gap of this size between the visual and layout viewports means the
      // keyboard is up; the panel's vh-based height would then sit underneath it.
      const keyboardUp = height < window.innerHeight - 80;
      panel.style.maxHeight = keyboardUp ? Math.round(height - 16) + 'px' : '';
    }
    output.scrollTop = output.scrollHeight;
  }

  // 16px is the threshold below which iOS Safari zooms the page on focus; if
  // the stylesheet ever sets something smaller, override it here rather than
  // trapping the reader in a zoomed viewport.
  function guardFontSize() {
    const size = Number.parseFloat(getComputedStyle(input).fontSize || '16');
    if (Number.isFinite(size) && size < 16) input.style.fontSize = '16px';
  }

  offs.push(on(form, 'submit', (event) => {
    event.preventDefault();
    const value = input.value;
    input.value = '';
    cancelBoot?.();
    cancelBoot = null;
    execute(value);
  }));

  offs.push(on(input, 'keydown', (event) => {
    if (event.key === 'Tab') {
      event.preventDefault();
      complete();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      recall(-1);
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      recall(1);
    } else if (event.key === 'l' && event.ctrlKey) {
      event.preventDefault();
      clear(output);
    } else if (event.key === 'c' && event.ctrlKey && input.selectionStart === input.selectionEnd) {
      event.preventDefault();
      print(promptLabel() + ' ' + input.value + '^C', 'echo');
      input.value = '';
    }
  }));

  // Tapping anywhere in the transcript should put the caret back in the input,
  // as it would in a real terminal — but not when text is being selected.
  offs.push(on(output, 'click', () => {
    if ((window.getSelection?.()?.toString() ?? '') === '') input.focus({ preventScroll: true });
  }));

  if (window.visualViewport) {
    offs.push(on(window.visualViewport, 'resize', fitToViewport, { passive: true }));
    offs.push(on(window.visualViewport, 'scroll', fitToViewport, { passive: true }));
  } else {
    offs.push(on(window, 'resize', fitToViewport, { passive: true }));
  }

  guardFontSize();
  syncPrompt();

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
    run: (line) => execute(line),
    destroy() {
      cancelBoot?.();
      while (offs.length) offs.pop()();
      modal.destroy();
      if (hooks.onDestroy) hooks.onDestroy();
    },
  };
}
