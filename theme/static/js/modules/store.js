/**
 * Storage wrapper that cannot throw and cannot return something unexpected.
 *
 * Two independent reasons for the try/catch on every call: Safari in private
 * mode throws on setItem once the (zero-byte) quota is hit, and a site running
 * with cookies blocked throws on merely *reading* localStorage. Neither is
 * worth taking a feature down for.
 *
 * Values read back out are treated as untrusted input — anything on the same
 * origin, including a previous version of this site, could have written them —
 * so every getter validates before returning, and falls back rather than
 * trusting what it found.
 */

const PREFIX = 'czr:';
const MAX_VALUE = 8192;

function backend(kind) {
  try {
    const store = kind === 'session' ? window.sessionStorage : window.localStorage;
    const probe = PREFIX + 'probe';
    store.setItem(probe, '1');
    store.removeItem(probe);
    return store;
  } catch {
    return null;
  }
}

function make(kind) {
  let store;
  const resolve = () => (store === undefined ? (store = backend(kind)) : store);

  const api = {
    /**
     * @param {string} key
     * @param {{fallback?: any, allow?: string[], pattern?: RegExp}} [rules]
     */
    get(key, rules) {
      const options = rules ?? {};
      const fallback = options.fallback ?? null;
      const target = resolve();
      if (!target) return fallback;
      let value;
      try {
        value = target.getItem(PREFIX + key);
      } catch {
        return fallback;
      }
      if (typeof value !== 'string' || value.length > MAX_VALUE) return fallback;
      if (options.allow && !options.allow.includes(value)) return fallback;
      if (options.pattern && !options.pattern.test(value)) return fallback;
      return value;
    },

    set(key, value) {
      const target = resolve();
      if (!target || typeof value !== 'string' || value.length > MAX_VALUE) return false;
      try {
        target.setItem(PREFIX + key, value);
        return true;
      } catch {
        return false;
      }
    },

    remove(key) {
      const target = resolve();
      if (!target) return;
      try {
        target.removeItem(PREFIX + key);
      } catch {
        /* nothing sensible to do */
      }
    },

    /** JSON round-trip guarded by a caller-supplied shape check. */
    getJSON(key, isValid, fallback) {
      const raw = api.get(key);
      if (raw === null) return fallback;
      try {
        const parsed = JSON.parse(raw);
        return isValid(parsed) ? parsed : fallback;
      } catch {
        return fallback;
      }
    },

    setJSON(key, value) {
      try {
        return api.set(key, JSON.stringify(value));
      } catch {
        return false;
      }
    },

    flag(key) {
      return api.get(key, { allow: ['1'] }) === '1';
    },

    setFlag(key) {
      return api.set(key, '1');
    },
  };
  return api;
}

export const local = make('local');
export const session = make('session');

export const KEYS = {
  theme: 'theme',
  motion: 'motion',
  history: 'hist',
  booted: 'booted',
  fx: 'fx',
};
