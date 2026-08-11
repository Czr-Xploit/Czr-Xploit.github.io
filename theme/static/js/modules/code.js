/**
 * Copy-to-clipboard for code blocks and for the current page URL.
 *
 * The buttons are emitted by the Markdown renderer, so they exist with
 * JavaScript disabled; they simply do nothing, which is why they carry no
 * "click me" affordance beyond a label. Success is announced through the
 * polite toast region as well as shown on the button, because a colour change
 * is invisible to a screen reader and to anyone not looking at that corner.
 */

import { on } from './dom.js';
import { toast } from './nav.js';

// The renderer emits U+200B in otherwise-empty code lines so they keep their
// height; it must not travel to the clipboard. Built from a char code so the
// source stays readable rather than containing an invisible character.
const ZERO_WIDTH = new RegExp(String.fromCharCode(0x200b), 'g');
const RESET_AFTER = 1800;

async function write(text) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Denied permission or a non-secure context: fall through to selection.
    }
  }
  return false;
}

/** Last resort: select the text so Ctrl+C works, and say so. */
function selectNode(node) {
  const selection = window.getSelection?.();
  if (!selection || !node) return false;
  const range = document.createRange();
  range.selectNodeContents(node);
  selection.removeAllRanges();
  selection.addRange(range);
  return true;
}

function flash(button, label) {
  const target = button.querySelector('.code-copy-label') ?? button;
  if (target.dataset.original === undefined) target.dataset.original = target.textContent ?? '';
  target.textContent = label;
  button.classList.add('is-copied');
  clearTimeout(Number(button.dataset.timer ?? 0));
  button.dataset.timer = String(setTimeout(() => {
    target.textContent = target.dataset.original ?? '';
    button.classList.remove('is-copied');
  }, RESET_AFTER));
}

export function init(data) {
  const strings = data?.strings ?? {};
  const done = typeof strings.copied === 'string' ? strings.copied : 'copied';

  const off = on(document, 'click', async (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;

    const copyCode = target.closest('[data-action="copy-code"]');
    if (copyCode) {
      const source = copyCode.closest('.code-block, figure')?.querySelector('pre code');
      if (!source) return;
      const text = (source.textContent ?? '').replace(ZERO_WIDTH, '');
      if (await write(text)) {
        flash(copyCode, done);
        toast(done);
      } else if (selectNode(source)) {
        toast('Ctrl+C / ⌘C');
      }
      return;
    }

    const copyLink = target.closest('[data-action="copy-link"]');
    if (copyLink) {
      // location.href, not anything from the page: no user-controlled string
      // reaches the clipboard through this path.
      if (await write(location.href)) {
        flash(copyLink, done);
        toast(done);
      } else {
        toast(location.href);
      }
    }
  });

  return { destroy: off };
}
