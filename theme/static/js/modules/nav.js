/**
 * Header navigation, prefetch-on-intent and the toast notifier.
 *
 * The mobile menu is progressive: the markup is a plain <nav> that is visible
 * and usable with no JavaScript at all, so everything here is about the
 * collapsed state and its aria wiring.
 */

import { qs, on, sameOrigin } from './dom.js';

const PREFETCH_DELAY = 120;
const PREFETCH_MAX = 4;

const prefetched = new Set();
let inFlight = 0;
let toastTimer = 0;

/** Cheap connection check: never spend a visitor's data plan on a guess. */
function prefetchAllowed() {
  const connection = navigator.connection ?? navigator.mozConnection ?? navigator.webkitConnection;
  if (!connection) return true;
  if (connection.saveData) return false;
  return !/^(?:slow-)?2g$/.test(connection.effectiveType ?? '');
}

function prefetch(href) {
  if (!prefetchAllowed() || inFlight >= PREFETCH_MAX) return;
  let url;
  try {
    url = new URL(href, location.href);
  } catch {
    return;
  }
  url.hash = '';
  const key = url.href;
  if (prefetched.has(key) || key === location.href.split('#')[0]) return;
  prefetched.add(key);
  inFlight += 1;
  const link = document.createElement('link');
  link.rel = 'prefetch';
  link.as = 'document';
  link.href = key;
  // Not every browser fires load/error for a prefetch, and a slot that is never
  // released would silently disable prefetching for the rest of the visit.
  let released = false;
  const release = () => {
    if (released) return;
    released = true;
    inFlight -= 1;
  };
  link.addEventListener('load', release);
  link.addEventListener('error', release);
  setTimeout(release, 5000);
  document.head.appendChild(link);
}

function candidate(target) {
  const link = target instanceof Element ? target.closest('a[href]') : null;
  if (!link) return null;
  const href = link.getAttribute('href') ?? '';
  if (!href || href.startsWith('#') || link.hasAttribute('download') || link.target === '_blank') return null;
  if (!sameOrigin(link.href)) return null;
  // Feeds, JSON and other non-document endpoints are not worth a document
  // prefetch and would pollute the cache.
  if (/\.(?:xml|json|txt|asc|zip|png|jpe?g|gif|webp|svg|pdf)$/i.test(new URL(link.href).pathname)) return null;
  return link.href;
}

/**
 * Show a transient message in the shared #toast live region.
 *
 * The region already carries role="status" aria-live="polite" in the markup, so
 * replacing its text is enough to have it announced. The stylesheet treats
 * `:empty` as the hidden state and `.is-hidden` as the fade-out, so this
 * fades first and empties afterwards — clearing the text immediately would
 * make some screen readers announce the removal as a second change.
 */
export function toast(message, timeout = 2600) {
  const node = qs('#toast');
  if (!node || typeof message !== 'string' || !message) return;
  clearTimeout(toastTimer);
  node.classList.remove('is-hidden');
  node.textContent = message;
  toastTimer = setTimeout(() => {
    node.classList.add('is-hidden');
    toastTimer = setTimeout(() => {
      node.textContent = '';
      node.classList.remove('is-hidden');
    }, 400);
  }, timeout);
}

export function init(data) {
  const offs = [];
  const toggle = qs('[data-action="toggle-nav"]');
  const nav = qs('#primary-nav');
  const strings = data?.strings ?? {};

  function setNav(open) {
    if (!toggle || !nav) return;
    // The stylesheet opens the menu from either signal (`.nav.is-open` or the
    // sibling selector on aria-expanded); both are set so neither is load-bearing.
    toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    nav.classList.toggle('is-open', open);
    const label = open ? strings.menuClose : strings.menuOpen;
    if (typeof label === 'string' && label) toggle.setAttribute('aria-label', label);
  }

  if (toggle && nav) {
    offs.push(on(toggle, 'click', () => {
      setNav(toggle.getAttribute('aria-expanded') !== 'true');
    }));
    offs.push(on(nav, 'click', (event) => {
      if (event.target instanceof Element && event.target.closest('a')) setNav(false);
    }));
    offs.push(on(document, 'keydown', (event) => {
      if (event.key === 'Escape' && toggle.getAttribute('aria-expanded') === 'true') {
        setNav(false);
        toggle.focus();
      }
    }));
    offs.push(on(document, 'click', (event) => {
      if (toggle.getAttribute('aria-expanded') !== 'true') return;
      const target = event.target;
      if (target instanceof Node && !nav.contains(target) && !toggle.contains(target)) setNav(false);
    }));
  }

  // Prefetch on intent. mouseenter is delayed because a pointer crossing the
  // header sweeps every link in it; touchstart is not, because a tap is a
  // commitment. Both listeners are passive: neither ever calls preventDefault.
  let hoverTimer = 0;
  offs.push(on(document, 'mouseover', (event) => {
    const href = candidate(event.target);
    if (!href) return;
    clearTimeout(hoverTimer);
    hoverTimer = setTimeout(() => prefetch(href), PREFETCH_DELAY);
  }, { passive: true }));
  offs.push(on(document, 'mouseout', () => clearTimeout(hoverTimer), { passive: true }));
  offs.push(on(document, 'touchstart', (event) => {
    const href = candidate(event.target);
    if (href) prefetch(href);
  }, { passive: true }));
  offs.push(on(document, 'focusin', (event) => {
    const href = candidate(event.target);
    if (href) prefetch(href);
  }));

  return {
    setNav,
    destroy() {
      clearTimeout(hoverTimer);
      while (offs.length) offs.pop()();
    },
  };
}
