/* Anti-flash bootstrap: applies the stored theme before the first paint.
 *
 * This is normally an inline <script>, but the site ships script-src 'self'
 * with no 'unsafe-inline', so an inline snippet would be blocked outright. An
 * external classic script is the only version that runs under that policy, so
 * it stays this small: one cached request, negligible parse cost.
 *
 * Stored values are checked against a fixed allowlist mirroring site.json.
 */
(function () {
  var THEMES = ['phosphor', 'amber', 'ice', 'redteam'];
  var root = document.documentElement;

  root.classList.remove('no-js');
  root.classList.add('js');

  try {
    var theme = localStorage.getItem('czr:theme');
    if (theme && THEMES.indexOf(theme) !== -1) root.setAttribute('data-theme', theme);

    var motion = localStorage.getItem('czr:motion');
    if (motion === 'on' || motion === 'off') root.setAttribute('data-motion', motion);
  } catch (error) {
    /* Storage blocked or full: the server-rendered defaults stand. */
  }
})();
