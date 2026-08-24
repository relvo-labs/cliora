import { mount } from "@vue/test-utils";
import { describe, expect, it, vi } from "vitest";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { defineComponent, h } from "vue";

import type { WorkItemCard as Card } from "../../api/dto";
import BoardColumn from "./components/BoardColumn.vue";
import MoveDialog from "./components/MoveDialog.vue";
import WorkItemCardView from "./components/WorkItemCard.vue";
import {
  BUILDER_FIELDS,
  type BuilderRow,
  buildFilter,
  readBuilder,
} from "./filterBuilder";
import ReadyTransitionDialog from "./components/ReadyTransitionDialog.vue";
import WorkItemRow from "./components/WorkItemRow.vue";
import WorkViewToolbar from "./components/WorkViewToolbar.vue";
import { explainMoveFailure } from "./composables/useOptimisticMove";
import { QUICK_FILTERS, RUNTIME_UNAVAILABLE } from "./quickFilters";
import {
  MAX_FILTER_URL_LENGTH,
  decodeFilter,
  encodeFilter,
  isModified,
  readDensity,
  readFullScreen,
  readViewState,
  writeDensity,
  writeFullScreen,
  writeViewState,
} from "./viewState";

// The board's load-bearing behaviours (PX-29…PX-36). Every one of these is silent when
// wrong: a column that counts what it loaded, a chip that rewrites a shared view, a moved
// card that stays put after a refusal, an index sent where a neighbour was meant.

function card(overrides: Partial<Card> = {}): Card {
  return {
    id: "t-1",
    card_ref: "TK-1",
    project_id: "p-1",
    version: 3,
    updated_at: "2026-08-23T00:00:00Z",
    title: "支援 SAML SSO 登入",
    lifecycle: "ready",
    legacy_stage: "ready",
    readiness: "ready",
    risk: "medium",
    delivery: "none",
    execution_status: "not_queued",
    ...overrides,
  };
}

function router(): Router {
  const blank = defineComponent({ render: () => h("div") });
  return createRouter({
    history: createMemoryHistory(),
    routes: [{ path: "/:pathMatch(.*)*", component: blank }],
  });
}

// --- the count -------------------------------------------------------------------

describe("BoardColumn", () => {
  it("shows the server's count, not the number of rows it holds", () => {
    // The upstream plan calls the alternative "the commonest lie on a board like this".
    // Asserted here and pinned again on the server.
    const wrapper = mount(BoardColumn, {
      props: {
        label: "就緒",
        groupKey: "ready",
        count: 348,
        items: [card(), card({ id: "t-2", card_ref: "TK-2" })],
        hasMore: true,
      },
      global: { plugins: [router()] },
    });
    expect(wrapper.get("[data-server-count]").text()).toBe("348");
    expect(wrapper.findAll("[data-card-ref]")).toHaveLength(2);
  });

  it("marks an over-WIP column and refuses nothing", () => {
    // Monstrare's semantics, kept: WIP reports, it does not enforce (ADR 0028).
    const wrapper = mount(BoardColumn, {
      props: {
        label: "進行中",
        groupKey: "in_progress",
        count: 5,
        items: [],
        hasMore: false,
        wipSuggested: 3,
      },
      global: { plugins: [router()] },
    });
    expect(wrapper.get("[data-server-count]").attributes("data-over-wip")).toBe(
      "true",
    );
    expect(wrapper.get("[data-server-count]").text()).toContain("5 / 3");
  });

  it("offers Load more per column, not per page", () => {
    const wrapper = mount(BoardColumn, {
      props: {
        label: "完成",
        groupKey: "done",
        count: 40,
        items: [card()],
        hasMore: true,
        windowNote: "近 7 天 · 共 348",
      },
      global: { plugins: [router()] },
    });
    expect(wrapper.find("[data-load-more='done']").exists()).toBe(true);
    // Done says what window it is showing. A Done count that means "ever" answers a
    // question nobody asked.
    expect(wrapper.text()).toContain("近 7 天");
  });

  it("offers a keyboard move control on every card when writing is allowed", () => {
    const wrapper = mount(BoardColumn, {
      props: {
        label: "就緒",
        groupKey: "ready",
        count: 1,
        items: [card()],
        hasMore: false,
        canWrite: true,
      },
      global: { plugins: [router()] },
    });
    expect(wrapper.find("[data-move-for='TK-1']").exists()).toBe(true);
  });

  it("offers no move control to a reader", () => {
    const wrapper = mount(BoardColumn, {
      props: {
        label: "就緒",
        groupKey: "ready",
        count: 1,
        items: [card()],
        hasMore: false,
      },
      global: { plugins: [router()] },
    });
    expect(wrapper.find("[data-move-for='TK-1']").exists()).toBe(false);
  });
});

