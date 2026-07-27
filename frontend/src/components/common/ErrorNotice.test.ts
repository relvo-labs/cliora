import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import { ApiError } from "../../api/client";
import { errorGuidance, knownErrorCodes } from "../../utils/errorCatalog";
import ErrorNotice from "./ErrorNotice.vue";

// Mounts the way a template uses it: the `retryable` key is *omitted* unless a test
// is exercising the override. Passing `retryable: undefined` explicitly is not the
// same thing — that is how the first version of this suite passed while the real
// AuditView usage rendered no retry control at all.
function render(error: unknown) {
  return mount(ErrorNotice, { props: { error } });
}

function renderWithOverride(error: unknown, retryable: boolean) {
  return mount(ErrorNotice, { props: { error, retryable } });
}

describe("ErrorNotice", () => {
  it("shows what happened, why, and what to do", () => {
    const text = render(
      new ApiError("NODE_OFFLINE", "Node is not connected", 409, "rid-1"),
    ).text();
    expect(text).toContain("Node is not connected");
    expect(text).toContain("沒有連線");
    expect(text).toContain("agentd doctor");
    expect(text).toContain("rid-1");
  });

  it("offers retry only where the catalog says it can work", () => {
    const retryable = render(new ApiError("NODE_OFFLINE", "offline", 409));
    expect(retryable.find("button").exists()).toBe(true);

    // Permanent: offering retry here would teach users to ignore the button.
    const permanent = render(new ApiError("FORBIDDEN", "no", 403));
    expect(permanent.find("button").exists()).toBe(false);
  });

  it("lets a caller override the retry affordance in both directions", () => {
    // `boolean | null` rather than an optional boolean: Vue casts an absent Boolean
    // prop to `false`, which would make "caller said no" and "caller said nothing"
    // identical and suppress every catalog-driven retry.
    expect(
      renderWithOverride(new ApiError("NODE_OFFLINE", "offline", 409), false)
        .find("button")
        .exists(),
    ).toBe(false);
    expect(
      renderWithOverride(new ApiError("FORBIDDEN", "no", 403), true)
        .find("button")
        .exists(),
    ).toBe(true);
  });

  it("renders a network failure, which has no code and no server message", () => {
    const text = render(new TypeError("Failed to fetch")).text();
    expect(text).toContain("無法連線至 Central");
    expect(text).toContain("NETWORK_UNREACHABLE");
    // Unknown codes still get guidance rather than an empty panel.
    expect(text).toContain("回報");
  });

  it("shows guidance for a code it does not know", () => {
    // Most likely a newer server. "Report it" is the honest next step, and a blank
    // panel would leave the user with nothing at all.
    const text = render(
      new ApiError("SOMETHING_NEW", "Unexpected", 500),
    ).text();
    expect(text).toContain("SOMETHING_NEW");
    expect(text).toContain("尚不認識");
  });

  it("does not invent a request id when the server did not send one", () => {
    expect(render(new ApiError("NOT_FOUND", "gone", 404)).text()).not.toContain(
      "request_id",
    );
  });

  it("keeps the forbidden wording indistinguishable between the two refusal layers", () => {
    // The server returns one message whether the role lacks the action or the user
    // does not own the resource, so a caller cannot learn a resource exists or who
    // owns it (ADR 0016). The UI must not undo that by guessing which it was.
    const guidance = errorGuidance("FORBIDDEN");
    expect(guidance.cause).toContain("或");
    expect(guidance.cause).not.toMatch(/擁有者是|owned by/);
  });

  it("gives every known code both a cause and a next step", () => {
    for (const code of knownErrorCodes()) {
      const guidance = errorGuidance(code);
      expect(guidance.cause.length, code).toBeGreaterThan(4);
      expect(guidance.nextStep.length, code).toBeGreaterThan(3);
    }
  });

  it("never puts a server path in the guidance", () => {
    // These strings are rendered to every user who triggers the error.
    for (const code of knownErrorCodes()) {
      const guidance = errorGuidance(code);
      const blob = `${guidance.cause} ${guidance.nextStep}`;
      expect(blob, code).not.toMatch(/\/(?:etc|var|root|home|usr)\//);
    }
  });
});
