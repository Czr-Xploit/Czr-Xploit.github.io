/**
 * One answer to "may I animate?", shared by every module that moves pixels.
 *
 * Two inputs: the OS-level `prefers-reduced-motion` query and the site's own
 * `data-motion` attribute (set before first paint by theme-boot.js, toggled at
 * runtime here). The media query is *subscribed to*, not sampled once — a
 * visitor who turns reduction on mid-session should see the matrix rain settle
 * on its next frame, not on their next navigation.
 */

import { local, KEYS } from './store.js';

const root = document.documentElement;
const query = typeof matchMedia === 'function' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
const listeners = new Set();

let systemReduced = query ? query.matches : false;

function siteOff() {
  return root.getAttribute('data-motion') === 'off';
}

/** True when animation is welcome. */
export function motionOK() {
  return !systemReduced && !siteOff();
}

/** Subscribe to changes; returns an unsubscribe function. */
export function onMotionChange(handler) {
  listeners.add(handler);
  return () => listeners.delete(handler);
}

function announce() {
  const value = motionOK();
  for (const handler of Array.from(listeners)) {
    try {
      handler(value);
    } catch {
      listeners.delete(handler);
    }
  }
}

/** Persisted site-level override. `on` is a boolean. */
export function setMotion(on) {
  root.setAttribute('data-motion', on ? 'on' : 'off');
  local.set(KEYS.motion, on ? 'on' : 'off');
  announce();
  return motionOK();
}

export function toggleMotion() {
  return setMotion(siteOff());
}

if (query) {
  const handler = (event) => {
    systemReduced = event.matches;
    announce();
  };
  // Safari only grew addEventListener on MediaQueryList in 14; the deprecated
  // addListener is the graceful fallback rather than a hard failure.
  if (typeof query.addEventListener === 'function') query.addEventListener('change', handler);
  else if (typeof query.addListener === 'function') query.addListener(handler);
}
