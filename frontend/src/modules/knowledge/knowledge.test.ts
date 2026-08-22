// The Knowledge page's two load-bearing claims (`KN-10`/`KN-11`).
//
// 1. **The "why" line is the server's, verbatim.** If the browser re-derived it, the two
//    rankings would disagree one day and nobody could tell which was lying — and the
//    whole argument for this page is that retrieval stops being a black box.
// 2. **An empty repository says so.** Content is pushed from inside a run (D77), so a
//    project whose agents never ran has none. A knowledge base that cannot show you it
//    is empty is worse than not having one.

import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { KnowledgeHealth, KnowledgeHit } from "../../api/dto";
import AuthorityBadge from "./components/AuthorityBadge.vue";
import CitationLink from "./components/CitationLink.vue";
import SourceHealth from "./components/SourceHealth.vue";
import {
  authorityLabel,
  authorityTier,
  explainWhy,
  isOpenable,
  sourceLabel,
} from "./queries";

function hit(over: Partial<KnowledgeHit> = {}): KnowledgeHit {
  return {
    source_id: "11111111-1111-1111-1111-111111111111",
    source_type: "repo_doc",
    title: "docs/adr/0035.md",
    authority: "canonical",
    version: "139f143",
    occurred_at: "2026-08-21T00:00:00Z",
    uri: "repo://github.com/acme/x/docs/adr/0035.md@139f143",
    excerpt: "租約過期時的處理",
    score: 1.2,
    historical: false,
    why: ["fts:0.412", "authority:canonical", "graph:dependency"],
    ...over,
  };
}

function health(over: Partial<KnowledgeHealth> = {}): KnowledgeHealth {
  return {
    families: [
      {
        source_type: "ticket",
        sources: 12,
        chunks: 14,
        last_ingested_at: "2026-08-22T00:00:00Z",
      },
    ],
    pending_jobs: 0,
    failed_jobs: 0,
    dead_jobs: 0,
    dead_letter_age_seconds: 0,
    last_error: null,
    repo_last_synced_at: null,
    repo_commit: null,
    repo_never_synced: true,
    ...over,
  };
}

beforeEach(() => {
  setActivePinia(createPinia());
  vi.restoreAllMocks();
});

describe("authority is three tiers with ten words", () => {
  it("maps the ten levels onto three visual tiers", () => {
    expect(authorityTier("authoritative")).toBe("high");
    expect(authorityTier("verified")).toBe("mid");
    expect(authorityTier("discussion")).toBe("low");
    expect(authorityTier("superseded")).toBe("stale");
  });

  it("keeps the precise level in the text", () => {
    expect(authorityLabel("generated")).toBe("Agent 產出");
    expect(authorityLabel("canonical")).toBe("程式庫現況");
  });

  it("renders the level and the version together", () => {
    const wrapper = mount(AuthorityBadge, {
      props: { authority: "accepted", version: "seq:41" },
    });
    expect(wrapper.text()).toContain("已接受");
    expect(wrapper.text()).toContain("seq:41");
    expect(wrapper.attributes("data-authority")).toBe("accepted");
  });
});

describe("the why line", () => {
  it("translates the server's reasons rather than recomputing them", () => {
    const line = explainWhy(hit().why);
    expect(line).toContain("全文命中");
    expect(line).toContain("前置任務");
    expect(line).toContain("加權");
  });

  it("passes an unknown reason through instead of dropping it", () => {
    // A reason nobody translated is still more useful than silence, and dropping it
    // would hide a ranking signal somebody added.
    expect(explainWhy(["graph:brand_new_thing"])).toBe("graph:brand_new_thing");
  });

  it("never invents a reason of its own", () => {
    expect(explainWhy([])).toBe("");
  });
});

describe("citations", () => {
  it("does not link a repo:// uri", () => {
    // Cliora has no repository browser. A link that pretends to work costs the reader a
    // click to discover it was never going anywhere.
    expect(isOpenable("repo://github.com/acme/x/docs/a.md@abc")).toBe(false);
    expect(isOpenable("/projects/1/tasks/2?seq=18")).toBe(true);
    expect(isOpenable(null)).toBe(false);
  });

  it("renders a repo uri as copyable text", () => {
    const wrapper = mount(CitationLink, {
      props: { uri: "repo://github.com/acme/x/docs/a.md@abc", title: "a.md" },
      global: { stubs: { RouterLink: true } },
    });
    expect(wrapper.find("code").exists()).toBe(true);
    expect(wrapper.find("a").exists()).toBe(false);
    expect(wrapper.text()).toContain("複製");
  });

  it("renders an in-app uri as a link", () => {
    const wrapper = mount(CitationLink, {
      props: { uri: "/projects/1/tasks/2?seq=18", title: "TK-1 #18" },
      global: { stubs: { RouterLink: { template: "<a><slot /></a>" } } },
    });
    expect(wrapper.find("a").exists()).toBe(true);
  });
});

describe("source health", () => {
  it("says in words when the repository has never been synced", () => {
    const wrapper = mount(SourceHealth, { props: { health: health() } });
    const notice = wrapper.get('[data-testid="repo-never-synced"]');
    expect(notice.text()).toContain("從未同步");
    expect(notice.text()).toContain("cliora knowledge sync");
  });

  it("shows the commit once a sync has happened", () => {
    const wrapper = mount(SourceHealth, {
      props: {
        health: health({
          repo_never_synced: false,
          repo_commit: "139f143",
          repo_last_synced_at: "2026-08-22T00:00:00Z",
        }),
      },
    });
    expect(wrapper.text()).toContain("139f143");
    expect(wrapper.text()).not.toContain("從未同步");
  });

  it("escalates a dead letter older than an hour", () => {
    const quiet = mount(SourceHealth, {
      props: { health: health({ dead_jobs: 1, dead_letter_age_seconds: 60 }) },
    });
    expect(quiet.get('[data-testid="dead-letter"]').classes()).not.toContain(
      "health__danger",
    );

    const loud = mount(SourceHealth, {
      props: {
        health: health({ dead_jobs: 1, dead_letter_age_seconds: 7200 }),
      },
    });
    expect(loud.get('[data-testid="dead-letter"]').classes()).toContain(
      "health__danger",
    );
  });

  it("names each source family in words", () => {
    const wrapper = mount(SourceHealth, { props: { health: health() } });
    expect(wrapper.text()).toContain("卡片");
    expect(sourceLabel("repo_doc")).toBe("程式庫文件");
  });
});
