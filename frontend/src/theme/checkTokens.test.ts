import { execFileSync, spawnSync } from "node:child_process";
import { mkdtempSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
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

  it("does not match a var() inside a CSS comment", () => {
    // **The checker used to fail on its own explanation.** A CSS comment saying that a
    // reference to an invented token would be unresolvable was itself reported as an
    // unresolvable reference — and the cheapest way to green that is to delete the
    // sentence saying why the rule exists, which is the failure `plan/18/09` §3 item 15
    // records for three V2.2 gates.
    //
    // Only `/* */` is stripped, which is what a `.css` file or a `.vue` style block has.
    // A `//` line comment is not a CSS comment at all, so this file keeps its existing
    // idiom for naming a token in prose: split the literal, as every case above does.
    const root = fixture(
      "/* a var(" +
        "--not-a-real-token) here would be dropped */\n" +
        "color: var(" +
        "--known)",
    );
    expect(
      spawnSync(process.execPath, [checker, "--root", root], {
        encoding: "utf8",
      }).status,
    ).toBe(0);
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

/** `--name: value;` pairs from the real token file, in declaration order. */
function declared(): Map<string, string> {
  const source = readFileSync(
    resolve(import.meta.dirname, "tokens.css"),
    "utf8",
  );
  const pairs = new Map<string, string>();
  for (const match of source.matchAll(/^\s*(--[a-z0-9-]+)\s*:\s*([^;]+);/gim)) {
    pairs.set(match[1], match[2].trim());
  }
  return pairs;
}

describe("V2-P1 work vocabulary (PX-17)", () => {
  // The checker above proves a `var()` reference resolves. It cannot prove the
  // *right* tokens exist, nor that the lifecycle aliases still point at the stage
  // colours — a hand-copied hex would satisfy every other guard in this file while
  // letting the same card render one colour on the board and another in a list.
  it("defines five attention levels and five lifecycle aliases", () => {
    const tokens = declared();
    expect(
      [...tokens.keys()].filter((name) => name.startsWith("--attention-")),
    ).toEqual([
      "--attention-human",
      "--attention-approval",
      "--attention-blocked",
      "--attention-failed",
      "--attention-warning",
    ]);
    expect(
      [...tokens.keys()].filter((name) => name.startsWith("--work-")),
    ).toEqual([
      "--work-backlog",
      "--work-ready",
      "--work-progress",
      "--work-review",
      "--work-done",
    ]);
  });

  it("keeps lifecycle tokens as aliases of the stage colours, never copies", () => {
    const tokens = declared();
    expect({
      "--work-backlog": tokens.get("--work-backlog"),
      "--work-ready": tokens.get("--work-ready"),
      "--work-progress": tokens.get("--work-progress"),
      "--work-review": tokens.get("--work-review"),
      "--work-done": tokens.get("--work-done"),
    }).toEqual({
      "--work-backlog": "var(--stage-backlog)",
      "--work-ready": "var(--stage-ready)",
      "--work-progress": "var(--stage-implementing)",
      "--work-review": "var(--stage-verify)",
      "--work-done": "var(--stage-done)",
    });
  });

  it("gives level 1 the existing waiting hue rather than a second orange", () => {
    // plan/19 D24: --run-waiting is the human-action-required treatment and nothing
    // else. A literal #d2691e here would be a copy that drifts.
    expect(declared().get("--attention-human")).toBe("var(--run-waiting)");
  });
});
