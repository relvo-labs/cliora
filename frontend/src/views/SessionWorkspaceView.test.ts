import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createRouter, createWebHistory, type Router } from "vue-router";

import { ApiError } from "../api/client";
import type { SessionDetail } from "../api/dto";

// The composable owns a real xterm and a real WebSocket; neither belongs in a
// component test. The mock keeps the shape the view depends on and records the
// calls the tab logic is supposed to make.
const { term } = vi.hoisted(() => ({
  term: {
    mount: vi.fn(),
    connect: vi.fn(async () => {}),
    retry: vi.fn(),
    takeover: vi.fn(),
    disconnect: vi.fn(),
    dispose: vi.fn(),
    fit: vi.fn(),
    focus: vi.fn(),
    status: { value: "connected" },
    role: { value: "writer" },
    gap: { value: undefined },
    exit: { value: undefined },
    lastError: { value: undefined },
    canRetry: { value: false },
  },
}));
vi.mock("../composables/useTerminalSession", () => ({
  useTerminalSession: () => term,
}));

// The file tree owns its own fetching; here it only needs to emit.
vi.mock("../components/file/FileTree.vue", () => ({
  default: {
    name: "FileTree",
    emits: ["open", "clear"],
    template: `<div class="file-tree">
      <button class="open-a" @click="$emit('open', 'src/app.py')">a</button>
      <button class="open-b" @click="$emit('open', 'docs/readme.md')">b</button>
      <button class="clear" @click="$emit('clear')">c</button>
    </div>`,
  },
}));
// PreviewPane is loaded through defineAsyncComponent (it drags Monaco in), so
// the mocked module is resolved at runtime and both Vue and test-utils probe it
// for internal markers (__isTeleport, __v_isVNode, name, …). A vi.mock factory
// result throws on every key it did not declare, so the module is returned as a
// proxy that answers "defined, undefined" instead of playing whack-a-mole.
vi.mock("../components/file/PreviewPane.vue", () => {
  const module = {
    // Without this, `defineAsyncComponent` does not recognise the result as a
    // module and hands Vue the namespace instead of the component.
    __esModule: true,
    default: { name: "PreviewPane", template: "<div class='preview' />" },
  };
  return new Proxy(module, {
    has: () => true,
    get: (target, key) => target[key as keyof typeof module],
  });
});

import * as auth from "../stores/auth";
import SessionWorkspaceView from "./SessionWorkspaceView.vue";

const ID = "44444444-4444-4444-8444-444444444444";
const SHELL_ID = "55555555-5555-4555-8555-555555555555";

function session(overrides: Partial<SessionDetail> = {}): SessionDetail {
  return {
    id: ID,
    node_id: "11111111-1111-1111-1111-111111111111",
    user_id: "22222222-2222-2222-2222-222222222222",
    name: "refactor-api",
    runtime: "claude",
    workspace: "/srv/work/api",
    status: "running",
    rows: 24,
    columns: 80,
    started_at: "2026-07-31T00:00:00Z",
    last_activity_at: "2026-07-31T00:01:00Z",
    exit_code: null,
    error_message: null,
    capabilities: {
      can_terminate: true,
      can_takeover: true,
      can_browse_files: true,
      can_open_shell: false,
    },
    ...overrides,
  } as SessionDetail;
}

function testRouter(): Router {
  return createRouter({
    history: createWebHistory(),
    routes: [
      {
        path: "/sessions",
        name: "sessions",
        component: { template: "<div/>" },
      },
      {
        path: "/sessions/:id",
        name: "session-workspace",
        component: SessionWorkspaceView,
      },
    ],
  });
}

const shellApi = {
  openShell: vi.fn(),
  terminateSession: vi.fn(async () => ({})),
};

