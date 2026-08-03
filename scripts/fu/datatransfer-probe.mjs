// FU-01 #1: what can the front end learn about a dropped item BEFORE it uploads
// anything? Prints, for a drop and for three picker inputs, whether `items`
// exists and what `webkitGetAsEntry()` says about each entry — including a real
// directory and a zero-byte extensionless file.
//
// This did NOT run on the machine that wrote plan/15: the bundled Chromium is
// missing libatk-1.0.so.0 and there is no passwordless sudo to install it
// (plan/15/07-open-measurements.md §1). The upload path was therefore built
// fail-closed — only positively-confirmed files are uploaded — so its
// correctness does not depend on this probe's answer. Run it anyway on a machine
// with browser deps; a positive result means the rule can stay as it is.
//
// Usage: node scripts/fu/datatransfer-probe.mjs
// Resolved absolutely: this script lives outside frontend/, and ESM resolves bare
// specifiers from the importing file rather than the cwd.
const { chromium } = await import(
  new URL("../../frontend/node_modules/@playwright/test/index.mjs", import.meta.url).href
);
import { mkdtempSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const dir = mkdtempSync(join(tmpdir(), "fu01-"));
writeFileSync(join(dir, "plain.txt"), "hello");
writeFileSync(join(dir, "empty"), ""); // zero bytes, no extension
mkdirSync(join(dir, "folder"));
writeFileSync(join(dir, "folder", "inner.txt"), "inner");

const PAGE = `<!doctype html><meta charset=utf-8>
<div id=drop style="width:200px;height:80px;border:1px solid #000">drop</div>
<input id=one type=file>
<input id=many type=file multiple>
<input id=dirs type=file webkitdirectory>
<script>
window.results = [];
function describeItems(dt, label) {
  const out = { label, hasItems: !!dt.items, itemCount: dt.items ? dt.items.length : null,
                fileCount: dt.files ? dt.files.length : null, items: [] };
  if (dt.items) {
    for (const item of dt.items) {
      const row = { kind: item.kind, type: item.type };
      const get = item.webkitGetAsEntry;
      row.hasWebkitGetAsEntry = typeof get === "function";
      if (row.hasWebkitGetAsEntry) {
        let entry = null;
        try { entry = item.webkitGetAsEntry(); } catch (e) { row.entryError = String(e); }
        row.entryNull = entry === null;
        if (entry) { row.isFile = entry.isFile; row.isDirectory = entry.isDirectory; row.name = entry.name; }
      }
      const f = item.getAsFile ? item.getAsFile() : null;
      if (f) { row.fileName = f.name; row.fileSize = f.size; row.fileType = f.type; }
      out.items.push(row);
    }
  }
  if (dt.files) {
    out.files = Array.from(dt.files).map((f) => ({ name: f.name, size: f.size, type: f.type,
      relativePath: f.webkitRelativePath }));
  }
  window.results.push(out);
}
document.getElementById("drop").addEventListener("dragover", (e) => e.preventDefault());
document.getElementById("drop").addEventListener("drop", (e) => {
  e.preventDefault();
  describeItems(e.dataTransfer, "drop");
});
for (const id of ["one", "many", "dirs"]) {
  document.getElementById(id).addEventListener("change", (e) => {
    describeItems({ items: e.dataTransfer && e.dataTransfer.items, files: e.target.files },
                  "input#" + id);
  });
}
</script>`;

const browser = await chromium.launch();
const page = await browser.newPage();
await page.setContent(PAGE);

// A: synthetic drop of two files (a normal one and a zero-byte extensionless one).
await page.evaluate(() => {
  const dt = new DataTransfer();
  dt.items.add(new File(["hello"], "plain.txt", { type: "text/plain" }));
  dt.items.add(new File([], "empty", { type: "" }));
  document.getElementById("drop").dispatchEvent(
    new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
});

// B: the picker paths.
await page.setInputFiles("#one", join(dir, "plain.txt"));
await page.setInputFiles("#many", [join(dir, "plain.txt"), join(dir, "empty")]);
let dirPickerError = null;
try {
  await page.setInputFiles("#dirs", join(dir, "folder"));
} catch (e) {
  dirPickerError = String(e).split("\n")[0];
}

const results = await page.evaluate(() => window.results);
console.log(JSON.stringify({ results, dirPickerError }, null, 1));
await browser.close();
