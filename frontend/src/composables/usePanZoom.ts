// Zoom and pan for the read-only binary viewers (ADR 0029 §11, §12).
//
// Shared by the image and PDF viewers so both behave the same way under a
// finger, a mouse and a keyboard: fit-to-width by default, ＋／−／fit, pinch
// and drag through pointer events, +／−／0 on the keyboard, and a re-fit when
// the width changes (rotation, a resized window — plan/31/08 BP-10 #14).
//
// `touch-action: none` on the viewport hands both gestures to this code. The
// page keeps its own pinch zoom everywhere else; ADR 0029 §11 does not disable
// it.

import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  type Ref,
} from "vue";

const STEP = 1.25;

export interface PanZoomOptions {
  /** CSS pixels per content unit that fits the viewport's width. */
  fit: (containerWidth: number) => number;
  /** The largest scale, in the same units. */
  maxScale: number;
}

export function usePanZoom(
  viewport: Ref<HTMLElement | null>,
  options: PanZoomOptions,
) {
  const containerWidth = ref(0);
  // Multiplier over the fit scale; 1 is "fit to width".
  const zoom = ref(1);

  const fitScale = computed(() =>
    containerWidth.value > 0 ? options.fit(containerWidth.value) : 1,
  );
  const maxZoom = computed(() =>
    Math.max(1, options.maxScale / fitScale.value),
  );
  const scale = computed(() => fitScale.value * zoom.value);

  function clamp(value: number): number {
    return Math.min(maxZoom.value, Math.max(1, value));
  }

  // Zoom about a point of the viewport, so what is under the fingers (or the
  // centre, for the buttons) stays there.
  async function zoomTo(next: number, anchorX?: number, anchorY?: number) {
    const el = viewport.value;
    const target = clamp(next);
    if (target === zoom.value) return;
    const before = scale.value;
    const x = anchorX ?? (el ? el.clientWidth / 2 : 0);
    const y = anchorY ?? (el ? el.clientHeight / 2 : 0);
    const contentX = el ? (el.scrollLeft + x) / before : 0;
    const contentY = el ? (el.scrollTop + y) / before : 0;
    zoom.value = target;
    await nextTick();
    if (el) {
      el.scrollLeft = contentX * scale.value - x;
      el.scrollTop = contentY * scale.value - y;
    }
  }

  function zoomIn(): void {
    void zoomTo(zoom.value * STEP);
  }
  function zoomOut(): void {
    void zoomTo(zoom.value / STEP);
  }
  function fitToWidth(): void {
    zoom.value = 1;
  }

  /** +／−／0. True when the key was handled. */
  function onZoomKey(event: KeyboardEvent): boolean {
    if (event.key === "+" || event.key === "=") zoomIn();
    else if (event.key === "-") zoomOut();
    else if (event.key === "0") fitToWidth();
    else return false;
    event.preventDefault();
    return true;
  }

  // One pointer drags, two pinch.
  const pointers = new Map<number, { x: number; y: number }>();
  let pinch: { distance: number; zoom: number } | null = null;

  function distance(): number {
    const [a, b] = [...pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y);
  }

  function onPointerDown(event: PointerEvent): void {
    viewport.value?.setPointerCapture?.(event.pointerId);
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 2) pinch = { distance: distance(), zoom: zoom.value };
  }

  function onPointerMove(event: PointerEvent): void {
    const previous = pointers.get(event.pointerId);
    const el = viewport.value;
    if (!previous || !el) return;
    pointers.set(event.pointerId, { x: event.clientX, y: event.clientY });
    if (pointers.size === 1) {
      el.scrollLeft -= event.clientX - previous.x;
      el.scrollTop -= event.clientY - previous.y;
      return;
    }
    if (pointers.size === 2 && pinch && pinch.distance > 0) {
      const [a, b] = [...pointers.values()];
      const box = el.getBoundingClientRect();
      void zoomTo(
        pinch.zoom * (distance() / pinch.distance),
        (a.x + b.x) / 2 - box.left,
        (a.y + b.y) / 2 - box.top,
      );
    }
  }

  function onPointerEnd(event: PointerEvent): void {
    pointers.delete(event.pointerId);
    if (pointers.size < 2) pinch = null;
  }

  // A width change re-fits: the old zoom was relative to a width that no
  // longer exists.
  let observer: ResizeObserver | null = null;
  function measure(): void {
    const width = viewport.value?.clientWidth ?? 0;
    if (width !== containerWidth.value) {
      containerWidth.value = width;
      zoom.value = 1;
    }
  }
  onMounted(() => {
    measure();
    if (typeof ResizeObserver !== "undefined" && viewport.value) {
      observer = new ResizeObserver(() => measure());
      observer.observe(viewport.value);
    }
  });
  onBeforeUnmount(() => {
    observer?.disconnect();
    observer = null;
    pointers.clear();
  });

  return {
    containerWidth,
    zoom,
    scale,
    maxZoom,
    zoomIn,
    zoomOut,
    fitToWidth,
    onZoomKey,
    onPointerDown,
    onPointerMove,
    onPointerEnd,
  };
}
