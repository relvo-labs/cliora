// The conversation panel's product rules, as assertions (`CV-10`, `CV-11`).
//
// Four of these guard something that would otherwise fail silently: a draft lost to a
// 500, a double click becoming two messages, a card that still says "waiting" after
// the reply, and two buttons a person cannot tell apart.

import { flushPromises, mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { TaskMessage, TaskQuestion } from "../../../api/dto";
import { useAuthStore } from "../../../stores/auth";
import ConversationPanel from "./ConversationPanel.vue";
import MessageComposer from "./MessageComposer.vue";
import ProposalCard from "./ProposalCard.vue";
import QuestionCard from "./QuestionCard.vue";

const listTaskMessages = vi.fn();
const listTaskQuestions = vi.fn();
const postTaskMessage = vi.fn();
const answerTaskQuestion = vi.fn();

vi.mock("../../../stores/auth", async () => {
  const actual = await vi.importActual<typeof import("../../../stores/auth")>(
    "../../../stores/auth",
  );
  return {
    ...actual,
    api: () => ({
      listTaskMessages,
      listTaskQuestions,
      postTaskMessage,
      answerTaskQuestion,
    }),
  };
});

function message(overrides: Partial<TaskMessage> = {}): TaskMessage {
  return {
    id: "m1",
    task_id: "t1",
    run_id: null,
    conversation_seq: 1,
    author_kind: "user",
    author_user_id: "u1",
    author_name: "陳小美",
    author_runner_id: null,
    author_runner_name: null,
    body: "hello",
    kind: "comment",
    event_kind: null,
    reply_to_message_id: null,
    question_id: null,
    question_state: null,
    created_at: "2026-08-16T10:00:00Z",
    ...overrides,
  };
}

function question(overrides: Partial<TaskQuestion> = {}): TaskQuestion {
  return {
    id: "q1",
    task_id: "t1",
    run_id: "r1",
    asked_message_id: "m1",
    state: "open",
    answered_message_id: null,
    created_at: "2026-08-16T10:00:00Z",
    answered_at: null,
    expired_at: null,
    ...overrides,
  };
}

function grant(actions: string[]): void {
  const auth = useAuthStore();
  auth.user = {
    id: "u1",
    username: "u1",
    display_name: "陳小美",
    role: "Developer",
    permissions: actions,
    features: [],
  };
}

async function panel(
  messages: TaskMessage[],
  questions: TaskQuestion[] = [],
  actions: string[] = ["task.update"],
) {
  listTaskMessages.mockResolvedValue({
    items: messages,
    next_after_seq: messages.at(-1)?.conversation_seq ?? null,
    has_more: false,
  });
  listTaskQuestions.mockResolvedValue(questions);
  grant(actions);
  const wrapper = mount(ConversationPanel, { props: { taskId: "t1" } });
  await flushPromises();
  return wrapper;
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.clearAllMocks();
  localStorage.clear();
});

describe("the two actions", () => {
  it("offers 回覆並繼續 only while a question is open", async () => {
    const open = await panel(
      [message({ kind: "question", author_kind: "agent" })],
      [question()],
    );
    const buttons = open.findAll("button").map((b) => b.text());
    expect(buttons.some((text) => text.includes("回覆並繼續"))).toBe(true);

    const closed = await panel([message()], []);
    const closedButtons = closed.findAll("button").map((b) => b.text());
    // **Absent, not disabled.** A permanently greyed control reads as broken and
    // invites somebody to go looking for the permission they are missing.
    expect(closedButtons.some((text) => text.includes("回覆並繼續"))).toBe(
      false,
    );
    expect(closedButtons.some((text) => text.includes("留言"))).toBe(true);
  });

  it("gives the two actions different names, and the primary one says 繼續", async () => {
    const wrapper = await panel(
      [message({ kind: "question", author_kind: "agent" })],
      [question()],
    );
    const composer = wrapper.findComponent(MessageComposer);
    const names = composer.findAll("button").map((b) => b.text().trim());
    expect(new Set(names).size).toBe(names.length);
    expect(names.find((name) => name.includes("繼續"))).toBeTruthy();
    expect(names).toContain("留言");
  });

  it("sends a comment to the message route and an answer to the question route", async () => {
    postTaskMessage.mockResolvedValue(message());
    answerTaskQuestion.mockResolvedValue({
      message: message({ kind: "answer", conversation_seq: 2 }),
      question: question({ state: "answered" }),
      mode: "new_turn",
      continuation_run_id: "run-2",
      refusal_code: null,
    });
    const wrapper = await panel(
      [message({ kind: "question", author_kind: "agent" })],
      [question()],
    );
    const composer = wrapper.findComponent(MessageComposer);
    await composer.find("textarea").setValue("用 SAML 2.0");

    await composer.findAll("button")[1].trigger("click");
    await flushPromises();
    expect(answerTaskQuestion).toHaveBeenCalledWith(
      "t1",
      "q1",
      expect.objectContaining({ body: "用 SAML 2.0", resume: true }),
    );
    expect(postTaskMessage).not.toHaveBeenCalled();
    expect(wrapper.text()).toContain("已回覆，並排入新的一輪。");
  });

  it("says the answer was kept when the continuation is refused", async () => {
    // `refused` must not read as failure: the answer *was* written, and only the next
    // round was stopped.
    answerTaskQuestion.mockResolvedValue({
      message: message({ kind: "answer" }),
      question: question({ state: "answered" }),
      mode: "refused",
      continuation_run_id: null,
      refusal_code: "TASK_KIND_FORBIDS_SECRETS",
    });
    const wrapper = await panel(
      [message({ kind: "question", author_kind: "agent" })],
      [question()],
    );
    const composer = wrapper.findComponent(MessageComposer);
    await composer.find("textarea").setValue("好");
    await composer.findAll("button")[1].trigger("click");
    await flushPromises();
    expect(wrapper.text()).toContain("已回覆");
    expect(wrapper.text()).toContain("無法繼續執行");
  });
});

