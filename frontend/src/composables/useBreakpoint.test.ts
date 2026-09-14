// The one place a layout decision reads the viewport (plan/29 MS-01/MS-22).
//
// Two properties matter here and neither is obvious from the implementation:
// that it listens rather than polls, and that it stops listening. The first is
// why it exists at all — a resize listener recomputes on every frame of a drag
// and only the boundary-crossing frame can change anything — and the second is
// the kind of leak that never fails a test, it just accumulates across a
// session until something is slow.

import { effectScope } from "vue";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NARROW, useBreakpoint } from "./useBreakpoint";

interface FakeQuery {
  media: string;
  matches: boolean;
  listeners: Set<(event: MediaQueryListEvent) => void>;
}

const queries: FakeQuery[] = [];
let removed = 0;

/** A `matchMedia` that answers width queries from one number and can move. */
function installMatchMedia(width: number): (next: number) => void {
  queries.length = 0;
  removed = 0;
  let current = width;
  const evaluate = (media: string, w: number): boolean => {
    const min = /min-width:\s*(\d+)px/.exec(media);
    const max = /max-width:\s*(\d+)px/.exec(media);
    if (min && w < Number(min[1])) return false;
    if (max && w > Number(max[1])) return false;
    return true;
  };
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    configurable: true,
    value: (media: string) => {
      const entry: FakeQuery = {
        media,
        matches: evaluate(media, current),
        listeners: new Set(),
      };
      queries.push(entry);
      return {
        get matches() {
          return entry.matches;
        },
        media,
        addEventListener: (_: string, fn: (e: MediaQueryListEvent) => void) =>
          entry.listeners.add(fn),
        removeEventListener: (
          _: string,
          fn: (e: MediaQueryListEvent) => void,
        ) => {
          entry.listeners.delete(fn);
          removed += 1;
        },
        addListener: vi.fn(),
        removeListener: vi.fn(),
        dispatchEvent: vi.fn(),
        onchange: null,
      };
    },
  });
  return (next: number) => {
    current = next;
    for (const entry of queries) {
      const matches = evaluate(entry.media, next);
      if (matches === entry.matches) continue;
      entry.matches = matches;
      for (const fn of entry.listeners) {
        fn({ matches } as MediaQueryListEvent);
      }
    }
  };
}

afterEach(() => {
  // @ts-expect-error — removing the stub is the point.
  delete window.matchMedia;
});

describe("useBreakpoint", () => {
  for (const [width, expected] of [
    [390, "isNarrow"],
    [767, "isNarrow"],
    [768, "isTablet"],
    [1023, "isTablet"],
    [1024, "isCompact"],
    [1439, "isCompact"],
    [1440, "isWide"],
    [1920, "isWide"],
  ] as const) {
    it(`${width}px 落在 ${expected}，而且只有它`, () => {
      installMatchMedia(width);
      const scope = effectScope();
      scope.run(() => {
        const bp = useBreakpoint();
        const exclusive = ["isNarrow", "isTablet", "isCompact", "isWide"];
        for (const name of exclusive) {
          expect(bp[name as keyof typeof bp].value, `${width}px: ${name}`).toBe(
            name === expected,
          );
        }
        // The cumulative pair is derived, never tracked separately: four
        // independent queries can disagree for one frame, and a layout that
        // briefly believes it is both narrow and wide is a flash the user sees.
        expect(bp.belowDesktop.value).toBe(width < 1024);
        expect(bp.belowWide.value).toBe(width < 1440);
      });
      scope.stop();
    });
  }

  it("跨越界限時更新，而且是被通知的不是被輪詢的", () => {
    const move = installMatchMedia(1440);
    const scope = effectScope();
    scope.run(() => {
      const bp = useBreakpoint();
      expect(bp.isWide.value).toBe(true);

      move(390);
      expect(bp.isNarrow.value).toBe(true);
      expect(bp.isWide.value).toBe(false);
      expect(bp.belowDesktop.value).toBe(true);

      move(1024);
      expect(bp.isCompact.value).toBe(true);
      expect(bp.belowDesktop.value).toBe(false);
      expect(bp.belowWide.value).toBe(true);
    });
    scope.stop();
  });

  it("不用 resize：改變 innerWidth 而不發事件時不會自己變", () => {
    const move = installMatchMedia(1440);
    const scope = effectScope();
    scope.run(() => {
      const bp = useBreakpoint();
      Object.defineProperty(window, "innerWidth", {
        value: 390,
        configurable: true,
        writable: true,
      });
      window.dispatchEvent(new Event("resize"));
      // Still wide: nothing crossed a boundary as far as matchMedia is
      // concerned, and that is the whole difference from what this replaces.
      expect(bp.isWide.value).toBe(true);
      move(390);
      expect(bp.isNarrow.value).toBe(true);
    });
    scope.stop();
  });

  it("scope 結束時解除每一個監聽", () => {
    installMatchMedia(1440);
    const scope = effectScope();
    scope.run(() => useBreakpoint());
    expect(queries).toHaveLength(3);
    scope.stop();
    expect(removed).toBe(3);
  });

  it("沒有 matchMedia 時退回讀一次 innerWidth，不掛監聽", () => {
    // jsdom's own gap, and the environment half the unit suite runs in. The
    // fallback is one reading with no listener rather than a polyfill: jsdom
    // dispatches no resize either, so there would be nothing to listen to.
    // @ts-expect-error — the absence is the case under test.
    delete window.matchMedia;
    Object.defineProperty(window, "innerWidth", {
      value: 390,
      configurable: true,
      writable: true,
    });
    const scope = effectScope();
    scope.run(() => {
      const bp = useBreakpoint();
      expect(bp.isNarrow.value).toBe(true);
      expect(bp.belowWide.value).toBe(true);
    });
    scope.stop();
  });

  it("NARROW 與 CSS 斷點是同一個字串", () => {
    // MS-D-05: the theme override and the layout breakpoint must not be able to
    // disagree, so applyTheme imports this constant rather than restating it.
    expect(NARROW).toBe("(max-width: 767px)");
  });
});
