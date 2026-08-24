import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const src = path.resolve("src");

function sourceFiles(directory = src): string[] {
  return fs.readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const item = path.join(directory, entry.name);
    if (entry.isDirectory()) return sourceFiles(item);
    if (!/\.(?:css|ts|vue)$/.test(entry.name) || /\.test\./.test(entry.name)) {
      return [];
    }
    return [item];
  });
}

function relative(file: string): string {
  return path.relative(src, file).replaceAll(path.sep, "/");
}

describe("V2 UI static guardrails", () => {
  it("allows naked hex only in the exact legacy and third-party adapter baseline", () => {
    // These counts pin existing V1 pixels and the literal palettes required by
    // Monaco/xterm APIs. A new file or one extra literal fails; retiring a literal
    // also fails until this documented debt list is deliberately reduced.
    const legacy: Record<string, number> = {
      "components/common/StatusBadge.vue": 12, // D36: V1 screenshot baseline.
      "components/file/PreviewDenied.vue": 6, // Terminal-themed V1 denial state.
      "components/session/NewSessionDialog.vue": 1,
      "composables/useTerminalSession.ts": 4, // xterm options cannot use CSS vars.
      "monaco/setup.ts": 10, // Monaco theme API requires colour strings.
      "views/EnrollmentView.vue": 1,
      "views/IntegrationsView.vue": 5,
      "views/NodeDetailView.vue": 4,
      "views/NodeTunnelsView.vue": 6,
      "views/NodesView.vue": 1,
      "views/SessionWorkspaceView.vue": 9,
    };
    const actual: Record<string, number> = {};
    for (const file of sourceFiles()) {
      if (relative(file).startsWith("theme/")) continue;
      const matches = fs
        .readFileSync(file, "utf8")
        .match(/#[0-9a-fA-F]{3,8}\b/g);
      if (matches?.length) actual[relative(file)] = matches.length;
    }
    expect(actual).toEqual(legacy);
  });

  it("centralizes all three evidence-source wire values", () => {
    const wireValues = /machine_verified|platform_observed|agent_reported/;
    const offenders = sourceFiles()
      .filter((file) => {
        const name = relative(file);
        // `api/dto.ts` joins the two in V2.4, and the distinction is worth stating:
        // it declares the **wire contract** (a union of the values the server may
        // send), not a presentation rule. What the guard is defending is that no
        // *component* decides how a level looks by comparing the string itself —
        // `labels.ts` exports `isMachineVerified` for exactly that.
        return ![
          "api/dto.ts",
          "components/ui/labels.ts",
          "components/ui/SourceBadge.vue",
        ].includes(name);
      })
      .filter((file) => wireValues.test(fs.readFileSync(file, "utf8")))
      .map(relative);
    expect(offenders).toEqual([]);
  });

  it("reserves the human-waiting colour for RunBadge and board cards", () => {
    const allowed = [
      "components/ui/BaseBadge.vue",
      // PX-17 mints `--attention-human` as an alias here rather than copying the
      // hex, which is the whole point of D24: one hue, one definition. A component
      // that wants the human-waiting treatment now asks for `--attention-human`,
      // and this list still keeps it from reaching past the token file for it.
      "theme/tokens.css",
    ];
    const offenders = sourceFiles()
      .filter((file) =>
        /var\(\s*--run-waiting\b/.test(fs.readFileSync(file, "utf8")),
      )
      .map(relative)
      .filter((file) => !allowed.includes(file));
    expect(offenders).toEqual([]);
  });
});
