/**
 * Service worker source. The build fills in the two placeholder tokens in the
 * VERSION and PRECACHE constants below — a build timestamp and a JSON array of
 * versioned asset URLs — and writes the result to /sw.js. See
 * _build_root_files() in tools/ssg/builder.py.
 *
 * The tokens are not named in this comment on purpose: the substitution is a
 * plain string replace over the whole file, so spelling them here would paste
 * the entire precache list into the prose.
 *
 * Design notes:
 *  - The cache name contains the build version, so a deploy invalidates
 *    everything at once and there is no partial-upgrade state to reason about.
 *  - Precached URLs carry ?v= hashes while page requests do not, so every
 *    lookup uses ignoreSearch. Without it the precache would never be hit.
 *  - Only same-origin GETs are touched. Anything else falls through to the
 *    network untouched, which keeps this worker out of the way of everything it
 *    has no business caching.
 *  - Nothing here is required for the site to work: on the first visit, with a
 *    failed install, or in a browser without service workers, the pages are
 *    plain static documents served normally.
 */

const VERSION = '__VERSION__';
const PRECACHE = __PRECACHE__;
const CACHE = 'czr-' + VERSION;
const RUNTIME_MAX = 64;
const OFFLINE_FALLBACK = '/404.html';

const PRECACHE_URLS = Array.isArray(PRECACHE) ? PRECACHE : [];

self.addEventListener('install', (event) => {
  event.waitUntil((async () => {
    const cache = await caches.open(CACHE);
    // One bad URL must not fail the whole install, so each entry is added on
    // its own and failures are tolerated.
    await Promise.all(PRECACHE_URLS.map((url) => cache.add(new Request(url, { cache: 'reload' })).catch(() => null)));
    await cache.add(new Request(OFFLINE_FALLBACK, { cache: 'reload' })).catch(() => null);
    await self.skipWaiting();
  })());
});

self.addEventListener('activate', (event) => {
  event.waitUntil((async () => {
    const names = await caches.keys();
    await Promise.all(names.filter((name) => name !== CACHE && name.startsWith('czr-')).map((name) => caches.delete(name)));
    await self.clients.claim();
  })());
});

self.addEventListener('message', (event) => {
  if (event.data === 'SKIP_WAITING') self.skipWaiting();
});

function cacheable(response) {
  return Boolean(response) && response.status === 200 && response.type !== 'opaque'
    && (response.type === 'basic' || response.type === 'default');
}

async function put(request, response) {
  if (!cacheable(response)) return;
  try {
    const cache = await caches.open(CACHE);
    await cache.put(request, response.clone());
    trim(cache);
  } catch {
    /* Quota or a partial response: not worth failing the fetch over. */
  }
}

/** Keep the runtime cache from growing without bound on a large site. */
async function trim(cache) {
  const keys = await cache.keys();
  const overflow = keys.length - (PRECACHE_URLS.length + RUNTIME_MAX);
  for (let index = 0; index < overflow; index += 1) {
    // Never evict a precached shell entry.
    const key = keys[index];
    if (!PRECACHE_URLS.some((url) => key.url.endsWith(url.split('?')[0]))) await cache.delete(key);
  }
}

async function fromCache(request) {
  const cache = await caches.open(CACHE);
  return cache.match(request, { ignoreSearch: true });
}

/** Static assets: serve instantly, refresh in the background. */
async function staleWhileRevalidate(request) {
  const cached = await fromCache(request);
  const network = fetch(request).then((response) => {
    put(request, response);
    return response;
  }).catch(() => null);
  return cached ?? (await network) ?? Response.error();
}

/** Documents: always prefer fresh content, fall back to whatever we have. */
async function networkFirst(request) {
  try {
    const response = await fetch(request);
    put(request, response);
    return response;
  } catch {
    const cached = await fromCache(request);
    if (cached) return cached;
    if (request.mode === 'navigate') {
      const fallback = await fromCache(new Request(OFFLINE_FALLBACK));
      if (fallback) return fallback;
    }
    return new Response('offline', { status: 503, headers: { 'Content-Type': 'text/plain; charset=utf-8' } });
  }
}

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET') return;

  let url;
  try {
    url = new URL(request.url);
  } catch {
    return;
  }
  if (url.origin !== self.location.origin) return;
  // Range requests (media seeking) must not be answered from a full cached
  // response; let the network handle them.
  if (request.headers.has('range')) return;

  const path = url.pathname;
  if (path.startsWith('/static/') || path.endsWith('.woff2')) {
    event.respondWith(staleWhileRevalidate(request));
  } else if (/^\/(?:search|fs)-[a-z-]{2,8}\.json$/.test(path)) {
    event.respondWith(staleWhileRevalidate(request));
  } else if (request.mode === 'navigate' || path.endsWith('/') || path.endsWith('.html')) {
    event.respondWith(networkFirst(request));
  }
});
