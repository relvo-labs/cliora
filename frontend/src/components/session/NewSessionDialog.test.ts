import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { nextTick } from "vue";

import type {
  NodeDetail,
  NodeSummary,
  RecentWorkspace,
  WorkspaceFavorite,
} from "../../api/dto";

const NODE = "11111111-1111-1111-1111-111111111111";

// One fake Central for the whole file. Each test sets `impl` before mounting, so a
// dialog is always exercised through the same code path the browser uses.
const { impl } = vi.hoisted(() => ({
  impl: {
    listFavorites: null as null | (() => Promise<WorkspaceFavorite[]>),
    listRecentWorkspaces: null as null | (() => Promise<RecentWorkspace[]>),
    addFavorite: null as null | ((input: unknown) => Promise<unknown>),
    removeFavorite: null as null | ((id: string) => Promise<void>),
  },
}));

vi.mock("../../stores/auth", () => ({
  api: () => ({
    listFavorites: () => impl.listFavorites!(),
    listRecentWorkspaces: () => impl.listRecentWorkspaces!(),
    addFavorite: (input: unknown) => impl.addFavorite!(input),
    removeFavorite: (id: string) => impl.removeFavorite!(id),
    listNodes: async (): Promise<NodeSummary[]> => [nodeSummary()],
    getNode: async (): Promise<NodeDetail> => nodeDetail(),
  }),
}));

import NewSessionDialog from "./NewSessionDialog.vue";

function nodeSummary(): NodeSummary {
  return {
    id: NODE,
    name: "vm",
    hostname: "vm",
    os: "linux",
    architecture: "amd64",
    status: "online",
    is_enabled: true,
    daemon_version: "0.1.0",
    last_heartbeat_at: "2026-07-25T00:00:00Z",
    session_count: 0,
  } as unknown as NodeSummary;
}

function nodeDetail(): NodeDetail {
  return {
    ...nodeSummary(),
    runtimes: [{ runtime: "claude", available: true }],
    workspace_roots: [{ path: "/home/neil/projects", is_enabled: true }],
  } as unknown as NodeDetail;
}

function favorite(over: Partial<WorkspaceFavorite> = {}): WorkspaceFavorite {
  return {
    id: "fav-1",
    node_id: NODE,
    node_name: "vm",
    path: "/home/neil/projects/app",
    display_name: null,
    created_at: "2026-07-01T00:00:00Z",
    usability: "usable",
    ...over,
  };
}

function recent(over: Partial<RecentWorkspace> = {}): RecentWorkspace {
  return {
    node_id: NODE,
    node_name: "vm",
    path: "/home/neil/projects/api",
    last_used_at: "2026-07-01T00:00:00Z",
    node_online: true,
    node_enabled: true,
    ...over,
  };
}

/** Mount closed, then open — the way the parent drives it.
 *
 * `open` is watched without `immediate`, so mounting already-open would never run
 * the dialog's load at all and every shortcut assertion would pass against an
 * untouched store. Tests have to reproduce the false -> true transition.
 */
async function open() {
  const wrapper = mount(NewSessionDialog, { props: { open: false } });
  await wrapper.setProps({ open: true });
  await flush();
  return wrapper;
}

/** Open and select the node, letting both fetch chains settle. */
async function openWithNodeSelected() {
  const wrapper = await open();
  await wrapper.find("select").setValue(NODE);
  await flush();
  return wrapper;
}

async function flush(): Promise<void> {
  for (let i = 0; i < 6; i += 1) {
    await nextTick();
    await Promise.resolve();
  }
}