// --- the card --------------------------------------------------------------------

describe("WorkItemCard", () => {
  it("outlines a card that is waiting on a person, not only badges it", () => {
    // plan/19 D24's treatment, carried forward: the one state where somebody is being
    // waited on is visible from across the board.
    const wrapper = mount(WorkItemCardView, {
      props: {
        card: card({
          primary_attention: "waiting_for_your_input",
          attention_count: 2,
        }),
      },
    });
    expect(
      wrapper.find("[data-attention='waiting_for_your_input']").exists(),
    ).toBe(true);
    expect(wrapper.get("[data-attention]").text()).toContain("＋1");
  });

  it("caps metadata by density rather than wrapping it", () => {
    // A card whose metadata wraps changes the column's rhythm, and the rhythm is what
    // lets somebody scan forty cards.
    const full = card({
      owner_name: "陳小美",
      risk: "high",
      delivery: "pull_request",
      blocking_count: 2,
      labels: ["sso", "auth"],
    });
    const comfortable = mount(WorkItemCardView, { props: { card: full } });
    const compact = mount(WorkItemCardView, {
      props: { card: full, density: "compact" },
    });
    const count = (text: string) => text.split(" · ").length;
    expect(count(comfortable.get(".meta").text())).toBe(5);
    expect(count(compact.get(".meta").text())).toBe(2);
  });
});

// --- the toolbar ------------------------------------------------------------------

describe("WorkViewToolbar", () => {
  function toolbar(overrides: Record<string, unknown> = {}) {
    return mount(WorkViewToolbar, {
      props: {
        views: [
          {
            id: "v-1",
            name: "Active Work",
            scope: "project",
            is_default: true,
          },
        ],
        activeView: "v-1",
        modified: false,
        activeChips: [],
        search: null,
        filter: null,
        group: "lifecycle",
        order: "rank:asc",
        density: "comfortable",
        layout: "board",
        ...overrides,
      },
      global: { plugins: [router()] },
    });
  }

  it("disables the two runtime chips with a reason rather than answering zero", () => {
    // **The one that matters.** "0 cards with no eligible runner" reads as *fixed*; the
    // truth is that the registry could not be consulted (ADR 0040 §2).
    const wrapper = toolbar({ runtimeAvailable: false });
    const chip = wrapper.get("[data-chip='no-runner']");
    expect(chip.attributes("disabled")).toBeDefined();
    expect(chip.attributes("title")).toBe(RUNTIME_UNAVAILABLE);
    // Said out loud, not only as a tooltip.
    expect(wrapper.get("[data-runtime-note]").text()).toContain(
      RUNTIME_UNAVAILABLE,
    );
    // And the chips that do not need the registry are still usable.
    expect(
      wrapper.get("[data-chip='high-risk']").attributes("disabled"),
    ).toBeUndefined();
  });

  it("offers exactly one chip per runtime-dependent attention level", () => {
    expect(
      QUICK_FILTERS.filter((chip) => chip.needsRuntime).map((chip) => chip.key),
    ).toEqual(["no-runner"]);
  });

  it("shows modified with Save as and Revert, and no Save as without permission", () => {
    const allowed = toolbar({ modified: true, canManageViews: true });
    expect(allowed.get("[data-modified]").text()).toContain("已修改");
    expect(allowed.find("[data-save-as]").exists()).toBe(true);
    expect(allowed.find("[data-revert]").exists()).toBe(true);

    const reader = toolbar({ modified: true, canManageViews: false });
    expect(reader.find("[data-save-as]").exists()).toBe(false);
    // Revert still there: undoing your own temporary filter is not a permission.
    expect(reader.find("[data-revert]").exists()).toBe(true);
  });

  it("says when the filter is not in the link, because the filter still applies", () => {
    const wrapper = toolbar({ filterNotInLink: true });
    expect(wrapper.get("[data-not-in-link]").text()).toContain(
      "未包含在連結中",
    );
  });

  it("names the full-screen toggle distinctly from the panel's own state", () => {
    // Both used to be `data-full-screen`, which made "click the toggle" ambiguous in the
    // browser suite. A selector that resolves to two elements is a test that cannot be
    // written, and the fix belongs in the markup rather than in the selector.
    const wrapper = toolbar();
    expect(wrapper.find("[data-toggle-full-screen]").exists()).toBe(true);
  });

  it("offers attention as a grouping and not as a sort (D92)", () => {
    const wrapper = toolbar();
    const groups = wrapper
      .get("[data-group-selector]")
      .findAll("option")
      .map((option) => option.attributes("value"));
    const orders = wrapper
      .get("[data-order-selector]")
      .findAll("option")
      .map((option) => option.attributes("value"));
    expect(groups).toContain("attention");
    expect(orders.some((value) => value?.startsWith("attention"))).toBe(false);
  });
});

