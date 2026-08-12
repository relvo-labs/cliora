import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const checker = resolve(
  import.meta.dirname,
  "../../../scripts/frontend/check-tokens.mjs",
);

function fixture(style: string): string {
  const root = mkdtempSync(resolve(tmpdir(), "cliora-token-check-"));
  mkdirSync(resolve(root, "frontend/src/theme"), { recursive: true });
  writeFileSync(
    resolve(root, "frontend/src/theme/tokens.css"),
    ":root {\n  --known: #fff;\n}",
  );
  writeFileSync(resolve(root, "frontend/src/theme/base.css"), "");
  writeFileSync(
    resolve(root, "frontend/src/Fixture.vue"),
    `<template><div style="color: var(${"--known"})"></div></template><style>${style}</style>`,
  );
  return root;
}

describe("CSS token guard", () => {
  it("passes defined references", () => {
    expect(() =>
      execFileSync(process.execPath, [
        checker,
        "--root",
        fixture("color: var(" + "--known)"),
      ]),
    ).not.toThrow();
  });

  it("rejects undefined references and explains the invalid namespace", () => {
    const result = spawnSync(
      process.execPath,
      [checker, "--root", fixture("color: var(" + "--color-does-not-exist)")],
      { encoding: "utf8" },
    );
    expect(result.status).toBe(1);
    expect(result.stderr).toContain("var(" + "--color-does-not-exist)");
    expect(result.stderr).toContain("宣告會被丟棄");
    expect(result.stderr).toContain("沒有 --color-* 命名空間");
  });

  it("rejects fallbacks by default and permits only the migration flag", () => {
    const root = fixture("color: var(" + "--missing, crimson)");
    const rejected = spawnSync(process.execPath, [checker, "--root", root], {
      encoding: "utf8",
    });
    expect(rejected.status).toBe(1);
    expect(rejected.stderr).toContain("WARN");
    expect(rejected.stderr).toContain("繞過 token");
    expect(
      spawnSync(
        process.execPath,
        [checker, "--root", root, "--allow-fallback"],
        { encoding: "utf8" },
      ).status,
    ).toBe(0);
  });
});