describe("NewSessionDialog shortcuts", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
    impl.listFavorites = async () => [];
    impl.listRecentWorkspaces = async () => [];
    impl.addFavorite = async () => favorite();
    impl.removeFavorite = async () => undefined;
  });

  it("does not show the shortcut region until a node is chosen", async () => {
    const wrapper = await open();
    // A path only means something on one machine, so there is nothing to offer yet.
    expect(wrapper.find('[aria-label="Shortcuts"]').exists()).toBe(false);
  });

  it("lists recents and favourites for the selected node only", async () => {
    impl.listFavorites = async () => [
      favorite(),
      favorite({ id: "other", node_id: "999", path: "/elsewhere/x" }),
    ];
    impl.listRecentWorkspaces = async () => [
      recent(),
      recent({ node_id: "999", path: "/elsewhere/y" }),
    ];
    const wrapper = await openWithNodeSelected();

    const text = wrapper.find('[aria-label="Shortcuts"]').text();
    expect(text).toContain("/home/neil/projects/app");
    expect(text).toContain("/home/neil/projects/api");
    expect(text).not.toContain("/elsewhere/x");
    expect(text).not.toContain("/elsewhere/y");
  });

  it("fills the workspace field when a shortcut is clicked", async () => {
    impl.listRecentWorkspaces = async () => [recent()];
    const wrapper = await openWithNodeSelected();

    const buttons = wrapper.findAll("button.shortcut");
    await buttons[0].trigger("click");

    const input = wrapper.find(
      'input[placeholder="/path/inside/an/allowed/root"]',
    );
    expect((input.element as HTMLInputElement).value).toBe(
      "/home/neil/projects/api",
    );
  });

  it("shows the empty state for each group separately", async () => {
    // Both groups can legitimately be empty on a fresh account, and each says so —
    // an absent group would read as a broken dialog.
    const wrapper = await openWithNodeSelected();
    const text = wrapper.find('[aria-label="Shortcuts"]').text();
    expect(text).toContain("No recent workspaces on this node yet.");
    expect(text).toContain("No favourites yet.");
  });

  it("offers a retry when the shortcut fetch fails", async () => {
    impl.listFavorites = async () => {
      throw new Error("boom");
    };
    const wrapper = await openWithNodeSelected();
    const region = wrapper.find('[aria-label="Shortcuts"]');
    expect(region.text()).toContain("Could not load shortcuts.");
    expect(region.find("button.link").exists()).toBe(true);
  });

  it("hides the whole region when the role has no session.create", async () => {
    const { ApiError } = await import("../../api/client");
    impl.listFavorites = async () => {
      throw new ApiError("FORBIDDEN", "no", 403);
    };
    const wrapper = await openWithNodeSelected();
    // No retry button either: retrying a permission the role does not hold would
    // never succeed.
    expect(wrapper.find('[aria-label="Shortcuts"]').exists()).toBe(false);
  });

  it("marks an offline node's recent entry as unusable and refuses the click", async () => {
    impl.listRecentWorkspaces = async () => [recent({ node_online: false })];
    const wrapper = await openWithNodeSelected();

    const shortcut = wrapper.find("button.shortcut");
    expect(shortcut.text()).toContain("Node is offline");
    // Shown rather than hidden (FR-NODE-002), but not selectable.
    expect(shortcut.attributes("disabled")).toBeDefined();
  });

  it("gives each unusable favourite its own reason", async () => {
    impl.listFavorites = async () => [
      favorite({ id: "a", path: "/p/a", usability: "node_offline" }),
      favorite({ id: "b", path: "/p/b", usability: "node_disabled" }),
      favorite({ id: "c", path: "/p/c", usability: "outside_allowed_root" }),
    ];
    const wrapper = await openWithNodeSelected();

    const text = wrapper.find('[aria-label="Shortcuts"]').text();
    expect(text).toContain("Node is offline");
    expect(text).toContain("Node is disabled");
    expect(text).toContain("No longer inside an allowed root");
  });

  it("offers removal only for a favourite that can never work again", async () => {
    // An offline node recovers on its own; a path outside every allowed root does
    // not, so removing it is the only useful next step.
    impl.listFavorites = async () => [
      favorite({ id: "off", path: "/p/off", usability: "node_offline" }),
      favorite({
        id: "gone",
        path: "/p/gone",
        usability: "outside_allowed_root",
      }),
    ];
    const removed: string[] = [];
    impl.removeFavorite = async (id: string) => {
      removed.push(id);
    };
    const wrapper = await openWithNodeSelected();

    const removeButtons = wrapper.findAll("button.link");
    expect(removeButtons).toHaveLength(1);
    await removeButtons[0].trigger("click");
    await flush();
    expect(removed).toEqual(["gone"]);
  });

  it("reflects the favourite state of the current path with aria-pressed", async () => {
    impl.listFavorites = async () => [
      favorite({ path: "/home/neil/projects" }),
    ];
    const wrapper = await openWithNodeSelected();
    // Selecting the node pre-fills the first enabled root, which is favourited.
    const star = wrapper.find("button.star");
    expect(star.attributes("aria-pressed")).toBe("true");
    expect(star.attributes("aria-label")).toContain("Remove");
  });

  it("saves the typed path and turns the star on", async () => {
    const wrapper = await openWithNodeSelected();
    const input = wrapper.find(
      'input[placeholder="/path/inside/an/allowed/root"]',
    );
    await input.setValue("/home/neil/projects/new");
    const sent: unknown[] = [];
    impl.addFavorite = async (body: unknown) => {
      sent.push(body);
      return favorite({ id: "saved", path: "/home/neil/projects/new" });
    };

    await wrapper.find("button.star").trigger("click");
    await flush();

    expect(sent).toEqual([
      {
        node_id: NODE,
        path: "/home/neil/projects/new",
        display_name: null,
      },
    ]);
    expect(wrapper.find("button.star").attributes("aria-pressed")).toBe("true");
  });

  it("reports why a refused favourite was not saved and leaves the star off", async () => {
    const { ApiError } = await import("../../api/client");
    const wrapper = await openWithNodeSelected();
    await wrapper
      .find('input[placeholder="/path/inside/an/allowed/root"]')
      .setValue("/etc");
    impl.addFavorite = async () => {
      throw new ApiError("WORKSPACE_OUTSIDE_ALLOWED_ROOT", "outside", 400);
    };

    await wrapper.find("button.star").trigger("click");
    await flush();

    expect(wrapper.find('[role="alert"]').text()).toContain(
      "not inside an allowed root",
    );
    // The rollback has to be visible: a star left on would claim the refusal saved.
    expect(wrapper.find("button.star").attributes("aria-pressed")).toBe(
      "false",
    );
  });

  it("disables the star while there is no path to save", async () => {
    const wrapper = await open();
    expect(wrapper.find("button.star").attributes("disabled")).toBeDefined();
  });

  it("keeps every shortcut reachable by keyboard", async () => {
    // The list is buttons in a list, not hover-only affordances: a11y requirement
    // from the ticket, and the reason `.shortcut` is a <button> rather than a <div>.
    impl.listRecentWorkspaces = async () => [recent()];
    impl.listFavorites = async () => [favorite()];
    const wrapper = await openWithNodeSelected();

    const items = wrapper.findAll('[aria-label="Shortcuts"] li');
    expect(items.length).toBe(2);
    for (const item of items) {
      expect(item.find("button").exists()).toBe(true);
    }
  });
});
