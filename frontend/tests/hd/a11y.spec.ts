import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { mkdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";

import {
  PROJECT,
  SCREENS,
  assertResolved,
  resolveDrawerTasks,
  signIn,
  withTasks,
} from "./screens";

// HD-04, the **automatic half** (plan/27/04 §2). Eight screens, WCAG 2.2 AA, and the
// threshold is zero `critical` and zero `serious`.
//
// **What this suite cannot see is listed in `plan/27/04` §3 and is not a formality.**
// axe finds contrast, missing labels, wrong roles and absent landmarks. It does not find
// whether the focus order matches the visual one, whether a state change was announced,
// whether the drag has a keyboard equivalent, whether 200% zoom produces a horizontal
// scrollbar, whether `prefers-reduced-motion` is honoured, or whether attention is
// distinguishable in greyscale. A report that is green here and silent about those six
// reads as "the screens are accessible", which is a stronger claim than was tested.
//
//   cd frontend && E2E_HD_PROJECT=<uuid> npx playwright test --config tests/hd/playwright.config.ts a11y

const OUT = resolve(process.cwd(), "..", "artifacts/hd/local/w1");

// Recorded for every screen, failed on for two. `moderate` and `minor` counts go into the
// release note: "we know there are N" and "we did not look" are different sentences.
const BLOCKING = new Set(["critical", "serious"]);

interface Row {
  screen: string;
  url: string;
  critical: number;
  serious: number;
  moderate: number;
  minor: number;
  violations: Array<{
    id: string;
    impact: string | null;
    nodes: number;
    help: string;
    /** The failing elements, with axe's own explanation of *why* each failed.
     *  Without these the report says "5 contrast violations" and the person fixing it
     *  has to reproduce the run to learn which five. A report that requires re-running
     *  the tool is a score, not a report. */
    targets: Array<{ target: string; summary: string }>;
  }>;
}

test.describe("accessibility — WCAG 2.2 AA", () => {
  test.skip(PROJECT === "", "set E2E_HD_PROJECT to the seeded project id");
  test.beforeAll(() => mkdirSync(OUT, { recursive: true }));

  test("eight screens have no critical or serious violations", async ({
    page,
  }) => {
    test.setTimeout(180_000);
    await signIn(page);
    const tasks = await resolveDrawerTasks(page, PROJECT);

    const rows: Row[] = [];
    const failures: string[] = [];

    for (const screen of SCREENS) {
      const url = withTasks(screen.path(PROJECT), tasks);
      assertResolved(screen.id, url);
      await page.goto(url);
      await screen.ready(page);

      const results = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
        .analyze();

      const count = (impact: string) =>
        results.violations.filter((violation) => violation.impact === impact)
          .length;
      const row: Row = {
        screen: screen.id,
        url,
        critical: count("critical"),
        serious: count("serious"),
        moderate: count("moderate"),
        minor: count("minor"),
        violations: results.violations.map((violation) => ({
          id: violation.id,
          impact: violation.impact ?? null,
          nodes: violation.nodes.length,
          help: violation.help,
          targets: violation.nodes.map((node) => ({
            target: node.target.join(" "),
            summary: (node.failureSummary ?? "").replace(/\s+/g, " ").trim(),
          })),
        })),
      };
      rows.push(row);

      const blocking = results.violations.filter(
        (violation) => violation.impact && BLOCKING.has(violation.impact),
      );
      if (blocking.length > 0) {
        failures.push(
          `${screen.id}: ${blocking
            .map(
              (violation) =>
                `${violation.id} (${violation.impact}, ${violation.nodes.length} nodes)`,
            )
            .join(", ")}`,
        );
      }
    }

    // Written **before** the assertion, so a failing run still leaves the report that
    // says what to fix. A suite whose evidence only appears when it passes is a suite
    // nobody can use to get to green.
    writeFileSync(
      resolve(OUT, "axe-after.json"),
      `${JSON.stringify({ screens: rows }, null, 2)}\n`,
    );

    expect(failures, failures.join("\n")).toEqual([]);
  });
});
