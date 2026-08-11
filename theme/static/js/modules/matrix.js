/**
 * Canvas matrix rain.
 *
 * Everything here exists to keep a decorative background from costing anything
 * a reader would notice:
 *
 *  - Glyphs are rendered *once* into an offscreen atlas and blitted with
 *    drawImage. fillText re-rasterises and re-shapes text on every call, which
 *    at ~90 columns x 30 fps is ~2700 text layouts per second for pixels that
 *    never change. The atlas turns that into 2700 texture copies.
 *  - Trails come from painting a translucent background over the whole canvas
 *    each frame instead of clearing it: the previous frame decays on its own,
 *    so a column only ever draws its newest glyph.
 *  - The canvas is sized in device pixels (DPR capped at 2) and scaled down by
 *    CSS, so it is sharp without ever being 9x the work on a 3x phone.
 *  - Cheap devices and narrow viewports get less of it, or none.
 */

import { qs, on } from './dom.js';
import { add as addFrame } from './raf.js';
import { motionOK, onMotionChange } from './motion.js';

const GLYPHS = 'アイウエオカキクケコサシスセソタチツテトナニヌネノabcdef0123456789<>[]{}/\\|=+*#$%&';
const FPS = 30;
const MIN_WIDTH = 720;
const RESIZE_DEBOUNCE = 160;
const FADE_ALPHA = 0.085;

let instance = null;

function hexToRgba(hex, alpha) {
  const value = (hex ?? '').trim();
  if (!/^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/.test(value)) return null;
  const full = value.length === 4
    ? '#' + value[1] + value[1] + value[2] + value[2] + value[3] + value[3]
    : value;
  const red = parseInt(full.slice(1, 3), 16);
  const green = parseInt(full.slice(3, 5), 16);
  const blue = parseInt(full.slice(5, 7), 16);
  return 'rgba(' + red + ',' + green + ',' + blue + ',' + alpha + ')';
}

/** How much rain this device should be asked to draw, 0 meaning "none". */
function budget(width) {
  if (width < MIN_WIDTH) return 0;
  const cores = navigator.hardwareConcurrency;
  if (typeof cores === 'number' && cores > 0 && cores <= 2) return 0;
  const weak = typeof cores === 'number' && cores > 0 && cores <= 4;
  // Density per unit area, not per column: a 2560px-wide window should not get
  // three times the work of a 900px one just because it has more room.
  const area = Math.min(2.2, (width * window.innerHeight) / (1440 * 900));
  return (weak ? 0.45 : 1) * (0.6 + 0.4 * area);
}

