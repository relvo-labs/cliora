// @vitest-environment node
// `no_viewer_or_scripting_import` (plan/31/05 BP-07 §2, §4).
//
// A static scan of the bundle's inputs. The PDF.js viewer (`pdfjs-dist/web/*`)
// brings download, print, open-file and an annotation DOM; the scripting
// sandbox (`pdf.sandbox*`, the QuickJS engine) is how a document's JavaScript
// would run. Neither may be imported anywhere, and `getDocument` may be called
// from pdf/setup.ts only, so its locked options cannot be bypassed.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { describe, expect, it } from "vitest";

const SRC = join(__dirname, "..");

function sources(dir: string): string[] {
  const out: string[] = [];
  for (const name of readdirSync(dir)) {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) out.push(...sources(path));
    else if (/\.(ts|vue)$/.test(name) && !/\.test\.ts$/.test(name))
      out.push(path);
  }
  return out;
}

const IMPORT =
  /(?:import\s[^'"]*?from\s*|import\s*\(\s*|import\s+)["']([^"']+)["']/g;

describe("PDF.js imports", () => {
  const files = sources(SRC);

  it("no_viewer_or_scripting_import", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const [, specifier] of text.matchAll(IMPORT)) {
        if (
          /^pdfjs-dist\/(legacy\/)?web(\/|$)/.test(specifier) ||
          /sandbox|scripting|quickjs/i.test(specifier)
        ) {
          offenders.push(`${relative(SRC, file)}: ${specifier}`);
        }
      }
    }
    expect(offenders).toEqual([]);
  });

  it("pdfjs-dist is imported by pdf/setup.ts only (components get types, not the library)", () => {
    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf8");
      for (const match of text.matchAll(IMPORT)) {
        const [statement, specifier] = match;
        if (!specifier.startsWith("pdfjs-dist")) continue;
        if (relative(SRC, file) === join("pdf", "setup.ts")) continue;
        if (/^import\s+type\s/.test(statement)) continue;
        offenders.push(`${relative(SRC, file)}: ${specifier}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("getDocument is called in pdf/setup.ts and nowhere else", () => {
    const callers = files.filter((file) =>
      /\bgetDocument\s*\(/.test(readFileSync(file, "utf8")),
    );
    expect(callers.map((f) => relative(SRC, f))).toEqual([
      join("pdf", "setup.ts"),
    ]);
  });

  it("the self-hosted assets never include the scripting engine", async () => {
    const { pdfjsAssetAllowed } = await import("../../vite.config");
    const root = join(SRC, "../node_modules/pdfjs-dist");
    const shipped: string[] = [];
    for (const dir of readdirSync(root)) {
      if (!statSync(join(root, dir)).isDirectory()) continue;
      for (const name of readdirSync(join(root, dir))) {
        if (pdfjsAssetAllowed(dir, name)) shipped.push(`${dir}/${name}`);
      }
    }
    expect(shipped.some((f) => f.startsWith("wasm/openjpeg"))).toBe(true);
    expect(shipped.some((f) => f.startsWith("cmaps/UniCNS-UCS2-H"))).toBe(true);
    expect(shipped.filter((f) => /quickjs|sandbox|scripting/i.test(f))).toEqual(
      [],
    );
    // Only the four asset directories: never build/ or web/.
    expect(new Set(shipped.map((f) => f.split("/")[0]))).toEqual(
      new Set(["cmaps", "standard_fonts", "wasm", "iccs"]),
    );
    expect(pdfjsAssetAllowed("wasm", "../build/pdf.mjs")).toBe(false);
  });

  it("no annotation, text or XFA layer is ever built", () => {
    const offenders = files.filter((file) =>
      /\b(AnnotationLayer|TextLayer|XfaLayer|AnnotationEditorLayer)\b/.test(
        readFileSync(file, "utf8"),
      ),
    );
    expect(offenders.map((f) => relative(SRC, f))).toEqual([]);
  });
});
