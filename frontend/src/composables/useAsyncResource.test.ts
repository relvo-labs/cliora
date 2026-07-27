import { describe, expect, it } from "vitest";

import type { NodeRuntime } from "../api/dto";
import { deriveNodeState } from "./useAsyncResource";

function runtime(available: boolean): NodeRuntime {
  return {
    runtime: "claude",
    available,
    version: available ? "1.0" : null,
    binary_path: null,
    checked_at: null,
  };
}

describe("deriveNodeState", () => {
  it("maps offline status to offline", () => {
    expect(deriveNodeState("offline")).toBe("offline");
  });

  it("maps degraded status to stale", () => {
    expect(deriveNodeState("degraded")).toBe("stale");
  });

  it("returns null for a healthy online node with all runtimes available", () => {
    expect(
      deriveNodeState("online", [runtime(true), runtime(true)]),
    ).toBeNull();
  });

  it("returns partial when some runtimes failed detection", () => {
    expect(deriveNodeState("online", [runtime(true), runtime(false)])).toBe(
      "partial",
    );
  });

  it("does not report partial when every runtime failed", () => {
    // A total detection failure is not a mixed/partial result.
    expect(
      deriveNodeState("online", [runtime(false), runtime(false)]),
    ).toBeNull();
  });

  it("returns null for online with no runtimes reported", () => {
    expect(deriveNodeState("online", [])).toBeNull();
  });

  it("status precedence beats runtime detection", () => {
    expect(deriveNodeState("offline", [runtime(false)])).toBe("offline");
  });
});
