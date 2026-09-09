/* Sets data-theme before first paint. Must stay tiny and import nothing.
 *
 * An external file, not an inline script: the CSP is `script-src 'self'` with no
 * 'unsafe-inline' (deploy/nginx/nginx.conf, deploy/railway/nginx.conf.template),
 * so an inline bootstrap is blocked and the symptom is "the theme sometimes
 * doesn't apply". Not in main.ts either: that is a deferred module and runs after
 * the stylesheet has painted. In public/ so Vite does not hash the name.
 *
 * No choice stored means no attribute, which lets the prefers-color-scheme rule
 * in tokens.css decide. GATE-VR-NO-GLYPH-ICON checks this file's length. */
(function () {
  try {
    var t = localStorage.getItem("cliora-theme");
    if (t === "graphite" || t === "porcelain") {
      document.documentElement.setAttribute("data-theme", t);
    }
  } catch (e) {
    /* Private mode or a blocked origin: fall through to the OS preference. */
  }
})();
