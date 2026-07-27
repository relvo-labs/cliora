import { describe, expect, it } from "vitest";

import { formatDuration, formatInstant } from "./time";

describe("formatDuration", () => {
  it("returns em dash for null/invalid input", () => {
    expect(formatDuration(null)).toBe("—");
    expect(formatDuration(-1)).toBe("—");
    expect(formatDuration(Number.NaN)).toBe("—");
  });

  it("formats sub-minute durations in seconds", () => {
    expect(formatDuration(0)).toBe("0s");
    expect(formatDuration(45)).toBe("45s");
  });

  it("formats minutes and hours", () => {
    expect(formatDuration(90)).toBe("1m");
    expect(formatDuration(3661)).toBe("1h 1m");
  });

  it("formats multi-day uptime", () => {
    expect(formatDuration(2 * 86400 + 3 * 3600 + 4 * 60)).toBe("2d 3h 4m");
  });
});

describe("formatInstant", () => {
  it("returns em dash for null", () => {
    expect(formatInstant(null)).toBe("—");
  });

  it("echoes back an unparseable string", () => {
    expect(formatInstant("not-a-date")).toBe("not-a-date");
  });
});
