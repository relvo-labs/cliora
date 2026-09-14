/* Sets data-theme before first paint. Must stay tiny and import nothing.
 *
 * An external file, not an inline script: the CSP is `script-src 'self'` with no
 * 'unsafe-inline' (deploy/nginx/nginx.conf, deploy/railway/nginx.conf.template),
 * so an inline bootstrap is blocked and the symptom is "the theme sometimes
 * doesn't apply". Not in main.ts either: that is a deferred module and runs after
 * the stylesheet has painted. In public/ so Vite does not hash the name.
 *
 * No choice stored means no attribute, which lets the prefers-color-scheme rule
 * in tokens.css decide. GATE-VR-NO-GLYPH-ICON checks this file's length.
 *
 * Below 768px the viewport decides and the stored choice is not read at all
 * (plan/29 MS-D-05/MS-D-07). Doing it here rather than in main.ts is the whole
 * point: main.ts is a deferred module, so leaving it to that path paints one
 * full dark frame on every cold load on a phone. The stored value is left
 * untouched — it is still the preference for every wider viewport. */
(function () {
  try {
    var t = window.innerWidth < 768 ? "pocket" : localStorage.getItem("cliora-theme");
    if (t === "pocket" || t === "graphite" || t === "porcelain") {
      document.documentElement.setAttribute("data-theme", t);
    }
  } catch (e) {
    /* Private mode or a blocked origin: fall through to the OS preference. */
  }
})();
