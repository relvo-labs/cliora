// M8 — does `--layout-sidebar: 208px` still fit once V2.0 adds a nav item and a
// second level? (plan/16/08-open-measurements.md §1)
//
// plan/09/03 measured "the longest item needs ~144px, so 208px leaves 64px of
// headroom". That figure was taken against `Enrollment`; `Integrations` arrived
// later (plan/11) and is longer, so the published number is already stale — this
// script re-measures rather than adding to it.
//
// It renders the *real* CSS: `theme/tokens.css` and `theme/base.css` are read from
// disk, and the nav rules are copied verbatim from the scoped block in
// `components/layout/AppLayout.vue`. Nothing here is an estimate; if AppLayout's
// nav CSS changes, this script must be updated with it or it measures a fiction.
//
// Run from `frontend/` so `@playwright/test` resolves:
//   cd frontend && node ../scripts/pj/measure-sidebar.mjs

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const frontend = resolve(here, "../../frontend");
// ESM resolves bare specifiers relative to *this file*, not the cwd, and Playwright
// lives in frontend/node_modules. Resolve through frontend/package.json so the script
// can sit in scripts/pj/ without a second copy of the dependency.
const { chromium } = createRequire(resolve(frontend, "package.json"))("@playwright/test");

const themeDir = resolve(frontend, "src/theme");
const tokens = readFileSync(resolve(themeDir, "tokens.css"), "utf8");
const base = readFileSync(resolve(themeDir, "base.css"), "utf8");

// Verbatim from AppLayout.vue's <style scoped>. Kept as a string so a diff in that
// file shows up here as a conflict rather than as a silently wrong number.
const NAV_CSS = `
.shell > aside { padding: 16px 12px; }
nav { display: grid; gap: 5px; }
nav a {
  display: flex;
  gap: 11px;
  padding: 11px;
  border-radius: 8px;
  text-decoration: none;
  font-size: 13px;
}
`;

// The V2.0 structure (plan/16/05-…md §1.2/§1.3). `Projects` and `Sessions` collapse
// to flat items because a group whose only child repeats the group name renders as
// one row, not two.
//
// Two variants are measured because the choice between them was a design decision,
// not a width-forced one — both fit, and keeping the loser measured is what makes
// "we chose the one with 61px of headroom over the one with 49px" checkable later.
//   divider (ADOPTED): group label is an un-indented rule; children are not indented.
//   indented:          group label is its own row; children indent 12px.
// Adopted variant printed LAST so `| tail` shows its numbers next to the verdict
// rather than the runner-up's.
const VARIANTS = {
  indented: 12,
  divider: 0,
};

const ITEMS = [
  { label: "Projects", icon: "▦", child: false, note: "V2.0 new, flat" },
  { label: "Sessions", icon: "▷", child: false, note: "existing, flat" },
  { label: "Infrastructure", icon: "", child: false, note: "group label", heading: true },
  { label: "Dashboard", icon: "◈", child: true, note: "all roles" },
  { label: "Nodes", icon: "▣", child: true, note: "all roles" },
  { label: "Enrollment", icon: "◉", child: true, note: "enrollment.manage" },
  { label: "Audit", icon: "☰", child: true, note: "audit.view" },
  { label: "Integrations", icon: "⇄", child: true, note: "integration.manage" },
];

const SIDEBAR = 208; // --layout-sidebar
const ASIDE_PADDING = 24; // 12px each side

const html = `
<style>${tokens}${base}${NAV_CSS}
  /* Measure intrinsic width: let each row size to its content instead of the column. */
  nav a, nav .heading { width: max-content; }
  nav .heading { font-size: 11px; padding: 11px; text-transform: none; }
</style>
<div class="shell"><aside><nav>
${ITEMS.map(
  (item, i) =>
    `<${item.heading ? "div" : "a"} class="${item.heading ? "heading" : ""}" data-i="${i}">` +
    `${item.icon ? `<span>${item.icon}</span>` : ""}<span>${item.label}</span>` +
    `</${item.heading ? "div" : "a"}>`,
).join("\n")}
</nav></aside></div>`;

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setViewportSize({ width: 1440, height: 900 });
await page.setContent(html);

const content = [];
for (let i = 0; i < ITEMS.length; i += 1) {
  const box = await page.locator(`[data-i="${i}"]`).boundingBox();
  content.push(Math.ceil(box.width));
}
const version = browser.version();
await browser.close();

const pad = (s, n) => String(s).padEnd(n);
console.log(`chromium ${version}  viewport 1440x900  --layout-sidebar ${SIDEBAR}px  aside padding ${ASIDE_PADDING}px`);

const summary = {};
for (const [variant, childIndent] of Object.entries(VARIANTS)) {
  const rows = ITEMS.map((item, i) => {
    const indent = item.child ? childIndent : 0;
    return { ...item, indent, content: content[i], needed: content[i] + indent + ASIDE_PADDING };
  });
  const widest = rows.reduce((a, b) => (b.needed > a.needed ? b : a));
  summary[variant] = widest;

  console.log("");
  console.log(`--- variant: ${variant}${variant === "divider" ? "  (ADOPTED)" : ""} ---`);
  console.log(`${pad("item", 18)}${pad("indent", 8)}${pad("content", 9)}${pad("needed", 8)}note`);
  for (const r of rows) {
    console.log(`${pad(r.label, 18)}${pad(r.indent + "px", 8)}${pad(r.content + "px", 9)}${pad(r.needed + "px", 8)}${r.note}`);
  }
  console.log(`widest: ${widest.label} ${widest.needed}px   headroom: ${SIDEBAR - widest.needed}px   ${widest.needed <= SIDEBAR ? "FITS" : "DOES NOT FIT"}`);
}

console.log("");
const adopted = summary.divider;
console.log(
  adopted.needed <= SIDEBAR
    ? `VERDICT: adopted variant fits with ${SIDEBAR - adopted.needed}px to spare — no change needed`
    : "VERDICT: adopted variant does not fit — see plan/16/05-…md §1.4",
);