describe("the draft", () => {
  it("survives a failed send", async () => {
    postTaskMessage.mockRejectedValue(new Error("boom"));
    const wrapper = await panel([message()]);
    const composer = wrapper.findComponent(MessageComposer);
    const textarea = composer.find("textarea");
    await textarea.setValue("辛苦寫好的一段話");

    await composer.findAll("button")[0].trigger("click");
    await flushPromises();

    // The one failure in this panel a person cannot recover from on their own.
    expect((textarea.element as HTMLTextAreaElement).value).toBe(
      "辛苦寫好的一段話",
    );
  });

  it("clears only after the write lands", async () => {
    postTaskMessage.mockResolvedValue(message());
    const wrapper = await panel([message()]);
    const composer = wrapper.findComponent(MessageComposer);
    const textarea = composer.find("textarea");
    await textarea.setValue("送得出去的一句話");
    await composer.findAll("button")[0].trigger("click");
    await flushPromises();
    expect((textarea.element as HTMLTextAreaElement).value).toBe("");
  });

  it("carries one idempotency key per send", async () => {
    postTaskMessage.mockResolvedValue(message());
    const wrapper = await panel([message()]);
    const composer = wrapper.findComponent(MessageComposer);
    await composer.find("textarea").setValue("一句話");
    await composer.findAll("button")[0].trigger("click");
    await flushPromises();
    expect(postTaskMessage).toHaveBeenCalledWith(
      "t1",
      expect.objectContaining({ idempotency_key: expect.any(String) }),
    );
  });
});

describe("the question card", () => {
  it("renders the state the server gave, not one derived from the thread", async () => {
    // A question followed by an unrelated comment used to look answered. The server
    // knows; the panel does not guess.
    const wrapper = await panel(
      [
        message({ id: "m1", kind: "question", author_kind: "agent" }),
        message({ id: "m2", conversation_seq: 2, body: "順便問一下…" }),
      ],
      [question({ asked_message_id: "m1", state: "open" })],
    );
    const card = wrapper.findComponent(QuestionCard);
    expect(card.props("state")).toBe("open");
    expect(card.text()).toContain("等待你的回覆");
  });

  it("offers dispatch rather than reply once a question has expired", async () => {
    const wrapper = await panel(
      [message({ id: "m1", kind: "question", author_kind: "agent" })],
      [question({ asked_message_id: "m1", state: "expired" })],
    );
    const card = wrapper.findComponent(QuestionCard);
    expect(card.text()).toContain("逾時");
    expect(card.text()).toContain("重新派工");
    expect(card.findAll("button").map((b) => b.text())).not.toContain(
      "回覆並繼續",
    );
  });
});

describe("the proposal card", () => {
  const proposal = message({
    id: "p1",
    conversation_seq: 3,
    kind: "proposal",
    author_kind: "agent",
    author_runner_name: "runner-03",
    body: "## 目標\n支援 SSO",
  });

  it("hides the decision buttons without task.approve", async () => {
    const wrapper = await panel([proposal], [], ["task.update"]);
    const card = wrapper.findComponent(ProposalCard);
    expect(card.text()).toContain("等待有核准權限的人檢視");
    expect(card.findAll("button").map((b) => b.text())).not.toContain("接受");
  });

  it("shows them with task.approve", async () => {
    const wrapper = await panel(
      [proposal],
      [],
      ["task.update", "task.approve"],
    );
    const card = wrapper.findComponent(ProposalCard);
    expect(card.findAll("button").map((b) => b.text())).toContain("接受");
  });

  it("marks all but the newest proposal as superseded", async () => {
    const wrapper = await panel(
      [
        proposal,
        message({
          id: "p2",
          conversation_seq: 4,
          kind: "proposal",
          author_kind: "agent",
          body: "## 目標\n第二版",
        }),
      ],
      [],
      ["task.update", "task.approve"],
    );
    const cards = wrapper.findAllComponents(ProposalCard);
    expect(cards).toHaveLength(2);
    expect(cards[0].props("superseded")).toBe(true);
    expect(cards[1].props("superseded")).toBe(false);
    // Nobody accepts a draft two rounds out of date.
    expect(cards[0].text()).toContain("已被較新的提案取代");
  });
});

describe("what the thread is not", () => {
  it("shows no run log and no log link", async () => {
    const wrapper = await panel([
      message({ kind: "system", author_kind: "system", body: "claimed" }),
    ]);
    expect(wrapper.text()).not.toContain("log");
    expect(wrapper.findAll("a")).toHaveLength(0);
  });
});
