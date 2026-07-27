import { describe, expect, it } from "vitest";
import {
  control,
  createRequestId,
  encodeBinaryInput,
  encodeTextInput,
} from "./v1";

describe("protocol v1", () => {
  it("generates unique 26-char Crockford request IDs", () => {
    const pattern = /^[0-9A-HJKMNP-TV-Z]{26}$/;
    const ids = new Set<string>();
    for (let i = 0; i < 100; i += 1) {
      const id = createRequestId();
      expect(id).toMatch(pattern);
      ids.add(id);
    }
    expect(ids.size).toBe(100);
  });

  it("builds UTC attach without executable fields", () => {
    const message = control(
      "session.attach",
      "00000000-0000-4000-8000-000000000002",
      24,
      80,
    );
    expect(message.version).toBe(1);
    expect(message.timestamp.endsWith("Z")).toBe(true);
    expect(message.payload).not.toHaveProperty("command");
  });
  it("preserves UTF-8 and binary input bytes", () => {
    expect(Array.from(encodeTextInput("中"))).toEqual([228, 184, 173]);
    expect(Array.from(encodeBinaryInput("\x1b[A"))).toEqual([27, 91, 65]);
  });
});
