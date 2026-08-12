import { mount } from "@vue/test-utils";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { RunStatus, TaskStage } from "../../api/dto";
import BaseBadge from "./BaseBadge.vue";
import DataTable from "./DataTable.vue";
import DeliveryBadge from "./DeliveryBadge.vue";
import EmptyState from "./EmptyState.vue";
import PageHead from "./PageHead.vue";
import RiskBadge from "./RiskBadge.vue";
import RunBadge from "./RunBadge.vue";
import SourceBadge from "./SourceBadge.vue";
import StageBadge from "./StageBadge.vue";
import ToastHost from "./ToastHost.vue";
import UiButton from "./UiButton.vue";
import UiCard from "./UiCard.vue";
import {
  runStatuses,
  SOURCE_AGENT,
  SOURCE_MACHINE,
  SOURCE_PLATFORM,
  taskStages,
} from "./labels";
import { useToast } from "./useToast";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("work vocabulary badges", () => {
  it("renders the base variants and a textual pulse label", () => {
    const wrapper = mount(BaseBadge, {
      props: { variant: "solid", tone: "run-running", pulse: true },
      slots: { default: "執行中" },
    });
    expect(wrapper.classes()).toContain("v-solid");
    expect(wrapper.classes()).toContain("t-run-running");
    expect(wrapper.find(".pulse").exists()).toBe(true);
    expect(wrapper.text()).toBe("執行中");
  });

  it.each(taskStages)("gives task stage %s a translated label", (stage) => {
    const wrapper = mount(StageBadge, { props: { stage } });
    expect(wrapper.text()).not.toBe(stage);
    expect(wrapper.text()).not.toBe("");
    expect(wrapper.find(".v-solid").exists()).toBe(true);
  });

  it.each(runStatuses)("gives run state %s a translated label", (status) => {
    const wrapper = mount(RunBadge, { props: { status } });
    expect(wrapper.text()).not.toBe(status);
    expect(wrapper.text()).not.toBe("");
  });

  it("includes the runner in a running badge", () => {
    expect(
      mount(RunBadge, {
        props: { status: "running", runnerName: "build-vm-02" },
      }).text(),
    ).toContain("執行中 · build-vm-02");
  });

  it("maps risk and delivery labels and makes no-delivery quiet", () => {
    expect(mount(RiskBadge, { props: { risk: "high" } }).text()).toBe("高風險");
    const delivery = mount(DeliveryBadge, { props: { delivery: "none" } });
    expect(delivery.text()).toBe("不交付");
    expect(delivery.find(".v-quiet").exists()).toBe(true);
  });

  it.each([
    [StageBadge, "stage", "totally_unknown" as TaskStage],
    [RunBadge, "status", "totally_unknown" as RunStatus],
    [RiskBadge, "risk", "totally_unknown"],
    [DeliveryBadge, "delivery", "totally_unknown"],
    [SourceBadge, "source", "totally_unknown"],
  ] as const)("falls back safely for %s", (component, prop, value) => {
    const wrapper = mount(
      component as never,
      {
        props: { [prop]: value },
      } as never,
    );
    expect(wrapper.text()).toBe("totally_unknown");
    expect(wrapper.find(".v-quiet").exists()).toBe(true);
  });

  it("uses solid, outline, and quiet for the three evidence sources", () => {
    const values = [
      [SOURCE_MACHINE, "v-solid"],
      [SOURCE_PLATFORM, "v-outline"],
      [SOURCE_AGENT, "v-quiet"],
    ];
    for (const [source, variant] of values) {
      expect(
        mount(SourceBadge, { props: { source } }).find(`.${variant}`).exists(),
      ).toBe(true);
    }
  });
});

describe("layout primitives", () => {
  it("renders button variants without changing native semantics", () => {
    const wrapper = mount(UiButton, {
      props: { variant: "primary", type: "submit" },
      slots: { default: "建立專案" },
    });
    expect(wrapper.get("button").attributes("type")).toBe("submit");
    expect(wrapper.get("button").classes()).toContain("primary");
    expect(wrapper.text()).toBe("建立專案");
  });

  it("renders page title, subtitle, and actions in stable regions", () => {
    const wrapper = mount(PageHead, {
      slots: { title: "專案", subtitle: "最近活動", actions: "新增" },
    });
    expect(wrapper.get("h1").text()).toBe("專案");
    expect(wrapper.get("p").text()).toBe("最近活動");
    expect(wrapper.get(".actions").text()).toBe("新增");
  });

  it("supports cards with and without a header", () => {
    const headed = mount(UiCard, {
      slots: { header: "摘要", default: "內容" },
    });
    expect(headed.get("header").text()).toBe("摘要");
    expect(headed.get(".body").text()).toBe("內容");
    expect(
      mount(UiCard, { slots: { default: "內容" } })
        .find("header")
        .exists(),
    ).toBe(false);
  });

  it("wraps a semantic table in its own scroll container", () => {
    const wrapper = mount(DataTable, {
      slots: { default: "<tbody><tr><td>row</td></tr></tbody>" },
    });
    expect(wrapper.get(".table-scroll").find("table").exists()).toBe(true);
  });

  it("warns when an empty state has no actionable next step", () => {
    const warning = vi
      .spyOn(console, "warn")
      .mockImplementation(() => undefined);
    mount(EmptyState, { slots: { default: "沒有資料" } });
    expect(warning).toHaveBeenCalledWith(
      "EmptyState requires an action slot with a safe next step.",
    );
    warning.mockClear();
    mount(EmptyState, {
      slots: { default: "沒有資料", action: "前往下一步" },
    });
    expect(warning).not.toHaveBeenCalled();
  });

  it("keeps errors until dismissed and auto-dismisses success messages", async () => {
    vi.useFakeTimers();
    const toast = useToast();
    const wrapper = mount(ToastHost);
    toast.push({ kind: "error", title: "拒絕", message: "請先修正" });
    toast.push({ kind: "success", title: "已完成" });
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(6000);
    await wrapper.vm.$nextTick();
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(1);
    expect(wrapper.text()).toContain("拒絕");
    await wrapper.get("button").trigger("click");
    expect(wrapper.findAll('[role="alert"]')).toHaveLength(0);
  });
});
