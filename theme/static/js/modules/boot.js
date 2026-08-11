/**
 * First-visit boot sequence for the in-page terminal.
 *
 * It runs *inside* the terminal the first time a visitor opens it, not on page
 * load: a splash screen that steals focus and delays content is a cost the
 * reader did not agree to. Under reduced motion the whole thing is skipped and
 * the banner is printed at once — a slow fake boot log is exactly the sort of
 * thing that makes people motion-sick or impatient.
 */

import { local, KEYS } from './store.js';
import { motionOK } from './motion.js';

const LINE_MS = 110;

/** The banner, also used by the terminal's `banner` command. */
export function banner(handle, tagline) {
  const name = (handle ?? 'czrxplo1t').slice(0, 24);
  const subtitle = (tagline ?? 'offensive research terminal').slice(0, 44);
  const width = Math.max(name.length + subtitle.length + 7, 46);
  const rule = '+' + '-'.repeat(width) + '+';
  const pad = (text) => '| ' + text + ' '.repeat(Math.max(0, width - text.length - 2)) + ' |';
  return [
    rule,
    pad(name + ' :: ' + subtitle),
    rule,
  ];
}

/** Only ever true once per browser profile. */
export function shouldRun() {
  return motionOK() && !local.flag(KEYS.booted);
}

export function markDone() {
  local.setFlag(KEYS.booted);
}

function lines(stats) {
  const counts = stats ?? {};
  const number = (value) => (Number.isFinite(value) ? String(value) : '?');
  return [
    ['dim', 'czr-bios 2.1 :: initialising session'],
    ['ok', 'mount /blog        ' + number(counts.posts) + ' documents'],
    ['ok', 'mount /writeups    ' + number(counts.writeups) + ' documents'],
    ['ok', 'mount /arsenal     ' + number(counts.tools) + ' entries'],
    ['ok', 'index ' + number(counts.words) + ' words'],
    ['ok', 'trackers detected  0'],
    ['ok', 'cookies set        0'],
    ['warn', 'operator caffeine  low'],
    ['dim', 'session ready'],
  ];
}

/**
 * @param {(text: string, kind?: string) => void} write
 * @param {{stats?: object, onDone?: () => void}} [options]
 * @returns {() => void} cancel; safe to call at any point
 */
export function run(write, options = {}) {
  const queue = lines(options.stats);
  let index = 0;
  let timer = 0;
  let cancelled = false;

  const step = () => {
    if (cancelled) return;
    if (index >= queue.length) {
      markDone();
      options.onDone?.();
      return;
    }
    const [kind, text] = queue[index];
    index += 1;
    write(kind === 'ok' ? '[  OK  ] ' + text : kind === 'warn' ? '[ WARN ] ' + text : text, kind);
    timer = setTimeout(step, LINE_MS);
  };

  timer = setTimeout(step, LINE_MS);

  return () => {
    cancelled = true;
    clearTimeout(timer);
    // Skipping still counts as having seen it; nobody wants the boot log twice.
    markDone();
  };
}
