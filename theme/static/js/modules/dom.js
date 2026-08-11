/**
 * DOM helpers.
 *
 * `el()` is the only element factory used anywhere in this codebase. Nothing
 * here — and nothing that imports this — ever touches innerHTML: the search
 * index, the terminal echo and the filter counters all carry text the author
 * (or the visitor) typed, and string-concatenated markup is how that turns
 * into script execution. Building real nodes and assigning textContent makes
 * that class of bug unrepresentable rather than merely avoided.
 */

const ATTR_ONLY = /^(?:aria-|data-|role$|xmlns)/;

/**
 * el('a', { class: 'x', href: '/', text: 'hi' })
 * el('li', { 'aria-selected': 'true' }, [node, 'text'])
 *
 * `props.text` sets textContent. There is deliberately no `html` option.
 */
export function el(tag, props, children) {
  const node = document.createElement(tag);
  if (props) {
    for (const key of Object.keys(props)) {
      const value = props[key];
      if (value === null || value === undefined || value === false) continue;
      if (key === 'class') node.className = value;
      else if (key === 'text') node.textContent = String(value);
      else if (key === 'on') {
        for (const type of Object.keys(value)) node.addEventListener(type, value[type]);
      } else if (key === 'dataset') {
        for (const name of Object.keys(value)) node.dataset[name] = String(value[name]);
      } else if (ATTR_ONLY.test(key) || key.includes('-')) {
        node.setAttribute(key, value === true ? '' : String(value));
      } else if (key in node) {
        node[key] = value;
      } else {
        node.setAttribute(key, String(value));
      }
    }
  }
  if (children !== null && children !== undefined) append(node, children);
  return node;
}

/** Append a node, a string, or an array of either. Strings become text nodes. */
export function append(parent, children) {
  const list = Array.isArray(children) ? children : [children];
  for (const child of list) {
    if (child === null || child === undefined || child === false) continue;
    if (Array.isArray(child)) append(parent, child);
    else parent.appendChild(typeof child === 'string' || typeof child === 'number'
      ? document.createTextNode(String(child))
      : child);
  }
  return parent;
}

export function frag(children) {
  return append(document.createDocumentFragment(), children ?? []);
}

export function qs(selector, root) {
  return (root ?? document).querySelector(selector);
}

export function qsa(selector, root) {
  return Array.from((root ?? document).querySelectorAll(selector));
}

/** Remove every child without going through innerHTML = ''. */
export function clear(node) {
  while (node && node.firstChild) node.removeChild(node.firstChild);
  return node;
}

/** addEventListener that hands back its own remover, so destroy() stays honest. */
export function on(target, type, handler, options) {
  if (!target) return () => {};
  target.addEventListener(type, handler, options);
  return () => target.removeEventListener(type, handler, options);
}

export function debounce(fn, wait) {
  let timer = 0;
  const wrapped = (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
  wrapped.cancel = () => clearTimeout(timer);
  return wrapped;
}

/**
 * Is this a path we are willing to hand to location.assign() or <link
 * rel=prefetch>? Route strings reach us from JSON, the hash and localStorage,
 * so "starts with a slash" is not enough: `//evil.tld` is a protocol-relative
 * absolute URL and `\` is normalised to `/` by some parsers.
 */
export function safePath(value) {
  if (typeof value !== 'string' || value.length === 0 || value.length > 512) return false;
  if (value[0] !== '/' || value[1] === '/' || value[1] === '\\') return false;
  // Control characters and backslashes are normalised in ways that can turn a
  // "relative"-looking string into something else once a URL parser sees it.
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    if (code < 0x21 || code === 0x7f || code === 0x5c) return false;
  }
  return true;
}

/** True for same-origin http(s) links we may prefetch or intercept. */
export function sameOrigin(url) {
  try {
    const parsed = new URL(url, location.href);
    return parsed.origin === location.origin && /^https?:$/.test(parsed.protocol);
  } catch {
    return false;
  }
}

/** requestIdleCallback where it exists, a timeout where it does not. */
export function idle(fn, timeout = 1200) {
  if (typeof requestIdleCallback === 'function') return requestIdleCallback(fn, { timeout });
  return setTimeout(fn, 1);
}
