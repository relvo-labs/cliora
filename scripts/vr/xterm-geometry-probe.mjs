// plan/28 VR-01 §1 + §2 — the two gating measurements, run with no backend and no
// dev server: both questions are about xterm itself, not about Cliora's stack.
//
//   node scripts/vr/xterm-geometry-probe.mjs [output-dir]     # default artifacts/vr/local
//
// §1 asks how many rows a given fontSize/lineHeight yields in plan/28's target
// geometry, because docs/design/visual-refresh says 14px/1.6 and plan/09's gate is
// >= 30 rows. §2 asks whether assigning `options.theme` keeps the buffer, because
// "switching theme does not interrupt work" is the phase's core promise.
//
// Only the browsers installed in this environment are run; the rest are recorded as
// skipped, never silently omitted (same rule as scripts/ly/evidence.sh).
import { readFileSync, mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");
// Playwright is installed under frontend/, not at the repo root, so resolve from
// there rather than adding a second node_modules tree for one probe.
const { chromium, firefox, webkit } = createRequire(
  join(ROOT, "frontend", "package.json"),
)("@playwright/test");
const OUT = process.argv[2] ?? join(ROOT, "artifacts", "vr", "local");
mkdirSync(OUT, { recursive: true });

const read = (p) => readFileSync(join(ROOT, "frontend", "node_modules", p), "utf8");
const XTERM_JS = read("@xterm/xterm/lib/xterm.js");
const XTERM_CSS = read("@xterm/xterm/css/xterm.css");
const FIT_JS = read("@xterm/addon-fit/lib/addon-fit.js");

// plan/28 00-…md §4. The host is given exactly the height the target geometry
// leaves for the CLI pane, so `rows` here is the number the gate will measure.
const GEOMETRY = [
  { label: "1440x900", viewport: { width: 1440, height: 900 }, paneHeight: 674, paneWidth: 1440 - 208 - 32 - 258 },
  { label: "1024x768", viewport: { width: 1024, height: 768 }, paneHeight: 768 - 224 - 2, paneWidth: 1024 - 64 - 32 - 258 },
];
const FONTS = [13, 14];
const LINE_HEIGHTS = [1.0, 1.2, 1.4, 1.6];
const ROW_GATE = 30; // plan/09 LY-06

function page(paneWidth, paneHeight) {
  return `<!doctype html><meta charset="utf-8">
<style>${XTERM_CSS}
  html,body{margin:0;background:#101416}
  #host{width:${paneWidth}px;height:${paneHeight}px}</style>
<div id="host"></div>
<script>${XTERM_JS}</script>
<script>${FIT_JS}</script>`;
}

async function measure(browserType, name, results) {
  let browser;
  try {
    browser = await browserType.launch();
  } catch (error) {
    results.skipped.push(`${name}: ${String(error).split("\n")[0]}`);
    return;
  }
  const ctx = await browser.newContext();
  for (const geo of GEOMETRY) {
    const p = await ctx.newPage();
    await p.setViewportSize(geo.viewport);
    await p.setContent(page(geo.paneWidth, geo.paneHeight));
    for (const fontSize of FONTS) {
      for (const lineHeight of LINE_HEIGHTS) {
        const row = await p.evaluate(
          ([fontSize, lineHeight]) => {
            const host = document.querySelector("#host");
            host.innerHTML = "";
            const term = new window.Terminal({
              fontSize,
              lineHeight,
              // plan/28 D12: no webfont ships (ADR 0016), so this is the real stack.
              fontFamily: 'ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace',
              scrollback: 10000,
            });
            const fit = new window.FitAddon.FitAddon();
            term.loadAddon(fit);
            term.open(host);
            fit.fit();
            const dims = term._core?._renderService?.dimensions?.css?.cell ?? {};
            const screen = host.querySelector(".xterm-screen");
            const out = {
              rows: term.rows,
              cols: term.cols,
              cellHeight: dims.height ?? null,
              screenHeight: screen ? screen.getBoundingClientRect().height : null,
              hostHeight: host.getBoundingClientRect().height,
            };
            term.dispose();
            return out;
          },
          [fontSize, lineHeight],
        );
        results.geometry.push({ browser: name, geometry: geo.label, fontSize, lineHeight, ...row });
      }
    }
    await p.close();
  }

  // §2 — does assigning options.theme preserve the buffer, the scroll position,
  // the unsent input and the row count?
  const p = await ctx.newPage();
  await p.setViewportSize(GEOMETRY[0].viewport);
  await p.setContent(page(GEOMETRY[0].paneWidth, GEOMETRY[0].paneHeight));
  const swap = await p.evaluate(() => {
    const host = document.querySelector("#host");
    const term = new window.Terminal({ fontSize: 14, lineHeight: 1.2, scrollback: 10000 });
    const fit = new window.FitAddon.FitAddon();
    term.loadAddon(fit);
    term.open(host);
    fit.fit();
    for (let i = 1; i <= 200; i += 1) term.writeln("line " + i + " ————— padding to force scrollback");
    // Unsent input: written to the viewport without a newline, the way a prompt
    // holds what the user has typed but not sent.
    term.write("$ half-typed-command");
    return new Promise((resolve) => {
      setTimeout(() => {
        term.scrollToLine(120);
        const snapshot = () => {
          const buf = term.buffer.active;
          const lines = [];
          for (let i = Math.max(0, buf.length - 5); i < buf.length; i += 1) {
            lines.push(buf.getLine(i)?.translateToString(true) ?? "");
          }
          return {
            length: buf.length,
            viewportY: buf.viewportY,
            cursorX: buf.cursorX,
            rows: term.rows,
            tail: lines,
            // .xterm-screen is transparent: xterm paints the background through the
            // renderer. .xterm-viewport is the element the theme actually colours.
            background: getComputedStyle(host.querySelector(".xterm-viewport")).backgroundColor,
          };
        };
        window.__term = term;
        window.__snapshot = snapshot;
        resolve(snapshot());
      }, 300);
    });
  });
  const shotBefore = await p.locator("#host").screenshot();
  // The exact operation plan/28 02-…md §8 specifies: assign, do not rebuild.
  await p.evaluate(() => {
    window.__term.options.theme = {
      background: "#F0EAD6",
      foreground: "#101416",
      cursor: "#101416",
      selectionBackground: "#78AAFF40",
      blue: "#8FB6E8",
      magenta: "#C3A0DC",
    };
  });
  await p.waitForTimeout(400);
  const after = await p.evaluate(() => window.__snapshot());
  const shotAfter = await p.locator("#host").screenshot();
  results.themeSwap.push({
    browser: name,
    before: swap,
    after,
    pixelsChanged: !shotBefore.equals(shotAfter),
  });
  await p.close();
  await browser.close();
}

const results = { geometry: [], themeSwap: [], skipped: [] };
await measure(chromium, "chromium", results);
await measure(firefox, "firefox", results);
await measure(webkit, "webkit", results);

// ---- report ----------------------------------------------------------------
const lines = [];
lines.push("# plan/28 VR-01 §1/§2 — xterm geometry and theme-swap probe");
lines.push(`generated_utc: ${new Date().toISOString()}`);
lines.push(`node: ${process.version}`);
lines.push(`row gate (plan/09 LY-06): >= ${ROW_GATE}`);
lines.push("");
lines.push("## §1 rows by fontSize x lineHeight");
lines.push("");
lines.push("| browser | geometry | pane h | font | lineHeight | cell h | rows | cols | verdict |");
lines.push("|---|---|---:|---:|---:|---:|---:|---:|---|");
for (const r of results.geometry) {
  lines.push(
    `| ${r.browser} | ${r.geometry} | ${Math.round(r.hostHeight)} | ${r.fontSize} | ${r.lineHeight.toFixed(1)} | ${r.cellHeight} | ${r.rows} | ${r.cols} | ${r.rows >= ROW_GATE ? "pass" : "**FAIL**"} |`,
  );
}
lines.push("");
lines.push("## §2 options.theme assignment");
lines.push("");
for (const s of results.themeSwap) {
  const same =
    s.before.length === s.after.length &&
    s.before.viewportY === s.after.viewportY &&
    s.before.cursorX === s.after.cursorX &&
    s.before.rows === s.after.rows &&
    JSON.stringify(s.before.tail) === JSON.stringify(s.after.tail);
  lines.push(`### ${s.browser}`);
  lines.push("");
  lines.push("| field | before | after |");
  lines.push("|---|---|---|");
  for (const k of ["length", "viewportY", "cursorX", "rows", "background"]) {
    lines.push(`| ${k} | ${s.before[k]} | ${s.after[k]} |`);
  }
  lines.push(`| tail[-1] | \`${s.before.tail.at(-1)}\` | \`${s.after.tail.at(-1)}\` |`);
  lines.push("");
  lines.push(`| rendered pixels changed | — | ${s.pixelsChanged} |`);
  lines.push("");
  lines.push(
    `verdict: ${
      same && s.pixelsChanged
        ? "**PASS** — buffer, scroll position, unsent input and rows all unchanged, and the terminal did repaint"
        : same
          ? "INCONCLUSIVE — state preserved but nothing repainted; the assignment may not have taken effect"
          : "**FAIL** — terminal state changed across the theme assignment"
    }`,
  );
  lines.push("");
}
if (results.skipped.length) {
  lines.push("## skipped");
  lines.push("");
  for (const s of results.skipped) lines.push(`- ${s}`);
  lines.push("");
  lines.push("Skipped legs are recorded, never omitted: a pack that quietly dropped a browser reads as a pass.");
}
const report = lines.join("\n") + "\n";
writeFileSync(join(OUT, "vr-01-xterm-probe.md"), report);
writeFileSync(join(OUT, "vr-01-xterm-probe.json"), JSON.stringify(results, null, 2));
process.stdout.write(report);
