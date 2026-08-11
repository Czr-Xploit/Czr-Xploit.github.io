/**
 * Theme cycling and persistence.
 *
 * theme-boot.js already applied the stored theme before first paint; this
 * module only handles changes made during the session. The list of legal
 * themes comes from the build (via #site-data) and is filtered again here,
 * because it arrives as JSON and JSON is input.
 */

import { local, KEYS } from './store.js';

const NAME = /^[a-z][a-z0-9-]{1,15}$/;
const root = document.documentElement;

let themes = ['phosphor'];

export function init(data) {
  const list = Array.isArray(data?.themes) ? data.themes.filter((name) => NAME.test(name)) : [];
  if (list.length) themes = list;
  const active = current();
  if (!themes.includes(active) && themes.length) apply(themes[0]);
  return { current, cycle, apply, list: () => themes.slice() };
}

export function current() {
  return root.getAttribute('data-theme') || themes[0];
}

/** Apply a theme by name. Returns the name actually applied, or null. */
export function apply(name) {
  if (typeof name !== 'string' || !themes.includes(name)) return null;
  root.setAttribute('data-theme', name);
  local.set(KEYS.theme, name);
  // Keep the browser UI colour in step with the palette where the meta tag
  // exists; the value is read from the page's own computed style, never from
  // anything a visitor supplied.
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) {
    const background = getComputedStyle(root).getPropertyValue('--bg').trim();
    if (/^#[0-9a-fA-F]{3,8}$/.test(background)) meta.setAttribute('content', background);
  }
  return name;
}

export function cycle() {
  const index = themes.indexOf(current());
  return apply(themes[(index + 1) % themes.length]);
}

export function list() {
  return themes.slice();
}
