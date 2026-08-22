// Server state for the Knowledge page.
//
// **This is not `PX-27`'s query layer.** That is `beta.1`'s work, roughly 300 lines with
// structured keys, prefix invalidation and optimistic mutation. Here there are five
// read-only resources and four mutations, so they are built on the existing
// `useAsyncResource` and this file exists only to keep the keys and the invalidation in
// one place — which is what makes handing them to `PX-27` a move rather than a rewrite.
//
// **If this file starts growing a retry policy or a cache, that is `PX-27` arriving
// early and the right response is to stop**, not to keep going.

import {
  useAsyncResource,
  type AsyncResource,
} from "../../composables/useAsyncResource";
import { api } from "../../stores/auth";
import type {
  KnowledgeDecisions,
  KnowledgeHealth,
  KnowledgeSearchPage,
  KnowledgeSourceRow,
} from "../../api/dto";

export interface KnowledgeQueries {
  health: AsyncResource<KnowledgeHealth>;
  recent: AsyncResource<KnowledgeSourceRow[]>;
  sources: AsyncResource<KnowledgeSourceRow[]>;
  decisions: AsyncResource<KnowledgeDecisions>;
  refreshAll: () => Promise<void>;
}

export function useKnowledgeQueries(projectId: () => string): KnowledgeQueries {
  const client = api();
  const health = useAsyncResource(() => client.knowledgeHealth(projectId()));
  const recent = useAsyncResource(() => client.recentlyLearned(projectId()), {
    isEmpty: (rows) => rows.length === 0,
  });
  const sources = useAsyncResource(
    () => client.listKnowledgeSources(projectId()),
    {
      isEmpty: (rows) => rows.length === 0,
    },
  );
  const decisions = useAsyncResource(() =>
    client.knowledgeDecisions(projectId()),
  );

  async function refreshAll(): Promise<void> {
    // Sequential rather than parallel: four small queries against one project, and a
    // burst of four is a burst the reader gains nothing from.
    await health.run();
    await recent.run();
    await sources.run();
    await decisions.run();
  }

  return { health, recent, sources, decisions, refreshAll };
}

export function useKnowledgeSearch(
  projectId: () => string,
  params: () => {
    q: string;
    sourceType?: string;
    authority?: string;
    includeHistory?: boolean;
  },
): AsyncResource<KnowledgeSearchPage> {
  const client = api();
  return useAsyncResource(() => client.searchKnowledge(projectId(), params()), {
    isEmpty: (page) => page.items.length === 0,
  });
}

// Three visual tiers rather than ten. What a reader needs to tell apart is
// "this is a rule / this is an observation / this is something somebody said";
// the exact level is carried by the text label beside the badge.
export function authorityTier(
  authority: string,
): "high" | "mid" | "low" | "stale" {
  switch (authority) {
    case "authoritative":
    case "accepted":
    case "canonical":
      return "high";
    case "verified":
    case "reviewed":
      return "mid";
    case "superseded":
    case "retracted":
      return "stale";
    default:
      return "low";
  }
}

const AUTHORITY_LABELS: Record<string, string> = {
  authoritative: "正式決策",
  accepted: "已接受",
  canonical: "程式庫現況",
  verified: "已驗證",
  reviewed: "已審閱",
  generated: "Agent 產出",
  discussion: "討論",
  diagnostic: "診斷",
  superseded: "已被取代",
  retracted: "已撤回",
};

export function authorityLabel(authority: string): string {
  return AUTHORITY_LABELS[authority] ?? authority;
}

const SOURCE_LABELS: Record<string, string> = {
  policy: "專案規則",
  ticket: "卡片",
  conversation: "對話",
  decision: "決策",
  artifact: "產物",
  verification: "驗證",
  repo_doc: "程式庫文件",
  activity: "時間軸",
};

export function sourceLabel(sourceType: string): string {
  return SOURCE_LABELS[sourceType] ?? sourceType;
}

// `repo://` is deliberately not a link. Cliora has no repository browser, and a link
// that pretends to work is worse than text a person can copy.
export function isOpenable(uri: string | null): boolean {
  return !!uri && !uri.startsWith("repo://");
}

const WHY_LABELS: Record<string, string> = {
  fts: "全文命中",
  trigram: "模糊命中",
  pinned: "已釘選",
  "graph:dependency": "前置任務",
  "graph:this_card": "這張卡自己的內容",
  "graph:same_epic": "同一個 Epic",
  "graph:supersedes": "取代關係",
  "graph:references": "引用關係",
  "graph:verifies": "驗證關係",
  "graph:delivers": "交付關係",
  "layer:always": "專案規則",
  "layer:open_question": "未決問題",
};

// Turn the server's machine-shaped reasons into one readable line. Unknown reasons pass
// through verbatim rather than being dropped: a reason nobody translated is still more
// useful than silence, and dropping it would hide a new ranking signal.
export function explainWhy(why: string[]): string {
  return why
    .map((reason) => {
      const [head] = reason.split(":");
      if (reason.startsWith("authority:")) {
        return authorityLabel(reason.slice("authority:".length)) + " 加權";
      }
      if (reason.startsWith("freshness:")) {
        return "時效 " + reason.slice("freshness:".length);
      }
      if (head === "fts" || head === "trigram") {
        return WHY_LABELS[head];
      }
      return WHY_LABELS[reason] ?? reason;
    })
    .join("・");
}
