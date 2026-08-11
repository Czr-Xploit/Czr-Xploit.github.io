/**
 * Shared modal-dialog behaviour for the palette and the terminal.
 *
 * The two share enough (focus trap, focus restore, Escape, backdrop, page
 * inerting, scroll lock) that duplicating it would guarantee they drift apart
 * — and the half that drifts is always the accessibility half.
 */

import { qsa, on } from './dom.js';

const FOCUSABLE = [
  'a[href]',
  'button:not([disabled])',
  'input:not([disabled]):not([type="hidden"])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

const SUPPORTS_INERT = typeof HTMLElement !== 'undefined' && 'inert' in HTMLElement.prototype;

// Scroll lock is a class the stylesheet owns (`body.is-locked`), and it is
// reference-counted: if two dialogs are ever open at once, the first one to
// close must not unlock the page under the second.
let lockCount = 0;

function lock() {
  lockCount += 1;
  document.body.classList.add('is-locked');
}

function unlock() {
  lockCount = Math.max(0, lockCount - 1);
  if (lockCount === 0) document.body.classList.remove('is-locked');
}

function visible(node) {
  return node.offsetWidth > 0 || node.offsetHeight > 0 || node.getClientRects().length > 0;
}

/**
 * @param {HTMLElement} root the outermost element of the dialog (the one with `hidden`)
 * @param {{panel?: string, initialFocus?: () => HTMLElement|null, onOpen?: Function, onClose?: Function}} options
 */
export function createModal(root, options = {}) {
  const offs = [];
  let open = false;
  let restoreTo = null;
  let hidden = [];

  function focusables() {
    return qsa(FOCUSABLE, root).filter(visible);
  }

  function inertRest() {
    hidden = [];
    for (const node of Array.from(document.body.children)) {
      if (node === root || node.contains(root) || node.id === 'toast') continue;
      if (SUPPORTS_INERT) {
        if (node.inert) continue;
        node.inert = true;
        hidden.push([node, 'inert', null]);
      } else {
        hidden.push([node, 'aria-hidden', node.getAttribute('aria-hidden')]);
        node.setAttribute('aria-hidden', 'true');
      }
    }
  }

  function releaseRest() {
    for (const [node, kind, previous] of hidden) {
      if (kind === 'inert') node.inert = false;
      else if (previous === null) node.removeAttribute('aria-hidden');
      else node.setAttribute('aria-hidden', previous);
    }
    hidden = [];
  }

  function onKeydown(event) {
    if (event.key === 'Escape') {
      event.stopPropagation();
      api.close();
      return;
    }
    if (event.key !== 'Tab') return;
    const items = focusables();
    if (items.length === 0) {
      event.preventDefault();
      return;
    }
    const first = items[0];
    const last = items[items.length - 1];
    const active = document.activeElement;
    // Wrapping by hand is what keeps the tab ring inside the dialog; the
    // browser has no idea this element is modal beyond aria-modal, which is
    // advisory only.
    if (event.shiftKey && (active === first || !root.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }

  function onPointer(event) {
    const target = event.target;
    if (target === root || (target instanceof Element && target.closest('[data-action^="close-"]'))) {
      event.preventDefault();
      api.close();
    }
  }

  const api = {
    isOpen: () => open,

    open(trigger) {
      if (open) return;
      open = true;
      // Remember the *element*, not just "the button": the palette can be
      // opened from a keyboard shortcut with focus anywhere on the page, and
      // dumping focus on <body> afterwards loses the reader's place.
      restoreTo = trigger instanceof HTMLElement ? trigger
        : (document.activeElement instanceof HTMLElement ? document.activeElement : null);
      root.hidden = false;
      root.classList.add('is-open');
      lock();
      inertRest();
      const target = options.initialFocus?.() ?? focusables()[0] ?? null;
      target?.focus({ preventScroll: true });
      options.onOpen?.();
    },

    close() {
      if (!open) return;
      open = false;
      root.classList.remove('is-open');
      root.hidden = true;
      unlock();
      releaseRest();
      options.onClose?.();
      if (restoreTo && restoreTo.isConnected) restoreTo.focus({ preventScroll: true });
      restoreTo = null;
    },

    toggle(trigger) {
      if (open) api.close();
      else api.open(trigger);
    },

    destroy() {
      api.close();
      while (offs.length) offs.pop()();
    },
  };

  offs.push(on(root, 'keydown', onKeydown));
  offs.push(on(root, 'mousedown', onPointer));
  return api;
}