// --- the move dialog -------------------------------------------------------------

describe("MoveDialog", () => {
  it("sends neighbour ids, never an index", async () => {
    // **The payload assertion.** On a filtered board position 3 of the list is not
    // position 3 of the lane, and the defect that produces is a card landing where nobody
    // pointed.
    const moving = card({ id: "t-move", card_ref: "TK-9" });
    const wrapper = mount(MoveDialog, {
      props: {
        card: moving,
        groups: [
          { key: "ready", label: "就緒" },
          { key: "review", label: "審查" },
        ],
        itemsByGroup: {
          ready: [
            card({ id: "a", card_ref: "TK-A" }),
            card({ id: "b", card_ref: "TK-B" }),
            moving,
          ],
          review: [],
        },
      },
    });
    await wrapper.get("[data-move-position]").setValue(2);
    await wrapper.get("[data-move-confirm]").trigger("click");

    const [payload] = wrapper.emitted("confirm")![0] as [
      { previous: Card | null; next: Card | null; groupKey: string },
    ];
    expect(payload.previous?.id).toBe("b");
    expect(payload.next).toBeNull();
    expect(payload.groupKey).toBe("ready");
    expect(payload).not.toHaveProperty("index");
  });

  it("removes the moving card from its own position list", async () => {
    // "Position 3" has to mean the same thing before and after; leaving the card in its
    // own list makes the index shift by one when it moves down.
    const moving = card({ id: "t-move", card_ref: "TK-9" });
    const wrapper = mount(MoveDialog, {
      props: {
        card: moving,
        groups: [{ key: "ready", label: "就緒" }],
        itemsByGroup: { ready: [moving, card({ id: "a", card_ref: "TK-A" })] },
      },
    });
    const labels = wrapper
      .get("[data-move-position]")
      .findAll("option")
      .map((option) => option.text());
    expect(labels).toEqual(["最前面", "在 TK-A 之後"]);
  });

  it("renders nothing until a card is being moved", () => {
    const wrapper = mount(MoveDialog, {
      props: { card: null, groups: [], itemsByGroup: {} },
    });
    expect(wrapper.find("[data-move-dialog]").exists()).toBe(false);
  });
});

// --- the refusal ------------------------------------------------------------------

