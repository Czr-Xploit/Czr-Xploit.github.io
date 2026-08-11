/**
 * Click-to-play animated media.
 *
 * The markup ships the still frame in `src` and the animation in `data-gif`,
 * so a reader with no JavaScript sees a poster image rather than a broken
 * figure — and nobody pays for an animation they did not ask for. Autoplay
 * figures are the one exception, and they still defer to reduced motion.
 */

import { qsa, on } from './dom.js';
import { motionOK, onMotionChange } from './motion.js';

function frame(button) {
  return button.closest('.gif-figure, .gif-frame, figure');
}

function media(scope) {
  return scope?.querySelector('img.gif-media') ?? null;
}

/** Swap in the animation only once it has decoded, to avoid a blank flash. */
function play(image, button) {
  const animated = image.dataset.gif;
  if (!animated || image.dataset.playing === '1') return;
  if (!image.dataset.still) image.dataset.still = image.getAttribute('src') ?? '';
  const loader = new Image();
  loader.decoding = 'async';
  loader.addEventListener('load', () => {
    image.setAttribute('src', animated);
    image.dataset.playing = '1';
    button?.setAttribute('aria-pressed', 'true');
    frame(image)?.classList.add('is-playing');
  }, { once: true });
  loader.addEventListener('error', () => {
    button?.setAttribute('aria-pressed', 'false');
  }, { once: true });
  loader.src = animated;
}

function stop(image, button) {
  const still = image.dataset.still;
  if (!still) return;
  image.setAttribute('src', still);
  image.dataset.playing = '0';
  button?.setAttribute('aria-pressed', 'false');
  frame(image)?.classList.remove('is-playing');
}

export function init() {
  const offs = [];
  let observer = null;

  for (const button of qsa('[data-action="toggle-gif"]')) {
    button.setAttribute('aria-pressed', 'false');
  }

  offs.push(on(document, 'click', (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest('[data-action="toggle-gif"]');
    if (!button) return;
    const image = media(frame(button));
    if (!image?.dataset.gif) return;
    if (image.dataset.playing === '1') stop(image, button);
    else play(image, button);
  }));

  // `.is-autoplay` figures start when they scroll into view, and only then:
  // an off-screen animation is pure battery drain.
  const autoplay = qsa('.gif-figure.is-autoplay');
  if (autoplay.length && typeof IntersectionObserver === 'function') {
    observer = new IntersectionObserver((entries) => {
      if (!motionOK()) return;
      for (const entry of entries) {
        const image = media(entry.target);
        if (!image) continue;
        if (entry.isIntersecting) play(image, entry.target.querySelector('[data-action="toggle-gif"]'));
        else stop(image, entry.target.querySelector('[data-action="toggle-gif"]'));
      }
    }, { rootMargin: '120px' });
    for (const figure of autoplay) observer.observe(figure);
  }

  offs.push(onMotionChange((allowed) => {
    if (allowed) return;
    for (const figure of autoplay) {
      const image = media(figure);
      if (image) stop(image, figure.querySelector('[data-action="toggle-gif"]'));
    }
  }));

  return {
    destroy() {
      observer?.disconnect();
      while (offs.length) offs.pop()();
    },
  };
}
