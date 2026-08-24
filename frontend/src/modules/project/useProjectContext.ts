// One project, loaded once, read by seven sub-routes (PX-64, plan/26/09 §4).
//
// **The shell provides it and the views inject it.** The alternative — each sub-route
// loading the project for itself — means a tab switch refetches the header and the
// permissions, and the header flickers on every navigation. The alternative to *that* —
// props threaded through `<RouterView>` — makes the shell know what each view needs,
// which is the coupling this split exists to remove.
//
// What is *not* here: anything a single view owns. The board's cards, the requirement
// list and the activity page's cursor all live in their own views, because a project's
// identity is shared and a view's data is not.

import {
  computed,
  inject,
  provide,
  ref,
  type ComputedRef,
  type InjectionKey,
  type Ref,
} from "vue";

import { ApiError } from "../../api/client";
import {
  ACTION_PROJECT_MANAGE,
  ACTION_RUN_DISPATCH,
  ACTION_SECRET_MANAGE,
  ACTION_TASK_APPROVE,
  ACTION_TASK_CREATE,
  ACTION_TASK_UPDATE,
  FEATURE_AGENT_RUNS,
  type ProjectDetail,
} from "../../api/dto";
import {
  useAsyncResource,
  type AsyncResource,
} from "../../composables/useAsyncResource";
import { useAuthStore } from "../../stores/auth";
import { useProjectsStore } from "../../stores/projects";

export interface ProjectContext {
  projectId: string;
  project: ComputedRef<ProjectDetail | null>;
  resource: AsyncResource<void>;
  isArchived: ComputedRef<boolean>;
  can: {
    manage: ComputedRef<boolean>;
    manageSecrets: ComputedRef<boolean>;
    writeTasks: ComputedRef<boolean>;
    createTasks: ComputedRef<boolean>;
    approve: ComputedRef<boolean>;
    dispatch: ComputedRef<boolean>;
  };
  /** Set by any view whose own write failed, and rendered by the shell.
   *
   *  One banner for the page rather than one per view: two error strips stacked above a
   *  board is how a reader stops reading either. */
  actionError: Ref<string>;
  actionRequestId: Ref<string | undefined>;
  actionBusy: Ref<boolean>;
  perform: (operation: () => Promise<void>) => Promise<void>;
  recordActionError: (error: unknown, fallback: string) => void;
  reload: () => Promise<void>;
  /** Opens the shell's "bind workspace" dialog.
   *
   *  The dialog lives in the shell because it edits the *project*; the button that opens
   *  it lives on Overview, next to the list it affects. This is the seam between those
   *  two facts, and it is a callback rather than a shared `ref` so that a view cannot
   *  leave the dialog open by mutating state it does not own. */
  openBindDialog: () => void;
}

const KEY: InjectionKey<ProjectContext> = Symbol("cliora.project");

export function createProjectContext(
  projectId: string,
  hooks: { openBindDialog: () => void },
): ProjectContext {
  const auth = useAuthStore();
  const projects = useProjectsStore();

  const resource = useAsyncResource(async () => {
    await projects.fetchProject(projectId);
    await projects.fetchActivity(projectId);
  });

  const actionError = ref("");
  const actionRequestId = ref<string | undefined>(undefined);
  const actionBusy = ref(false);

  function recordActionError(error: unknown, fallback: string): void {
    actionError.value = error instanceof ApiError ? error.message : fallback;
    actionRequestId.value =
      error instanceof ApiError ? error.requestId : undefined;
  }

  async function perform(operation: () => Promise<void>): Promise<void> {
    actionBusy.value = true;
    actionError.value = "";
    actionRequestId.value = undefined;
    try {
      await operation();
    } catch (error) {
      recordActionError(error, "The project could not be updated.");
    } finally {
      actionBusy.value = false;
    }
  }

  const context: ProjectContext = {
    projectId,
    project: computed(() => projects.current),
    resource,
    isArchived: computed(() => projects.current?.status === "archived"),
    can: {
      manage: computed(() => auth.hasPermission(ACTION_PROJECT_MANAGE)),
      // **The flag and the permission, both.** A flag says what the deployment has, a
      // permission says what this person may do, and neither alone is authorization
      // (ADR 0027). The server checks both regardless; this only decides what renders.
      manageSecrets: computed(
        () =>
          auth.hasFeature(FEATURE_AGENT_RUNS) &&
          auth.hasPermission(ACTION_SECRET_MANAGE),
      ),
      writeTasks: computed(() => auth.hasPermission(ACTION_TASK_UPDATE)),
      createTasks: computed(() => auth.hasPermission(ACTION_TASK_CREATE)),
      approve: computed(() => auth.hasPermission(ACTION_TASK_APPROVE)),
      // Both, because sending a requirement to an agent is two acts: creating a card
      // and spending compute. `run.dispatch` is deliberately not covered by
      // `task.update` for exactly that reason (ADR 0029).
      dispatch: computed(
        () =>
          auth.hasPermission(ACTION_TASK_CREATE) &&
          auth.hasPermission(ACTION_RUN_DISPATCH),
      ),
    },
    actionError,
    actionRequestId,
    actionBusy,
    perform,
    recordActionError,
    reload: () => resource.run(),
    openBindDialog: hooks.openBindDialog,
  };
  provide(KEY, context);
  return context;
}

/** The views' side of it.
 *
 *  Throws rather than returning null when the shell is missing: a view rendered outside
 *  its shell has no project, and every line after this point would be reading undefined.
 *  A thrown error names the mistake once; a null would produce a blank page. */
export function useProjectContext(): ProjectContext {
  const context = inject(KEY, null);
  if (context === null) {
    throw new Error("useProjectContext() requires a ProjectShell ancestor");
  }
  return context;
}