describe("explainMoveFailure", () => {
  it("tells a version conflict apart from a stale neighbour", async () => {
    // Two different situations with two different recoveries: "somebody edited this card"
    // and "somebody moved the cards around it". A single message would make the board's
    // recovery generic.
    const { ApiError } = await import("../../api/client");
    expect(
      explainMoveFailure(new ApiError("TASK_VERSION_CONFLICT", "x", 409)),
    ).toContain("改過");
    expect(
      explainMoveFailure(new ApiError("RANK_NEIGHBOR_STALE", "x", 409)),
    ).toContain("不相鄰");
  });

  it("names the blocking cards rather than saying the move failed", async () => {
    const { ApiError } = await import("../../api/client");
    const error = new ApiError(
      "TASK_DEPENDENCY_UNSATISFIED",
      "x",
      409,
      undefined,
      {
        blocking_refs: ["TK-3", "TK-7"],
      },
    );
    expect(explainMoveFailure(error)).toContain("TK-3、TK-7");
  });

  it("never returns a bare failure for a known code", async () => {
    const { ApiError } = await import("../../api/client");
    for (const code of [
      "TASK_VERSION_CONFLICT",
      "RANK_NEIGHBOR_STALE",
      "TASK_DEPENDENCY_UNSATISFIED",
      "PROJECT_ARCHIVED",
    ]) {
      expect(
        explainMoveFailure(new ApiError(code, "x", 409, undefined, {})),
      ).not.toBe("移動失敗，請重試。");
    }
  });
});

// --- URL state --------------------------------------------------------------------

describe("view state in the URL", () => {
  it("round-trips a filter through base64url", () => {
    const filter = { field: "risk", op: "in", value: ["high", "critical"] };
    expect(decodeFilter(encodeFilter(filter))).toEqual(filter);
  });

  it("returns null for a filter somebody hand-edited", () => {
    // The unfiltered board with a note, not an error page. The *server* refuses an
    // undecodable filter, which is where a refusal belongs.
    expect(decodeFilter("not-base64!!")).toBeNull();
    expect(decodeFilter(encodeFilter([] as never))).toBeNull();
  });

  it("drops a key rather than setting it empty", () => {
    // `?f=` and no `f` are different requests to the read model, and "no filter" is what
    // an absent key means.
    const query = writeViewState(
      { filter: null, group: null },
      { f: "x", g: "owner" },
    );
    expect(query).not.toHaveProperty("f");
    expect(query).not.toHaveProperty("g");
  });

  it("keeps the open card when the filter changes", () => {
    const query = writeViewState(
      { filter: { field: "risk", op: "eq", value: "high" } },
      {
        task: "t-9",
      },
    );
    expect(query.task).toBe("t-9");
    expect(query.f).toBeTruthy();
  });

  it("leaves an over-long filter out of the URL", () => {
    // The filter still applies; it is the link that does not carry it, and the toolbar
    // says so (D103).
    const huge = {
      field: "owner",
      op: "in",
      value: Array.from(
        { length: 60 },
        () => "00000000-0000-4000-8000-000000000000",
      ),
    };
    expect(encodeFilter(huge).length).toBeGreaterThan(MAX_FILTER_URL_LENGTH);
    expect(writeViewState({ filter: huge }, {})).not.toHaveProperty("f");
  });

  it("reads every key it writes", () => {
    const state = readViewState({
      view: "v-1",
      f: encodeFilter({ field: "risk", op: "eq", value: "high" }),
      g: "owner",
      o: "updated_at:desc",
      task: "t-1",
    });
    expect(state.view).toBe("v-1");
    expect(state.group).toBe("owner");
    expect(state.order).toBe("updated_at:desc");
    expect(state.task).toBe("t-1");
    expect(state.filter).toEqual({ field: "risk", op: "eq", value: "high" });
  });

  it("does not call an untouched view modified when key order differs", () => {
    // Otherwise the toolbar permanently offers "Revert" on a view nobody touched.
    expect(
      isModified(
        { op: "eq", field: "risk", value: "high" },
        {
          field: "risk",
          op: "eq",
          value: "high",
        },
      ),
    ).toBe(false);
    expect(
      isModified(
        { field: "risk", op: "eq", value: "low" },
        {
          field: "risk",
          op: "eq",
          value: "high",
        },
      ),
    ).toBe(true);
  });

  it("keeps density local, because it is a personal preference", () => {
    // And `PX-28` asserts on the server that changing it writes no audit row: auditing a
    // preference turns the audit log into telemetry.
    const store = new Map<string, string>();
    const storage = {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => void store.set(key, value),
    };
    expect(readDensity(storage)).toBe("comfortable");
    writeDensity("compact", storage);
    expect(readDensity(storage)).toBe("compact");
  });
});

