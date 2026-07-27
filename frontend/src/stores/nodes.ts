import { defineStore } from "pinia";

import type {
  NodeDetail,
  NodeSummary,
  ReleaseManifest,
  UpdateNodeInput,
} from "../api/dto";
import { api } from "./auth";

function toSummary(node: NodeDetail): NodeSummary {
  return {
    id: node.id,
    name: node.name,
    hostname: node.hostname,
    status: node.status,
    os: node.os,
    architecture: node.architecture,
    claude_available: node.claude_available,
    codex_available: node.codex_available,
    session_count: node.session_count,
    last_seen_at: node.last_seen_at,
  };
}

interface NodesState {
  list: NodeSummary[];
  current: NodeDetail | null;
  // The published releases, once fetched. Null means "not asked yet", which the UI
  // shows differently from an empty manifest ("nothing published").
  releases: ReleaseManifest | null;
}

export const useNodesStore = defineStore("nodes", {
  state: (): NodesState => ({ list: [], current: null, releases: null }),
  actions: {
    async fetchList(): Promise<NodeSummary[]> {
      this.list = await api().listNodes();
      return this.list;
    },
    async fetchNode(id: string): Promise<NodeDetail> {
      const node = await api().getNode(id);
      this.current = node;
      return node;
    },
    async setEnabled(id: string, enabled: boolean): Promise<NodeDetail> {
      const node = await api().setNodeEnabled(id, enabled);
      this.current = node;
      this.patchList(node);
      return node;
    },
    // Ask a node to update to an allowlisted release (P4-10). Resolves as soon as
    // Central has accepted the request — the returned status may be `in_progress`,
    // because the daemon restarts mid-update and reports afterwards.
    async requestUpdate(
      id: string,
      input: UpdateNodeInput,
    ): Promise<NodeDetail> {
      const node = await api().updateNode(id, input);
      this.current = node;
      this.patchList(node);
      return node;
    },
    // The versions a node may be asked to install. Fetched from the server rather
    // than typed by the user: a free-text version field would only produce 409s,
    // and there is deliberately no way to name an artifact directly.
    async fetchReleases(): Promise<ReleaseManifest> {
      this.releases = await api().getReleaseManifest();
      return this.releases;
    },
    async remove(id: string): Promise<void> {
      // Soft delete on the server; the removed node simply leaves the list.
      await api().removeNode(id);
      this.list = this.list.filter((node) => node.id !== id);
      if (this.current?.id === id) {
        this.current = null;
      }
    },
    patchList(node: NodeDetail): void {
      const index = this.list.findIndex((item) => item.id === node.id);
      if (index >= 0) {
        this.list[index] = toSummary(node);
      }
    },
  },
});
