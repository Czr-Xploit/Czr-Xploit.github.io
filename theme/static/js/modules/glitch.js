/**
 * Decorative text effects: scramble-decode reveal, typewriter, stat count-up.
 *
 * All three are strictly additive. The final text is already in the markup (or
 * in a data attribute the markup owns), so with JavaScript off, reduced motion
 * on, or this module throwing, the reader sees the finished string — which is
 * why every effect ends by writing that exact string back.
 */

import { qsa } from './dom.js';
import { add as addFrame } from './raf.js';
import { motionOK, onMotionChange } from './motion.js';

const GLYPHS = '01_/\\|<>[]{}#$%&*+=-abcdefghijklmnopqrstuvwxyz0123456789';
const SCRAMBLE_MS = 620;
const TYPE_MS = 42;
const COUNT_MS = 900;

function glyph() {
  return GLYPHS[Math.floor(Math.random() * GLYPHS.length)];
}

/**
 * Run `step(progress)` from 0 to 1 over `duration`, then `step(1)` once more.
 * 30 fps is plenty for text effects and leaves the frame budget alone.
 */
function tween(duration, step) {
  // Seed the clock from the first frame, not from performance.now() at
  // registration time. A requestAnimationFrame callback receives the timestamp
  // of the frame it belongs to, which can predate the moment the task was
  // registered if registration happened while that frame was already being
  // processed. Subtracting a later `started` from an earlier `now` yields a
  // negative progress, and a negative progress rendered a count-up as "-402".
  // Clamping to [0, 1] as well, so no arithmetic can escape the range.
  let started = 0;
  let stop = () => {};
  stop = addFrame((now) => {
    if (started === 0) started = now;
    const progress = Math.max(0, Math.min(1, (now - started) / duration));
    step(progress);
    if (progress >= 1) stop();
  }, { fps: 30 });
  return stop;
}

function scramble(node, finalText) {
  const length = finalText.length;
  return tween(SCRAMBLE_MS, (progress) => {
    if (progress >= 1) {
      node.textContent = finalText;
      node.classList.remove('is-scrambling');
      return;
    }
    const settled = Math.floor(length * progress);
    let out = finalText.slice(0, settled);
    for (let index = settled; index < length; index += 1) {
      out += finalText[index] === ' ' ? ' ' : glyph();
    }
    node.textContent = out;
  });
}

function typewriter(node, text) {
  const length = text.length;
  node.classList.add('is-typing');
  return tween(length * TYPE_MS, (progress) => {
    node.textContent = text.slice(0, Math.round(length * progress));
    if (progress >= 1) node.classList.remove('is-typing');
  });
}

function countUp(node, value, finalText) {
  return tween(COUNT_MS, (progress) => {
    if (progress >= 1) {
      node.textContent = finalText;
      return;
    }
    // Ease-out so the number lands rather than stopping dead.
    const eased = 1 - (1 - progress) * (1 - progress);
    node.textContent = String(Math.round(value * eased));
  });
}

export function init() {
  const offs = [];
  const stoppers = new Set();
  let observer = null;

  const typers = qsa('[data-typewriter]');
  const counters = qsa('[data-count]');
  const glitches = qsa('.glitch[data-text]');

  function immediate() {
    for (const node of typers) node.textContent = node.getAttribute('data-typewriter') ?? '';
    for (const node of glitches) {
      const text = node.getAttribute('data-text');
      if (text) node.textContent = text;
    }
  }

  if (!motionOK()) {
    immediate();
  } else {
    for (const node of typers) {
      const text = node.getAttribute('data-typewriter') ?? '';
      if (text) stoppers.add(typewriter(node, text));
    }

    for (const node of counters) {
      const raw = node.getAttribute('data-count') ?? '';
      const finalText = node.textContent ?? '';
      if (/^\d{1,9}$/.test(raw) && Number(raw) > 0) stoppers.add(countUp(node, Number(raw), finalText));
    }

    if (glitches.length && typeof IntersectionObserver === 'function') {
      observer = new IntersectionObserver((entries, self) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue;
          self.unobserve(entry.target);
          const text = entry.target.getAttribute('data-text');
          // Only scramble when the visible text really is the final text;
          // otherwise something else owns this node and we leave it alone.
          if (text && (entry.target.textContent ?? '').trim() === text.trim() && motionOK()) {
            entry.target.classList.add('is-scrambling');
            stoppers.add(scramble(entry.target, text));
          }
        }
      }, { rootMargin: '0px 0px -10% 0px' });
      for (const node of glitches) observer.observe(node);
    }
  }

  // If reduction is switched on mid-effect, stop and show the final strings.
  offs.push(onMotionChange((allowed) => {
    if (allowed) return;
    for (const stop of stoppers) stop();
    stoppers.clear();
    observer?.disconnect();
    immediate();
  }));

  return {
    destroy() {
      for (const stop of stoppers) stop();
      stoppers.clear();
      observer?.disconnect();
      while (offs.length) offs.pop()();
    },
  };
}