// --- search and the filter builder (PX-31) -----------------------------------------

describe("search", () => {
  function toolbar(overrides: Record<string, unknown> = {}) {
    return mount(WorkViewToolbar, {
      props: {
        views: [],
        activeView: null,
        modified: false,
        activeChips: [],
        search: null,
        filter: null,
        group: null,
        order: "rank:asc",
        density: "comfortable",
        layout: "board",
        ...overrides,
      },
      global: { plugins: [router()] },
    });
  }

  it("debounces typing into one emit rather than one per keystroke", async () => {
    vi.useFakeTimers();
    try {
      const view = toolbar();
      const input = view.get("[data-search-input]");
      for (const value of ["匯", "匯出", "匯出速"]) {
        await input.setValue(value);
      }
      // Nothing yet: this is the whole point. Three keystrokes inside the window are one
      // request, not three, and the third is the only one whose answer anybody wants.
      expect(view.emitted("set-search")).toBeUndefined();
      vi.advanceTimersByTime(300);
      expect(view.emitted("set-search")).toEqual([["匯出速"]]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("Enter skips the wait", async () => {
    vi.useFakeTimers();
    try {
      const view = toolbar();
      const input = view.get("[data-search-input]");
      await input.setValue("報表");
      await input.trigger("keydown.enter");
      // No timer advance. Somebody who pressed Enter has finished typing.
      expect(view.emitted("set-search")).toEqual([["報表"]]);
    } finally {
      vi.useRealTimers();
    }
  });

  it("an all-whitespace search emits null, not a space", async () => {
    // `?q=%20` and no `q` have to be the same board, or a stray space in a shared link
    // changes what the person who opened it sees.
    const view = toolbar();
    const input = view.get("[data-search-input]");
    await input.setValue("   ");
    await input.trigger("keydown.enter");
    expect(view.emitted("set-search")).toEqual([[null]]);
    expect(writeViewState({ search: "   " }, {})).not.toHaveProperty("q");
  });

  it("follows the prop when the URL changes underneath it", async () => {
    // Browser Back, or Revert. Without this the box keeps the last thing typed and
    // disagrees with the board it sits above.
    const view = toolbar({ search: "報表" });
    expect(
      (view.get("[data-search-input]").element as HTMLInputElement).value,
    ).toBe("報表");
    await view.setProps({ search: null });
    expect(
      (view.get("[data-search-input]").element as HTMLInputElement).value,
    ).toBe("");
  });

  it("round-trips through the URL", () => {
    const query = writeViewState({ search: "月報" }, {});
    expect(query.q).toBe("月報");
    expect(readViewState(query).search).toBe("月報");
  });
});

describe("filterBuilder", () => {
  it("wraps even a single row in `and`, so the shape never changes", () => {
    // A bare leaf would be legal and one level shallower — and then adding a second row
    // would change the shape, so every reader of `f=` would have to handle both.
    expect(
      buildFilter([{ field: "risk", op: "eq", values: ["high"] }]),
    ).toEqual({
      and: [{ field: "risk", op: "eq", value: "high" }],
    });
  });

  it("sends a scalar for eq and a list for in", () => {
    expect(
      buildFilter([{ field: "risk", op: "in", values: ["high", "critical"] }]),
    ).toEqual({
      and: [{ field: "risk", op: "in", value: ["high", "critical"] }],
    });
  });

  it("coerces is_blocked to a boolean, because the server's field is a bool", () => {
    expect(
      buildFilter([{ field: "is_blocked", op: "eq", values: ["true"] }]),
    ).toEqual({ and: [{ field: "is_blocked", op: "eq", value: true }] });
  });

  it("drops rows with no value rather than sending an empty list", () => {
    // An empty `in` is a filter that matches nothing, and nobody means that by "I have
    // not picked a value yet".
    expect(
      buildFilter([
        { field: "risk", op: "in", values: [] },
        { field: "priority", op: "eq", values: ["high"] },
      ]),
    ).toEqual({ and: [{ field: "priority", op: "eq", value: "high" }] });
    expect(buildFilter([{ field: "risk", op: "in", values: [] }])).toBeNull();
  });

  it("round-trips what it built", () => {
    const rows: BuilderRow[] = [
      { field: "lifecycle", op: "in", values: ["ready", "in_progress"] },
      { field: "risk", op: "eq", values: ["high"] },
    ];
    const read = readBuilder(buildFilter(rows));
    expect(read.representable).toBe(true);
    expect(read.rows).toEqual(rows);
  });

  it("reports a filter it cannot draw instead of rewriting it", () => {
    // The filter still applies — the URL is what the server reads. Rewriting it to
    // whatever the builder *could* express would change somebody's board on open.
    const read = readBuilder({
      or: [{ field: "risk", op: "eq", value: "high" }],
    });
    expect(read).toEqual({ rows: [], representable: false });
    expect(readBuilder({ field: "owner", op: "is_null", value: true })).toEqual(
      {
        rows: [],
        representable: false,
      },
    );
  });

  it("treats an empty filter as representable and empty, not as unreadable", () => {
    expect(readBuilder(null)).toEqual({ rows: [], representable: true });
    expect(readBuilder({})).toEqual({ rows: [], representable: true });
  });

  it("offers no operator a field does not have", () => {
    // `is_blocked` carries `EQUALITY` alone on the server. A dropdown that could build
    // `is_blocked in [true, false]` would be a dropdown that produces a 400.
    const blocked = BUILDER_FIELDS.find(
      (entry) => entry.field === "is_blocked",
    );
    expect(blocked?.ops).toEqual(["eq", "neq"]);
  });
});

// --- the Ready transition and inline rename (PX-30, D97) ---------------------------

describe("ReadyTransitionDialog", () => {
  const LABELS = {
    acceptance_criteria: "驗收標準逐項可檢查",
    dependencies_known: "相依已辨識",
    verification_defined: "驗證方式已定義",
  };

  function dialog(overrides: Record<string, unknown> = {}) {
    return mount(ReadyTransitionDialog, {
      props: {
        cardRef: "TASK-7",
        missing: Object.keys(LABELS),
        labels: LABELS,
        ...overrides,
      },
    });
  }

  it("says out loud that it is not a gate", () => {
    // **The load-bearing sentence.** A person shown a list of missing items assumes it is
    // a barrier, and without this the first one to press through believes they bypassed
    // something. `plan/26/06` §5 makes the wording a requirement, not a nicety.
    const view = dialog();
    expect(view.get("[data-not-a-gate]").text()).toContain("不會阻擋這次移動");
  });

  it("names every missing item and counts them in the heading", () => {
    const view = dialog();
    expect(view.get("[data-ready-dialog] h2").text()).toContain("3");
    for (const label of Object.values(LABELS)) {
      expect(view.text()).toContain(label);
    }
  });

  it("emits the readiness key, not the label, when a row is clicked", () => {
    // The Drawer maps keys to its own fields; a label is for reading. Emitting the label
    // would make this dialog's wording part of an interface contract.
    const view = dialog();
    view.get("[data-fill='dependencies_known']").trigger("click");
    expect(view.emitted("fill")).toEqual([["dependencies_known"]]);
  });

  it("『補齊缺失項』 goes to the first missing item", () => {
    const view = dialog();
    view.get("[data-fill-first]").trigger("click");
    expect(view.emitted("fill")).toEqual([["acceptance_criteria"]]);
  });

  it("shows an unknown key as itself rather than hiding it", () => {
    // A project may carry an item this console's build has no label for. Hiding it would
    // under-report what is missing, which is the one thing this dialog must not do.
    const view = dialog({ missing: ["something_new"], labels: {} });
    expect(view.text()).toContain("something_new");
  });

  it("renders nothing when there is no card", () => {
    expect(dialog({ cardRef: null }).find("[data-ready-dialog]").exists()).toBe(
      false,
    );
  });
});

describe("WorkItemRow inline rename", () => {
  const CARD = {
    id: "t-1",
    card_ref: "TASK-1",
    project_id: "p-1",
    version: 3,
    updated_at: "2026-08-24T00:00:00Z",
    title: "匯出很慢",
    lifecycle: "backlog",
  };

  function row(overrides: Record<string, unknown> = {}) {
    return mount(WorkItemRow, {
      props: { card: CARD as never, canWrite: true, ...overrides },
    });
  }

  it("saves on Enter and carries the card's version", async () => {
    const view = row();
    await view.get("[data-rename-for='TASK-1']").trigger("click");
    const input = view.get("[data-rename-input='TASK-1']");
    await input.setValue("月報匯出很慢");
    await input.trigger("keydown.enter");
    expect(view.emitted("rename")).toEqual([
      [{ card: CARD, title: "月報匯出很慢" }],
    ]);
  });

  it("Escape abandons without writing", async () => {
    // A mistaken double-click needs an exit that is not "save whatever is in the box".
    const view = row();
    await view.get("[data-rename-for='TASK-1']").trigger("click");
    const input = view.get("[data-rename-input='TASK-1']");
    await input.setValue("按錯了");
    await input.trigger("keydown.esc");
    expect(view.emitted("rename")).toBeUndefined();
    expect(view.find("[data-rename-input='TASK-1']").exists()).toBe(false);
  });

  it("an unchanged title is not a write", async () => {
    // Otherwise a stray double-click on every row of a backlog is a PATCH per row and an
    // activity entry per row.
    const view = row();
    await view.get("[data-rename-for='TASK-1']").trigger("click");
    await view.get("[data-rename-input='TASK-1']").trigger("keydown.enter");
    expect(view.emitted("rename")).toBeUndefined();
  });

  it("offers no rename when the view hides the title", () => {
    // `title` is optional on the card because `visible_fields` may drop it, and a rename
    // box pre-filled with "" would silently replace a title nobody could see.
    const view = row({ card: { ...CARD, title: undefined } as never });
    expect(view.find("[data-rename-for='TASK-1']").exists()).toBe(false);
  });

  it("offers no rename or Ready button without write permission", () => {
    const view = row({ canWrite: false });
    expect(view.find("[data-rename-for='TASK-1']").exists()).toBe(false);
    expect(view.find("[data-send-ready='TASK-1']").exists()).toBe(false);
  });

  it("offers 送到就緒 only on a backlog card", () => {
    expect(row().find("[data-send-ready='TASK-1']").exists()).toBe(true);
    const inReady = row({ card: { ...CARD, lifecycle: "ready" } as never });
    expect(inReady.find("[data-send-ready='TASK-1']").exists()).toBe(false);
  });
});

// --- full screen survives a reload (PX-36) -------------------------------------------

describe("full screen", () => {
  function storage(initial: Record<string, string> = {}) {
    const values = { ...initial };
    return {
      getItem: (key: string) => values[key] ?? null,
      setItem: (key: string, value: string) => {
        values[key] = value;
      },
      values,
    };
  }

  it("is remembered locally, not in the URL", () => {
    // Local for the same reason density is: it is a property of *this screen*, not of the
    // board being looked at. A shared link that forced somebody else's board into full
    // screen would be one person's window preference arriving as a surprise — and unlike
    // a filter, there is no sentence anybody says that means it.
    const store = storage();
    writeFullScreen(true, store);
    expect(readFullScreen(store)).toBe(true);
    expect(writeViewState({ view: null }, {})).not.toHaveProperty("fs");
  });

  it("defaults to off, including for a value nobody wrote", () => {
    expect(readFullScreen(storage())).toBe(false);
    expect(readFullScreen(storage({ "cliora.work.fullScreen": "yes" }))).toBe(
      false,
    );
  });

  it("round-trips off as well as on", () => {
    // The failure this catches: storing only the `true` case, so turning it off and
    // reloading brings it back.
    const store = storage();
    writeFullScreen(true, store);
    writeFullScreen(false, store);
    expect(readFullScreen(store)).toBe(false);
  });
});