async function render(getSession: ReturnType<typeof vi.fn>) {
  vi.spyOn(auth, "api").mockReturnValue({
    getSession,
    attachSession: vi.fn(async () => ({ ticket: "t" })),
    openShell: shellApi.openShell,
    terminateSession: shellApi.terminateSession,
  } as never);
  const router = testRouter();
  router.push(`/sessions/${ID}`);
  await router.isReady();
  const wrapper = mount(SessionWorkspaceView, {
    props: { id: ID },
    global: {
      plugins: [router],
      stubs: { AppLayout: { template: "<div><slot /></div>" } },
    },
  });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  setActivePinia(createPinia());
  shellApi.openShell.mockReset();
  shellApi.openShell.mockResolvedValue({
    ...session(),
    id: SHELL_ID,
    runtime: "shell",
  });
  shellApi.terminateSession.mockReset();
  shellApi.terminateSession.mockResolvedValue({});
  Object.values(term).forEach((value) => {
    if (typeof value === "function")
      (value as ReturnType<typeof vi.fn>).mockClear();
  });
});
afterEach(() => vi.restoreAllMocks());

describe("SessionWorkspaceView — centre tabs", () => {
  it("starts on CLI with no preview tab", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs).toHaveLength(1);
    expect(tabs[0].text()).toBe("CLI");
    expect(wrapper.find("#panel-cli").exists()).toBe(true);
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
  });

  it("opening a file adds one tab, labelled with the basename, and selects it", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    await wrapper.get(".open-a").trigger("click");

    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs).toHaveLength(2);
    expect(tabs[1].text()).toBe("app.py");
    expect(tabs[1].attributes("title")).toBe("src/app.py");
    expect(tabs[1].attributes("aria-selected")).toBe("true");
  });

  // D2: one preview at a time. A second file replaces the first tab's content
  // rather than growing the bar.
  it("opening a second file reuses the same tab", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    await wrapper.get(".open-a").trigger("click");
    await wrapper.get(".open-b").trigger("click");

    const tabs = wrapper.findAll('[role="tab"]');
    expect(tabs).toHaveLength(2);
    expect(tabs[1].text()).toBe("readme.md");
  });

  // D4: the terminal panel is hidden, never unmounted — otherwise the socket
  // and the scrollback go with it.
  it("keeps the terminal panel mounted while the preview is shown", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    await wrapper.get(".open-a").trigger("click");

    const cli = wrapper.find("#panel-cli");
    expect(cli.exists()).toBe(true);
    expect(cli.attributes("style")).toContain("display: none");
    expect(term.dispose).not.toHaveBeenCalled();
  });

  it("re-measures the terminal when the CLI tab comes back", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    await wrapper.get(".open-a").trigger("click");
    term.fit.mockClear();
    term.focus.mockClear();

    await wrapper.findAll('[role="tab"]')[0].trigger("click");
    await flushPromises();

    expect(term.fit).toHaveBeenCalledOnce();
    expect(term.focus).toHaveBeenCalledOnce();
  });

  it("closing the preview tab returns to CLI and drops the panel", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    await wrapper.get(".open-a").trigger("click");
    await wrapper.get(".close").trigger("click");

    expect(wrapper.findAll('[role="tab"]')).toHaveLength(1);
    expect(wrapper.find("#panel-preview").exists()).toBe(false);
    expect(wrapper.get("#panel-cli").attributes("style")).not.toContain(
      "display: none",
    );
  });

  it("a tree clear (session switch, lost permission) also drops the preview", async () => {
    const wrapper = await render(vi.fn(async () => session()));
    await wrapper.get(".open-a").trigger("click");
    await wrapper.get(".clear").trigger("click");
    expect(wrapper.findAll('[role="tab"]')).toHaveLength(1);
  });
});

