import { defineStore } from "pinia";

import type {
  ActivityEvent,
  ProjectDetail,
  ProjectStatus,
  ProjectSummary,
} from "../api/dto";
import { api } from "./auth";

interface ProjectsState {
  list: ProjectSummary[];
  current: ProjectDetail | null;
  activity: ActivityEvent[];
  // Server-driven, never inferred here: it means "you are not allowed to see who
  // did this", which is a different fact from an event that genuinely has no actor
  // (a system-originated row). The view has to say which, so it needs the flag
  // rather than the absence of a name.
  actorsHidden: boolean;
  activityCursor: string | null;
}

export const useProjectsStore = defineStore("projects", {
  state: (): ProjectsState => ({
    list: [],
    current: null,
    activity: [],
    actorsHidden: false,
    activityCursor: null,
  }),
  actions: {
    async fetchList(params?: {
      status?: ProjectStatus;
      owned_by_me?: boolean;
    }): Promise<ProjectSummary[]> {
      this.list = await api().listProjects(params);
      return this.list;
    },
    async fetchProject(id: string): Promise<ProjectDetail> {
      const project = await api().getProject(id);
      this.current = project;
      return project;
    },
    async create(input: {
      name: string;
      slug?: string;
      description?: string;
    }): Promise<ProjectDetail> {
      const project = await api().createProject(input);
      this.current = project;
      return project;
    },
    async update(
      id: string,
      input: { name?: string; description?: string; status?: ProjectStatus },
    ): Promise<ProjectSummary> {
      const project = await api().updateProject(id, input);
      const index = this.list.findIndex((item) => item.id === id);
      if (index >= 0) this.list[index] = project;
      if (this.current?.id === id)
        this.current = { ...this.current, ...project };
      return project;
    },
    async bindWorkspace(
      id: string,
      input: {
        node_id: string;
        path: string;
        label?: string;
        is_primary?: boolean;
      },
    ): Promise<void> {
      await api().bindProjectWorkspace(id, input);
      // Re-read rather than push the response: binding one workspace as primary
      // demotes another, and the usability verdicts are computed per response from
      // the node's state *now*.
      await this.fetchProject(id);
    },
    async unbindWorkspace(id: string, bindingId: string): Promise<void> {
      await api().unbindProjectWorkspace(id, bindingId);
      await this.fetchProject(id);
    },
    async fetchActivity(id: string, { append = false } = {}): Promise<void> {
      const page = await api().listProjectActivity(id, {
        limit: 25,
        before: append ? (this.activityCursor ?? undefined) : undefined,
      });
      this.activity = append ? [...this.activity, ...page.items] : page.items;
      this.actorsHidden = page.actors_hidden;
      this.activityCursor = page.next_before;
    },
    reset(): void {
      this.list = [];
      this.current = null;
      this.activity = [];
      this.actorsHidden = false;
      this.activityCursor = null;
    },
  },
});
