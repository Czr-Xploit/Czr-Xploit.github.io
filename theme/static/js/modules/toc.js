/**
 * Scroll-spy table of contents and the reading-progress bar.
 *
 * Scroll-spy uses IntersectionObserver rather than a scroll handler: the
 * browser computes the intersections off the main thread and only calls back
 * when the answer changes. The progress bar does need scroll position, so that
 * one listener is passive and rAF-throttled — it writes a transform, never a
 * width, so it cannot trigger layout.
 */

import { qs, qsa, on } from './dom.js';
import { next as onNextFrame } from './raf.js';

const ACTIVE = 'is-active';

export function init() {
  const links = qsa('[data-toc-link]');
  const progress = qs('#reading-progress .progress-bar');
  const article = qs('#article-body');
  const offs = [];
  let observer = null;
  let current = null;

  // -- scroll spy ------------------------------------------------------- //
  const targets = [];
  for (const link of links) {
    const id = link.getAttribute('data-toc-link');
    const heading = id ? document.getElementById(id) : null;
    if (heading) targets.push({ link, heading });
  }

  function activate(entry) {
    if (entry === current) return;
    current = entry;
    for (const item of targets) {
      const active = item === entry;
      item.link.classList.toggle(ACTIVE, active);
      if (active) item.link.setAttribute('aria-current', 'true');
      else item.link.removeAttribute('aria-current');
    }
  }

  if (targets.length && typeof IntersectionObserver === 'function') {
    const seen = new Set();
    observer = new IntersectionObserver((entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) seen.add(entry.target);
        else seen.delete(entry.target);
      }
      let chosen = targets.find((item) => seen.has(item.heading));
      if (!chosen) {
        // Nothing in the band: fall back to the last heading above it, so a
        // long section keeps its own entry highlighted while it is read.
        for (const item of targets) {
          if (item.heading.getBoundingClientRect().top <= 120) chosen = item;
        }
      }
      if (chosen) activate(chosen);
    }, {
      // A band across the top third of the viewport: a heading is "current"
      // from the moment it reaches reading height until the next one does.
      rootMargin: '-80px 0px -66% 0px',
      threshold: 0,
    });
    for (const item of targets) observer.observe(item.heading);
  }

  // -- reading progress -------------------------------------------------- //
  if (progress && article) {
    let ticking = false;

    const update = () => {
      ticking = false;
      const rect = article.getBoundingClientRect();
      const total = rect.height - window.innerHeight;
      const passed = -rect.top;
      const ratio = total > 0 ? Math.min(1, Math.max(0, passed / total)) : (rect.top <= 0 ? 1 : 0);
      // The stylesheet owns the transform: `.progress-bar` is
      // `scaleX(var(--progress, var(--reading-progress, 0)))`, so writing the
      // custom property keeps the animation declarative and leaves the CSS free
      // to change how progress is drawn.
      progress.style.setProperty('--progress', ratio.toFixed(4));
      document.documentElement.style.setProperty('--reading-progress', ratio.toFixed(4));
    };

    const schedule = () => {
      if (ticking) return;
      ticking = true;
      onNextFrame(update);
    };

    update();
    offs.push(on(window, 'scroll', schedule, { passive: true }));
    offs.push(on(window, 'resize', schedule, { passive: true }));
  }

  return {
    destroy() {
      observer?.disconnect();
      while (offs.length) offs.pop()();
    },
  };
}