describe("SessionWorkspaceView — terminal host lifecycle (WT-02)", () => {
  it("mounts the terminal into the host element on first render", async () => {
    await render(vi.fn(async () => session()));
    expect(term.mount).toHaveBeenCalledOnce();
    expect(term.mount.mock.calls[0][0]).toBeInstanceOf(HTMLElement);
  });

  // The regression this whole ticket exists for: a failed load used to replace
  // the workspace (host included), and nothing ever mounted xterm again.
  it("keeps the host mounted through a failed load and a successful retry", async () => {
    const getSession = vi
      .fn()
      .mockRejectedValueOnce(new ApiError("BOOM", "boom", 500, "req"))
      .mockResolvedValue(session());
    const wrapper = await render(getSession);

    // The terminal host exists even while the error veil is up …
    expect(wrapper.find(".veil").exists()).toBe(true);
    expect(wrapper.find("#panel-cli").exists()).toBe(true);
    const mountsAfterFailure = term.mount.mock.calls.length;
    expect(mountsAfterFailure).toBeGreaterThan(0);

    await wrapper.get(".veil button").trigger("click");
    await flushPromises();

    // … and the same element is still there afterwards, so nothing needs a
    // second mount to become usable again.
    expect(wrapper.find(".veil").exists()).toBe(false);
    expect(wrapper.find("#panel-cli").exists()).toBe(true);
    expect(term.dispose).not.toHaveBeenCalled();
  });

  it("shows the forbidden state without tearing the workspace down", async () => {
    const wrapper = await render(
      vi.fn().mockRejectedValue(new ApiError("FORBIDDEN", "no", 403, "req")),
    );
    expect(wrapper.find(".veil").exists()).toBe(true);
    expect(wrapper.text()).toContain("You do not have permission");
    expect(wrapper.find("#panel-cli").exists()).toBe(true);
  });
});

describe("SessionWorkspaceView — system terminal (WT-08)", () => {
  const withShell = () =>
    vi.fn(async () => {
      const base = session();
      return {
        ...base,
        capabilities: { ...base.capabilities, can_open_shell: true },
      };
    });

  it("shows no TERMINAL tab when the server did not offer one", async () => {
    // can_open_shell already folds in the action, ownership and the node's veto,
    // so a false here must be the end of it — no local re-derivation.
    const wrapper = await render(vi.fn(async () => session()));
    expect(wrapper.findAll('[role="tab"]').map((t) => t.text())).toEqual([
      "CLI",
    ]);
  });

  it("shows the TERMINAL tab when the server offers one, but starts nothing yet", async () => {
    const wrapper = await render(withShell());
    expect(wrapper.findAll('[role="tab"]').map((t) => t.text())).toEqual([
      "CLI",
      "TERMINAL",
    ]);
    // D8: opening the workspace must not consume a session slot on the node.
    expect(shellApi.openShell).not.toHaveBeenCalled();
  });

  it("opens the shell on first activation and warns which boundary it is", async () => {
    const wrapper = await render(withShell());
    await wrapper.findAll('[role="tab"]')[1].trigger("click");
    await flushPromises();

    expect(shellApi.openShell).toHaveBeenCalledOnce();
    expect(shellApi.openShell.mock.calls[0][0]).toBe(ID);
    const panel = wrapper.get("#panel-terminal");
    expect(panel.text()).toContain("不受 workspace");
  });

  it("does not open a second shell when the tab is activated again", async () => {
    const wrapper = await render(withShell());
    const tabs = wrapper.findAll('[role="tab"]');
    await tabs[1].trigger("click");
    await flushPromises();
    await tabs[0].trigger("click");
    await tabs[1].trigger("click");
    await flushPromises();
    expect(shellApi.openShell).toHaveBeenCalledOnce();
  });

  it("closing the tab terminates the session on the node", async () => {
    const wrapper = await render(withShell());
    await wrapper.findAll('[role="tab"]')[1].trigger("click");
    await flushPromises();

    await wrapper.get(".close").trigger("click");
    await flushPromises();

    expect(shellApi.terminateSession).toHaveBeenCalledWith(SHELL_ID);
    expect(wrapper.findAll('[role="tab"]')[0].attributes("aria-selected")).toBe(
      "true",
    );
  });

  it("surfaces a refusal with its own message and a retry", async () => {
    shellApi.openShell.mockRejectedValueOnce(
      new ApiError("SHELL_ALREADY_OPEN", "already open", 409, "req"),
    );
    const wrapper = await render(withShell());
    await wrapper.findAll('[role="tab"]')[1].trigger("click");
    await flushPromises();

    expect(wrapper.get("#panel-terminal").text()).toContain("already open");

    shellApi.openShell.mockResolvedValueOnce({
      ...session(),
      id: SHELL_ID,
      runtime: "shell",
    });
    await wrapper.get("#panel-terminal").get("button.link").trigger("click");
    await flushPromises();
    expect(wrapper.get("#panel-terminal").text()).not.toContain("already open");
  });
});
