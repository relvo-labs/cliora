import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope, ref } from "vue";

import type { FileContent } from "../api/dto";

// --- Monaco mock: tracks every model and editor so the leak gate can assert
// that rapid switching neither accumulates models nor rebuilds the editor. ---
const { store } = vi.hoisted(() => ({
  store: {
    models: [] as Array<{
      uri: string;
      value: string;
      language: string;
      disposed: boolean;
    }>,
    editors: [] as Array<Record<string, unknown>>,
    themes: [] as string[],
  },
}));

vi.mock("../monaco/setup", () => {
  function makeModel(uri: string, value: string, language: string) {
    const model = {
      uri,
      value,
      language,
      disposed: false,
      getValue: () => model.value,
      setValue: (next: string) => {
        model.value = next;
      },
      dispose: () => {
        model.disposed = true;
      },
    };
    store.models.push(model);
    return model;
  }
  const monaco = {
    Uri: {
      from: (parts: { scheme: string; path: string; query: string }) =>
        `${parts.scheme}:${parts.query}${parts.path}`,
    },
    editor: {
      defineTheme: (name: string) => store.themes.push(name),
      create: (_el: unknown, options: Record<string, unknown>) => {
        let current: ReturnType<typeof makeModel> | null = null;
        const editor = {
          options,
          disposed: false,
          triggered: [] as string[],
          getModel: () => current,
          setModel: (model: ReturnType<typeof makeModel> | null) => {
            current = model;
          },
          updateOptions: (next: Record<string, unknown>) =>
            Object.assign(options, next),
          trigger: (_src: string, id: string) => editor.triggered.push(id),
          focus: () => {},
          dispose: () => {
            editor.disposed = true;
          },
        };
        store.editors.push(editor as unknown as Record<string, unknown>);
        return editor;
      },
      createModel: (value: string, language: string, uri: string) =>
        makeModel(uri, value, language),
      getModel: (uri: string) =>
        store.models.find((m) => m.uri === uri && !m.disposed) ?? null,
      setModelLanguage: (model: { language: string }, language: string) => {
        model.language = language;
      },
    },
  };
  return {
    PREVIEW_THEME: "cliora-preview",
    setupMonaco: () => monaco,
    monacoLanguage: (hint?: string) => hint ?? "plaintext",
    monacoWorkerCount: () => 0,
  };
});

import { MODEL_CACHE_LIMIT, useMonacoModel } from "./useMonacoModel";

function ok(relPath: string, content = `# ${relPath}\n`): FileContent {
  return {
    success: true,
    rel_path: relPath,
    size: content.length,
    modified_at: "2026-07-25T00:00:00Z",
    encoding: "utf-8",
    language_hint: "python",
    content,
  };
}

function denied(
  relPath: string,
  code: string,
  extra: Partial<FileContent> = {},
): FileContent {
  return {
    success: false,
    rel_path: relPath,
    error: { code, reason: extra.error?.reason },
    ...extra,
  };
}

const live = () => store.models.filter((m) => m.disposed === false).length;
const editor = () =>
  store.editors[0] as unknown as {
    getModel: () => { value: string } | null;
    disposed: boolean;
    triggered: string[];
    options: Record<string, unknown>;
  };

let scope: ReturnType<typeof effectScope>;

function mount(
  loader: (relPath: string, signal: AbortSignal) => Promise<FileContent>,
) {
  const sessionId = ref<string | null>("s1");
  let preview!: ReturnType<typeof useMonacoModel>;
  scope = effectScope();
  scope.run(() => {
    preview = useMonacoModel(loader, { sessionId });
  });
  preview.mount(document.createElement("div"));
  return { preview, sessionId };
}

