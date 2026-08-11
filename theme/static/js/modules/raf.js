/**
 * The site's single requestAnimationFrame loop.
 *
 * Every animated module registers a callback here instead of starting its own
 * loop. One loop means one place that knows about document.hidden, one place
 * that can be frame-capped, and — the part that actually matters on a phone —
 * zero loops running when nothing needs to animate, because the loop cancels
 * itself the moment the callback set empties.
 */

const tasks = new Set();
let handle = 0;
let running = false;

function frame(now) {
  handle = 0;
  if (!running) return;

  for (const task of Array.from(tasks)) {
    // A capped task still gets called on the frame where its budget expires,
    // never more often; `last` is seeded on the first frame so a 30 fps task
    // does not burn its first tick immediately after a tab regains focus.
    if (task.interval > 0) {
      if (task.last === 0) task.last = now;
      else if (now - task.last < task.interval) continue;
      else task.last = now;
    }
    try {
      task.fn(now);
    } catch (error) {
      // One broken animation must not stop every other animation on the page.
      tasks.delete(task);
      if (typeof console !== 'undefined') console.error('raf task removed:', error);
    }
  }

  if (tasks.size > 0) handle = requestAnimationFrame(frame);
  else running = false;
}

function start() {
  if (running || tasks.size === 0 || document.hidden) return;
  running = true;
  handle = requestAnimationFrame(frame);
}

function stop() {
  running = false;
  if (handle) cancelAnimationFrame(handle);
  handle = 0;
}

/**
 * @param {(now: number) => void} fn
 * @param {{fps?: number}} [options] frame cap; 0 or omitted means every frame
 * @returns {() => void} remover
 */
export function add(fn, options) {
  const fps = options?.fps ?? 0;
  const task = { fn, interval: fps > 0 ? 1000 / fps : 0, last: 0 };
  tasks.add(task);
  start();
  return () => {
    tasks.delete(task);
    if (tasks.size === 0) stop();
  };
}

export function count() {
  return tasks.size;
}

/** Run one callback on the next frame without joining the loop. */
export function next(fn) {
  const id = requestAnimationFrame(fn);
  return () => cancelAnimationFrame(id);
}

document.addEventListener('visibilitychange', () => {
  if (document.hidden) {
    stop();
  } else {
    // Timestamps from before the tab was backgrounded are meaningless now.
    for (const task of tasks) task.last = 0;
    start();
  }
});
