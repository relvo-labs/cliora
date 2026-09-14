// The one place a layout decision reads the viewport width (plan/29 MS-01).
//
// Before this, three files each held their own literal: AppLayout's `< 768`,
// SessionWorkspaceView's `< 1024`, and a `@media (max-width: 1100px)` in that
// same view's stylesheet. The 1100 disagreed with the 1024 and the result was a
// file panel that, between 1024 and 1100px, was in the DOM, `display: none`, and
// had no control to open it — measured in plan/29 09-…md §4.1, not guessed.
// Three literals is how that happens; one source is the fix.
//
// CSS cannot import a TypeScript constant, so the four values still appear as
// literals in stylesheets. GATE-MS-BREAKPOINT holds that set closed: only
// 767/768/1023/1024/1439/1440 may appear in a `@media` width, and this file is
// the only place JavaScript may compare against a width at all.
//
// `matchMedia` rather than `resize`: a resize listener recomputes on every frame
// of a drag, and the only frame that can change the layout is the one that
// crosses a boundary — which is the single event `matchMedia` reports.

import { onScopeDispose, readonly, ref, watch, type Ref } from "vue";

/** `<768px`. Phones in portrait, and the narrow end of the acceptance matrix. */
export const NARROW = "(max-width: 767px)";
/** `768–1023px`. Tablets, phones in landscape. */
export const TABLET = "(min-width: 768px) and (max-width: 1023px)";
/** `1024–1439px`. Desktop, with the rail collapsed and the work header in one row. */
export const COMPACT = "(min-width: 1024px) and (max-width: 1439px)";

export interface Breakpoint {
  /** `<768px`. */
  isNarrow: Readonly<Ref<boolean>>;
  /** `768–1023px`. */
  isTablet: Readonly<Ref<boolean>>;
  /** `1024–1439px`. */
  isCompact: Readonly<Ref<boolean>>;
  /** `>=1440px`, the expanded desktop baseline. */
  isWide: Readonly<Ref<boolean>>;
  /**
   * `<1024px`. The two ranges with no room for a side-by-side file column, so
   * the panel becomes a drawer or a mode. Named here rather than re-OR-ed at
   * each call site, because that is the same scattering this file replaces.
   */
  belowDesktop: Readonly<Ref<boolean>>;
  /** `<1440px`. Everything that gets a collapsed rail and a compact work header. */
  belowWide: Readonly<Ref<boolean>>;
}

/**
 * Evaluate a width query without `matchMedia`.
 *
 * jsdom has no `matchMedia` (the same gap `applyTheme.prefersLight` and
 * `DashboardView` already guard for), and it dispatches no resize either, so the
 * honest fallback is one reading at setup with no listener. Tests that need a
 * boundary to actually move install a `matchMedia`; tests that only need a
 * starting width keep setting `innerWidth` and still get the right answer.
 */
function widthMatches(query: string): boolean {
  const width = typeof window === "undefined" ? 1440 : window.innerWidth;
  const min = /min-width:\s*(\d+)px/.exec(query);
  const max = /max-width:\s*(\d+)px/.exec(query);
  if (min && width < Number(min[1])) return false;
  if (max && width > Number(max[1])) return false;
  return true;
}

function track(query: string): Ref<boolean> {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") {
    return ref(widthMatches(query));
  }
  const mql = window.matchMedia(query);
  const state = ref(mql.matches);
  const onChange = (event: MediaQueryListEvent): void => {
    state.value = event.matches;
  };
  mql.addEventListener("change", onChange);
  // Tied to the effect scope rather than to a component's unmount: the
  // composable is callable from a store or another composable, and a listener
  // that outlives its owner is the leak that accumulates across a SPA session.
  onScopeDispose(() => mql.removeEventListener("change", onChange));
  return state;
}

export function useBreakpoint(): Breakpoint {
  const isNarrow = track(NARROW);
  const isTablet = track(TABLET);
  const isCompact = track(COMPACT);

  // Derived rather than tracked separately: four independent queries can
  // disagree for one frame while the browser applies them, and a layout that
  // briefly believes it is both narrow and wide is a flash the user sees.
  const isWide = ref(false);
  const belowDesktop = ref(false);
  const belowWide = ref(false);
  const sync = (): void => {
    belowDesktop.value = isNarrow.value || isTablet.value;
    belowWide.value = belowDesktop.value || isCompact.value;
    isWide.value = !belowWide.value;
  };
  sync();
  // One watcher over all three, not three watchers: the sources update in
  // separate event callbacks, and `sync` reads all three every time, so the
  // derived trio is never assembled from a half-applied set. A watcher created
  // inside an effect scope stops with it, so there is nothing to clean up here.
  watch([isNarrow, isTablet, isCompact], sync);

  return {
    isNarrow: readonly(isNarrow),
    isTablet: readonly(isTablet),
    isCompact: readonly(isCompact),
    isWide: readonly(isWide),
    belowDesktop: readonly(belowDesktop),
    belowWide: readonly(belowWide),
  };
}