describe("useMonacoModel", () => {
  beforeEach(() => {
    store.models.length = 0;
    store.editors.length = 0;
    store.themes.length = 0;
  });

  afterEach(() => {
    scope?.stop();
  });

  it("creates a read-only editor with the shared workspace theme", async () => {
    const { preview } = mount(async (p) => ok(p));
    expect(editor().options.readOnly).toBe(true);
    expect(editor().options.domReadOnly).toBe(true);
    expect(editor().options.theme).toBe("cliora-preview");
    expect(editor().options.lineNumbers).toBe("on");
    expect(preview.state.value).toBe("idle");
  });

  it("opens a file, attaches its model and exposes its metadata", async () => {
    const { preview } = mount(async (p) => ok(p, "print('hi')\n"));
    await preview.openFile("src/main.py");
    expect(preview.state.value).toBe("ready");
    expect(editor().getModel()?.value).toBe("print('hi')\n");
    expect(preview.meta.value).toMatchObject({
      relPath: "src/main.py",
      language: "python",
      encoding: "utf-8",
    });
  });

  it("reuses a cached model instead of refetching", async () => {
    let loads = 0;
    const { preview } = mount(async (p) => {
      loads += 1;
      return ok(p);
    });
    await preview.openFile("a.py");
    await preview.openFile("b.py");
    await preview.openFile("a.py");
    expect(loads).toBe(2);
    expect(live()).toBe(2);
  });

  it("refresh refetches the same path and replaces the content", async () => {
    let body = "v1\n";
    const { preview } = mount(async (p) => ok(p, body));
    await preview.openFile("a.py");
    body = "v2\n";
    await preview.refresh();
    expect(editor().getModel()?.value).toBe("v2\n");
  });

  it("caps the model cache and disposes evicted models (LRU)", async () => {
    const { preview } = mount(async (p) => ok(p));
    for (let i = 0; i < MODEL_CACHE_LIMIT + 4; i += 1) {
      await preview.openFile(`file${i}.py`);
    }
    expect(preview.modelCount()).toBeLessThanOrEqual(MODEL_CACHE_LIMIT);
    expect(live()).toBeLessThanOrEqual(MODEL_CACHE_LIMIT);
    expect(store.models.filter((m) => m.disposed).length).toBe(4);
  });

  it("leak gate: rapid switching accumulates no models, editors or workers", async () => {
    const { preview } = mount(async (p) => ok(p));
    for (let i = 0; i < 40; i += 1) {
      await preview.openFile(`f${i % 12}.py`);
    }
    // One editor for the whole session (so one worker pool), models bounded.
    expect(store.editors).toHaveLength(1);
    expect(live()).toBeLessThanOrEqual(MODEL_CACHE_LIMIT);
    expect(preview.modelCount()).toBeLessThanOrEqual(MODEL_CACHE_LIMIT);
  });

  it("disposes every model and clears the view when the session changes", async () => {
    const { preview, sessionId } = mount(async (p) => ok(p));
    await preview.openFile("a.py");
    await preview.openFile("b.py");
    expect(live()).toBe(2);

    sessionId.value = "s2";
    await Promise.resolve();
    expect(live()).toBe(0);
    expect(editor().getModel()).toBeNull();
    expect(preview.state.value).toBe("idle");
    expect(preview.currentPath.value).toBeNull();
  });

  it("disposes models and the editor when the scope is torn down", async () => {
    const { preview } = mount(async (p) => ok(p));
    await preview.openFile("a.py");
    scope.stop();
    expect(live()).toBe(0);
    expect(editor().disposed).toBe(true);
  });

  it("renders a sensitive denial with no content and no model", async () => {
    const { preview } = mount(async (p) =>
      denied(p, "FILE_DENIED", {
        error: { code: "FILE_DENIED", reason: "dotenv" },
      }),
    );
    await preview.openFile("config/.env");
    expect(preview.state.value).toBe("denied");
    expect(preview.denial.value).toMatchObject({
      code: "FILE_DENIED",
      reason: "dotenv",
    });
    expect(editor().getModel()).toBeNull();
    expect(live()).toBe(0);
  });

  it("carries size and mime for binary and oversize denials", async () => {
    const payloads: Record<string, FileContent> = {
      "logo.png": denied("logo.png", "FILE_BINARY", {
        error: { code: "FILE_BINARY" },
        size: 4096,
        mime: "application/octet-stream",
        modified_at: "2026-07-25T00:00:00Z",
      }),
      "big.log": denied("big.log", "FILE_TOO_LARGE", {
        error: { code: "FILE_TOO_LARGE" },
        size: 5 * 1024 * 1024,
      }),
    };
    const { preview } = mount(async (p) => payloads[p]);
    await preview.openFile("logo.png");
    expect(preview.denial.value).toMatchObject({
      code: "FILE_BINARY",
      size: 4096,
      mime: "application/octet-stream",
    });
    await preview.openFile("big.log");
    expect(preview.denial.value).toMatchObject({
      code: "FILE_TOO_LARGE",
      size: 5 * 1024 * 1024,
    });
  });

  it("clears previously shown content when a file becomes denied on refresh", async () => {
    let allowed = true;
    const { preview } = mount(async (p) =>
      allowed
        ? ok(p, "SECRET_KEY=placeholder\n")
        : denied(p, "FILE_DENIED", {
            error: { code: "FILE_DENIED", reason: "dotenv" },
          }),
    );
    await preview.openFile("app.conf");
    expect(editor().getModel()?.value).toBe("SECRET_KEY=placeholder\n");
    const model = store.models[0];

    // The file was replaced on the node with a sensitive one.
    allowed = false;
    await preview.refresh();

    expect(preview.state.value).toBe("denied");
    expect(editor().getModel()).toBeNull();
    expect(model.disposed).toBe(true);
    expect(live()).toBe(0);
  });

  it("ignores a superseded response when the user switches file mid-load", async () => {
    const gates: Record<string, (value: FileContent) => void> = {};
    const { preview } = mount(
      (p) => new Promise<FileContent>((resolve) => (gates[p] = resolve)),
    );
    const first = preview.openFile("slow.py");
    const second = preview.openFile("fast.py");
    gates["fast.py"](ok("fast.py", "fast\n"));
    await second;
    gates["slow.py"](ok("slow.py", "slow\n"));
    await first;

    expect(preview.currentPath.value).toBe("fast.py");
    expect(editor().getModel()?.value).toBe("fast\n");
  });

  it("surfaces a load failure as an error state with no content", async () => {
    const { preview } = mount(async () => {
      throw new Error("Cannot access path");
    });
    await preview.openFile("gone.py");
    expect(preview.state.value).toBe("error");
    expect(preview.errorMessage.value).toBe("Cannot access path");
    expect(editor().getModel()).toBeNull();
  });

  it("close clears the pane without disposing the cache", async () => {
    const { preview } = mount(async (p) => ok(p));
    await preview.openFile("a.py");
    preview.close();
    expect(preview.state.value).toBe("idle");
    expect(editor().getModel()).toBeNull();
    // The model stays cached for a cheap re-open.
    expect(preview.modelCount()).toBe(1);
  });

  it("exposes read-only affordances: word wrap, find and goto line", async () => {
    const { preview } = mount(async (p) => ok(p));
    await preview.openFile("a.py");
    expect(preview.wordWrap.value).toBe(true);
    preview.toggleWordWrap();
    expect(preview.wordWrap.value).toBe(false);
    expect(editor().options.wordWrap).toBe("off");
    preview.find();
    preview.gotoLine();
    expect(editor().triggered).toEqual([
      "actions.find",
      "editor.action.gotoLine",
    ]);
  });

  it("copies only a previewable file's content", async () => {
    const written: string[] = [];
    Object.defineProperty(navigator, "clipboard", {
      configurable: true,
      value: {
        writeText: async (text: string) => {
          written.push(text);
        },
      },
    });
    const { preview } = mount(async (p) =>
      p === "a.py"
        ? ok(p, "body\n")
        : denied(p, "FILE_DENIED", {
            error: { code: "FILE_DENIED", reason: "dotenv" },
          }),
    );
    await preview.openFile("a.py");
    expect(await preview.copyAll()).toBe(true);
    expect(written).toEqual(["body\n"]);

    await preview.openFile(".env");
    expect(await preview.copyAll()).toBe(false);
    expect(written).toEqual(["body\n"]);
  });
});
