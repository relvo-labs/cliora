import { mount } from "@vue/test-utils";
import { defineComponent, h, nextTick } from "vue";
import { createMemoryHistory, createRouter, type Router } from "vue-router";
import { beforeEach, describe, expect, it } from "vitest";

import TaskDetailDrawer from "./TaskDetailDrawer.vue";
import { useTaskDrawer } from "./useTaskDrawer";

const Blank = defineComponent({ render: () => h("div") });

function router(): Router {
  return createRouter({
    history: createMemoryHistory(),
    routes: [
      // A catch-all too: `createMemoryHistory` starts at "" and the unmatched start warns
      // on every mount, which buries the output the failures need.
      { path: "/:pathMatch(.*)*", component: Blank },
      { path: "/projects/:id", name: "project-detail", component: Blank },
      {
        path: "/projects/:id/tasks/:taskId",
        name: "task-detail",
        component: Blank,
      },
    ],
  });
}

/** A component that exposes the composable's surface so the URL contract can be
 *  exercised through a real router rather than through a mock of one. */
const Harness = defineComponent({
  setup(_, { expose }) {
    const drawer = useTaskDrawer();
    expose(drawer);
    return () => h("div", drawer.taskId.value ?? "closed");
  },
});

describe("useTaskDrawer: the URL is the state", () => {
  let instance: Router;

  beforeEach(() => {
    instance = router();
  });

  it("replaces rather than pushes, so back does not walk through the reader's scanning", async () => {
    await instance.push("/projects/p1?tab=board");
    const wrapper = mount(Harness, { global: { plugins: [instance] } });
    const before = window.history.length;

    await (
      wrapper.vm as unknown as { open: (id: string) => Promise<void> }
    ).open("t1");
    expect(instance.currentRoute.value.query.task).toBe("t1");
    expect(window.history.length).toBe(before);
  });

  it("keeps every other query key when it opens and when it closes", async () => {
    // The whole point of a Drawer: what is behind it survives. `view`, the filter and
    // the tab must come back untouched.
    await instance.push("/projects/p1?tab=board&f=eyJhIjoxfQ&view=v-9");
    const wrapper = mount(Harness, { global: { plugins: [instance] } });
    const vm = wrapper.vm as unknown as {
      open: (id: string) => Promise<void>;
      close: () => Promise<void>;
    };

    await vm.open("t1");
    expect(instance.currentRoute.value.query).toEqual({
      tab: "board",
      f: "eyJhIjoxfQ",
      view: "v-9",
      task: "t1",
    });

    await vm.close();
    expect(instance.currentRoute.value.query).toEqual({
      tab: "board",
      f: "eyJhIjoxfQ",
      view: "v-9",
    });
  });

  it("reads the task straight out of the URL, so a reload reopens the same card", async () => {
    await instance.push("/projects/p1?task=t7");
    const wrapper = mount(Harness, { global: { plugins: [instance] } });
    expect(wrapper.text()).toBe("t7");
  });

  it("survives a duplicated task key instead of taking the board down with it", async () => {
    await instance.push("/projects/p1?task=t1&task=t2");
    const wrapper = mount(Harness, { global: { plugins: [instance] } });
    expect(wrapper.text()).toBe("t1");
  });
});

describe("TaskDetailDrawer: the container's keyboard contract", () => {
  function drawer(taskId: string | null) {
    const instance = router();
    // Give the router a location before mounting: `RouterLink` resolves against the
    // current route, and an unpushed memory history warns on every render.
    void instance.push("/projects/p1");
    return mount(TaskDetailDrawer, {
      props: {
        projectId: "p1",
        taskId,
        cardRef: "TK-9",
        title: "支援 SAML SSO 登入",
      },
      attachTo: document.body,
      global: { plugins: [instance] },
      slots: { default: h("button", { id: "inside" }, "回覆") },
    });
  }

  it("renders nothing at all while no task is named", () => {
    expect(drawer(null).find("[data-task-drawer]").exists()).toBe(false);
  });

  it("is a dialog that does not make the board inert", () => {
    // kintra's rule, adopted word for word: a normal ticket detail is not a modal.
    // `aria-modal="false"` is the assertion that the board behind stays reachable.
    const panel = drawer("t1").get("[data-task-drawer]");
    expect(panel.attributes("role")).toBe("dialog");
    expect(panel.attributes("aria-modal")).toBe("false");
    expect(panel.attributes("aria-label")).toBe("任務 TK-9");
  });

  it("names the card before the fetch answers, from what the board already knew", () => {
    const wrapper = drawer("t1");
    expect(wrapper.get(".ref").text()).toBe("TK-9");
    expect(wrapper.get("h2").text()).toBe("支援 SAML SSO 登入");
  });

  it("offers a real link to the full page, not a click handler", () => {
    // Middle-click and "copy link address" are what people actually do with this, and
    // neither works on a button.
    const link = drawer("t1").get("[data-drawer-newtab]");
    expect(link.element.tagName).toBe("A");
    expect(link.attributes("href")).toBe("/projects/p1/tasks/t1");
    expect(link.attributes("target")).toBe("_blank");
    expect(link.attributes("rel")).toBe("noopener");
  });

  it("closes on Escape, on the close button and on the backdrop", async () => {
    for (const act of [
      (w: ReturnType<typeof drawer>) =>
        w.get("[data-task-drawer]").trigger("keydown", { key: "Escape" }),
      (w: ReturnType<typeof drawer>) =>
        w.get("[data-drawer-close]").trigger("click"),
      (w: ReturnType<typeof drawer>) =>
        w.get("[data-drawer-backdrop]").trigger("click"),
    ]) {
      const wrapper = drawer("t1");
      await act(wrapper);
      expect(wrapper.emitted("close")).toHaveLength(1);
      wrapper.unmount();
    }
  });

  it("takes focus on open and gives it back on close", async () => {
    // A reader who pressed Escape expects to be back on the card they pressed it from,
    // not at the top of the document with the board scrolled away under them.
    const opener = document.createElement("button");
    document.body.append(opener);
    opener.focus();
    expect(document.activeElement).toBe(opener);

    const wrapper = drawer("t1");
    await nextTick();
    expect(document.activeElement).toBe(
      wrapper.get("[data-task-drawer]").element,
    );

    await wrapper.setProps({ taskId: null });
    await nextTick();
    expect(document.activeElement).toBe(opener);
    wrapper.unmount();
    opener.remove();
  });

  it("wraps Tab at the ends so a keyboard reader cannot walk out of it", async () => {
    const wrapper = drawer("t1");
    await nextTick();
    const panel = wrapper.get("[data-task-drawer]");
    const stops = panel.element.querySelectorAll<HTMLElement>("a,button");
    const first = stops[0];
    const last = stops[stops.length - 1];

    last.focus();
    await panel.trigger("keydown", { key: "Tab" });
    expect(document.activeElement).toBe(first);

    first.focus();
    await panel.trigger("keydown", { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
    wrapper.unmount();
  });
});
