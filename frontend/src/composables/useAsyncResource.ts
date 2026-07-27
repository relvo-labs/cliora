import { ref, shallowRef, type Ref } from "vue";

import { ApiError } from "../api/client";
import type { NodeRuntime, NodeStatus } from "../api/dto";

// The lifecycle states a single async resource can be in. A view maps richer
// presentation states (stale/offline/partial) from the resolved data itself.
export type ResourceState =
  | "idle"
  | "loading"
  | "success"
  | "empty"
  | "forbidden"
  | "error";

export interface AsyncResource<T> {
  data: Ref<T | null>;
  error: Ref<unknown>;
  state: Ref<ResourceState>;
  run: () => Promise<void>;
}

// useAsyncResource owns the loading/error lifecycle for one loader. It is the
// single owner of that request's state and is safe to re-run (retry). A 403 is
// surfaced as "forbidden" so RBAC-denied views render the right affordance.
export function useAsyncResource<T>(
  loader: () => Promise<T>,
  options: { isEmpty?: (value: T) => boolean } = {},
): AsyncResource<T> {
  const data = shallowRef<T | null>(null);
  const error = shallowRef<unknown>(null);
  const state = ref<ResourceState>("idle");

  async function run(): Promise<void> {
    state.value = "loading";
    error.value = null;
    try {
      const value = await loader();
      data.value = value;
      state.value = options.isEmpty?.(value) ? "empty" : "success";
    } catch (caught) {
      error.value = caught;
      state.value =
        caught instanceof ApiError && caught.status === 403
          ? "forbidden"
          : "error";
    }
  }

  return { data, error, state, run };
}

// The presentation states from the UI state contract (AsyncState.vue) that are
// derived from resolved data rather than the request lifecycle. useAsyncResource
// only ever produces the lifecycle states above; a view maps these on top once
// the node data is in hand.
export type DerivedNodeState = "stale" | "offline" | "partial";

// Map a node's computed status + runtime detection onto the derived contract
// states. Offline/Degraded come straight from the Central-computed status;
// partial means some runtimes were detected and some failed (mixed result).
// Returns null when the node is fully healthy (plain "success").
export function deriveNodeState(
  status: NodeStatus,
  runtimes: readonly NodeRuntime[] = [],
): DerivedNodeState | null {
  if (status === "offline") {
    return "offline";
  }
  if (status === "degraded") {
    return "stale";
  }
  const failed = runtimes.filter((rt) => !rt.available).length;
  if (failed > 0 && failed < runtimes.length) {
    return "partial";
  }
  return null;
}