function create() {
  const canvas = qs('#matrix');
  if (!canvas || typeof canvas.getContext !== 'function') return null;
  const context = canvas.getContext('2d', { alpha: true });
  if (!context) return null;

  // The layer is already aria-hidden in the markup; belt and braces, plus the
  // pointer-events guard so the canvas can never eat a click.
  canvas.setAttribute('aria-hidden', 'true');
  canvas.style.pointerEvents = 'none';

  const attribute = Number.parseFloat(canvas.getAttribute('data-density') ?? '');
  const configured = Number.isFinite(attribute) ? Math.min(1.5, Math.max(0.05, attribute)) : 0.7;

  let dpr = 1;
  let cell = 0;
  let rows = 0;
  let columns = 0;
  let drops = null;
  let lastRow = null;
  let speeds = null;
  let atlas = null;
  let atlasCells = 0;
  let bodyColour = '#3df08a';
  let headColour = '#ccffe0';
  let fade = 'rgba(5,7,10,' + FADE_ALPHA + ')';
  let density = configured;
  let stopFrame = null;
  let observer = null;
  let themeWatcher = null;
  let resizeTimer = 0;
  const offs = [];

  /** Space-separated channel triple, as used by the theme's `--*-rgb` tokens. */
  function tripleToRgba(triple, alpha) {
    const parts = (triple ?? '').trim().split(/[\s,]+/).map(Number);
    if (parts.length < 3 || parts.some((value) => !Number.isFinite(value))) return null;
    return 'rgba(' + parts[0] + ',' + parts[1] + ',' + parts[2] + ',' + alpha + ')';
  }

  /**
   * The rain borrows the active theme's colours instead of hardcoding green, so
   * switching to amber or ice switches the canvas too. Only recognised colour
   * shapes are accepted; anything else falls back to a constant.
   */
  function readColours() {
    const styles = getComputedStyle(document.documentElement);
    const hex = /^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$/;
    const glyph = styles.getPropertyValue('--matrix-glyph').trim() || styles.getPropertyValue('--accent').trim();
    const head = styles.getPropertyValue('--matrix-head').trim() || styles.getPropertyValue('--accent-2').trim();
    if (hex.test(glyph)) bodyColour = glyph;
    if (hex.test(head)) headColour = head;
    fade = hexToRgba(styles.getPropertyValue('--bg').trim(), FADE_ALPHA)
      ?? tripleToRgba(styles.getPropertyValue('--bg-rgb'), FADE_ALPHA)
      ?? 'rgba(5,7,10,' + FADE_ALPHA + ')';
  }

  /**
   * Two rows: body colour on row 0, head colour on row 1. One glyph per column.
   * Rebuilt only when the cell size or the theme colours change.
   */
  function buildAtlas() {
    atlasCells = GLYPHS.length;
    const sheet = document.createElement('canvas');
    sheet.width = atlasCells * cell;
    sheet.height = cell * 2;
    const paint = sheet.getContext('2d');
    if (!paint) return;
    paint.textBaseline = 'top';
    paint.textAlign = 'center';
    paint.font = Math.floor(cell * 0.86) + 'px ui-monospace, SFMono-Regular, Menlo, monospace';
    for (let row = 0; row < 2; row += 1) {
      paint.fillStyle = row === 0 ? bodyColour : headColour;
      paint.shadowColor = row === 1 ? headColour : 'transparent';
      paint.shadowBlur = row === 1 ? cell * 0.4 : 0;
      for (let index = 0; index < atlasCells; index += 1) {
        paint.fillText(GLYPHS[index], index * cell + cell / 2, row * cell + cell * 0.06);
      }
    }
    atlas = sheet;
  }

  function resize() {
    const width = canvas.clientWidth || window.innerWidth;
    const height = canvas.clientHeight || window.innerHeight;
    density = configured * budget(width);
    dpr = Math.min(2, window.devicePixelRatio || 1);
    canvas.width = Math.max(1, Math.floor(width * dpr));
    canvas.height = Math.max(1, Math.floor(height * dpr));
    cell = Math.max(10, Math.round(16 * dpr));
    columns = Math.max(1, Math.floor(canvas.width / cell));
    rows = Math.max(1, Math.floor(canvas.height / cell));
    drops = new Float32Array(columns).fill(-1);
    lastRow = new Int32Array(columns).fill(-1);
    speeds = new Float32Array(columns);
    for (let index = 0; index < columns; index += 1) speeds[index] = 0.35 + Math.random() * 0.55;
    readColours();
    buildAtlas();
    context.clearRect(0, 0, canvas.width, canvas.height);
  }

  function blit(index, row, head) {
    if (!atlas) return;
    const glyph = Math.floor(Math.random() * atlasCells);
    context.drawImage(
      atlas,
      glyph * cell, head ? cell : 0, cell, cell,
      index * cell, row * cell, cell, cell,
    );
  }

  function frame() {
    context.fillStyle = fade;
    context.fillRect(0, 0, canvas.width, canvas.height);

    const spawn = 0.014 * density;
    for (let index = 0; index < columns; index += 1) {
      let position = drops[index];
      if (position < 0) {
        if (Math.random() < spawn) drops[index] = 0;
        continue;
      }
      position += speeds[index];
      const row = Math.floor(position);
      // Only paint when the stream has actually moved into a new cell: painting
      // the same cell twice fights the fade and produces a hard bright block.
      if (row !== lastRow[index]) {
        blit(index, row, true);
        lastRow[index] = row;
      }
      if (row > rows + 2) {
        drops[index] = -1;
        lastRow[index] = -1;
      } else {
        drops[index] = position;
      }
    }
  }

  /**
   * Reduced motion still gets a picture: an empty canvas behind a page whose
   * design expects one reads as a rendering failure, not as restraint.
   */
  function staticFrame() {
    context.clearRect(0, 0, canvas.width, canvas.height);
    const target = Math.floor(columns * rows * 0.02 * Math.max(0.4, density));
    for (let count = 0; count < target; count += 1) {
      blit(Math.floor(Math.random() * columns), Math.floor(Math.random() * rows), false);
    }
  }

  function stop() {
    stopFrame?.();
    stopFrame = null;
  }

  function start() {
    if (density <= 0) return false;
    if (!motionOK()) {
      stop();
      staticFrame();
      return false;
    }
    if (stopFrame) return true;
    stopFrame = addFrame(frame, { fps: FPS });
    return true;
  }

  const scheduleResize = () => {
    clearTimeout(resizeTimer);
    // Debounced because ResizeObserver fires per animation frame during a drag,
    // and every call here reallocates typed arrays and repaints the atlas.
    resizeTimer = setTimeout(() => {
      const wasRunning = Boolean(stopFrame);
      stop();
      resize();
      if (wasRunning || !motionOK()) start();
    }, RESIZE_DEBOUNCE);
  };

  resize();

  if (typeof ResizeObserver === 'function') {
    observer = new ResizeObserver(scheduleResize);
    observer.observe(canvas.parentElement ?? canvas);
  } else {
    offs.push(on(window, 'resize', scheduleResize, { passive: true }));
  }

  // Repaint the atlas when the theme changes: the glyph colours come from CSS
  // custom properties, and an atlas is a cached bitmap that will not update on
  // its own.
  if (typeof MutationObserver === 'function') {
    themeWatcher = new MutationObserver(() => {
      readColours();
      buildAtlas();
      if (!motionOK()) staticFrame();
    });
    themeWatcher.observe(document.documentElement, { attributeFilter: ['data-theme'] });
  }

  offs.push(onMotionChange(() => {
    if (motionOK()) start();
    else {
      stop();
      staticFrame();
    }
  }));

  return {
    start,
    stop,
    isRunning: () => Boolean(stopFrame),
    eligible: () => density > 0,
    destroy() {
      stop();
      clearTimeout(resizeTimer);
      observer?.disconnect();
      themeWatcher?.disconnect();
      while (offs.length) offs.pop()();
      context.clearRect(0, 0, canvas.width, canvas.height);
      // Drop the big allocations rather than waiting for the module to unload.
      atlas = null;
      drops = null;
      lastRow = null;
      speeds = null;
      instance = null;
    },
  };
}

function ensure() {
  if (!instance) instance = create();
  return instance;
}

export function init() {
  const api = ensure();
  api?.start();
  return api;
}

export function start() {
  const api = ensure();
  return api ? api.start() : false;
}

export function stop() {
  instance?.stop();
}

export function isRunning() {
  return Boolean(instance?.isRunning());
}

export function eligible() {
  return Boolean(ensure()?.eligible());
}

export function destroy() {
  instance?.destroy();
}
