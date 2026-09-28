<script setup lang="ts">
// Page viewer for the read-only PDF preview (ADR 0029 §12, plan/31/05 BP-07 §3).
//
// One page at a time, drawn to a canvas by PDF.js's display layer. The document,
// its worker, every canvas and every render task belong to `useBinaryPreview`:
// canvases are registered with it and render tasks tracked by it, so any
// disposal trigger (close, session switch, sign-out) cancels and zeroes them
// even while this component is still mounted.
//
// Canvases are keyed per render and capped at 3. A page flip cancels and drops
// whatever was drawing for the page left; a zoom draws the same page again at
// the new resolution and swaps it in when done, so zooming never blanks the
// page. Each render has 10 s; a page that runs out fails on its own and the
// rest of the document still works.
//
// There is no text layer (OD-3) and no annotation DOM (OD-4): nothing in the
// document is selectable, clickable or submittable, and a screen reader hears
// "第 n／N 頁" — which the toolbar says out loud, too.

import {
  ChevronLeft,
  ChevronRight,
  Maximize2,
  ZoomIn,
  ZoomOut,
} from "lucide-vue-next";
import type { PDFDocumentProxy, PDFPageProxy, RenderTask } from "pdfjs-dist";
import {
  computed,
  nextTick,
  onBeforeUnmount,
  onMounted,
  ref,
  watch,
  type ComponentPublicInstance,
} from "vue";

import { IMAGE_MAX_PIXELS } from "../../composables/useBinaryPreview";
import { usePanZoom } from "../../composables/usePanZoom";
import { PDF_PAGE_TIMEOUT_MS, renderPage } from "../../pdf/setup";
import UiIconButton from "../ui/UiIconButton.vue";

const props = defineProps<{
  doc: PDFDocumentProxy;
  /** File name only. */
  name: string;
  register: (canvas: HTMLCanvasElement) => () => void;
  trackRender: (task: { cancel(): void }) => () => void;
}>();

const MAX_CANVASES = 3;

const viewport = ref<HTMLElement | null>(null);
const current = ref(1);
const pageInput = ref("1");
const total = computed(() => props.doc.numPages);
// The current page's size at scale 1, in PDF points (1/72 in).
const pageSize = ref<{ width: number; height: number } | null>(null);

// Fit the page to the viewport width. Vector content can be enlarged, so the
// fit is not capped at 1 the way an image's is.
const view = usePanZoom(viewport, {
  fit: (width) => width / (pageSize.value?.width ?? 612),
  maxScale: 6,
});
const { zoom, scale, maxZoom } = view;

interface Entry {
  id: number;
  page: number;
  scale: number;
  status: "drawing" | "done" | "failed";
  timedOut?: boolean;
}
// What the template renders. The canvas, task, timer and releases for each
// entry live outside reactive state.
const entries = ref<Entry[]>([]);
interface Held {
  canvas?: HTMLCanvasElement;
  task?: RenderTask;
  timer?: ReturnType<typeof setTimeout>;
  release: Array<() => void>;
}
const held = new Map<number, Held>();
let sequence = 0;
// Bumped by every page change and by unmount, so a slow `getPage` for a page
// the user has already left does not start drawing it.
let pageToken = 0;
let alive = true;

const mine = computed(() =>
  entries.value.filter((e) => e.page === current.value),
);
const shown = computed(
  () =>
    mine.value.filter((e) => e.status === "done").at(-1) ?? mine.value.at(-1),
);
const failed = computed(() =>
  mine.value.at(-1)?.status === "failed" ? mine.value.at(-1) : undefined,
);
const cssWidth = computed(() =>
  Math.max(1, Math.round((pageSize.value?.width ?? 612) * scale.value)),
);
const cssHeight = computed(() =>
  Math.max(1, Math.round((pageSize.value?.height ?? 792) * scale.value)),
);
const pageLabel = (page: number) => `第 ${page}／${total.value} 頁`;
const announcement = computed(() => pageLabel(current.value));

function drop(entry: Entry): void {
  const h = held.get(entry.id);
  if (h) {
    if (h.timer) clearTimeout(h.timer);
    if (entry.status === "drawing") h.task?.cancel();
    if (h.canvas) {
      h.canvas.width = 0;
      h.canvas.height = 0;
    }
    for (const release of h.release) release();
    held.delete(entry.id);
  }
  entries.value = entries.value.filter((e) => e.id !== entry.id);
}

function bindCanvas(id: number, el: Element | ComponentPublicInstance | null) {
  const h = held.get(id);
  if (!h || !(el instanceof HTMLCanvasElement) || h.canvas === el) return;
  h.canvas = el;
  h.release.push(props.register(el));
}

async function draw(page: PDFPageProxy, number: number): Promise<void> {
  const cssScale = scale.value;
  const entry: Entry = {
    id: ++sequence,
    page: number,
    scale: cssScale,
    status: "drawing",
  };
  held.set(entry.id, { release: [] });
  entries.value = [...entries.value, entry];
  while (entries.value.length > MAX_CANVASES) drop(entries.value[0]);
  await nextTick();
  const h = held.get(entry.id);
  if (!alive || !h?.canvas) return;

  // As sharp as the screen, and never over the pixel limit (ADR 0029 §4):
  // past it the canvas stays put and CSS scales it.
  const base = page.getViewport({ scale: 1 });
  let renderScale = cssScale * (globalThis.devicePixelRatio || 1);
  const pixels = base.width * base.height * renderScale * renderScale;
  if (pixels > IMAGE_MAX_PIXELS) {
    renderScale *= Math.sqrt(IMAGE_MAX_PIXELS / pixels);
  }
  const target = page.getViewport({ scale: renderScale });
  // PDF.js draws into the canvas at whatever size it already has; sizing the
  // backing store is the caller's job.
  h.canvas.width = Math.max(1, Math.floor(target.width));
  h.canvas.height = Math.max(1, Math.floor(target.height));
  const task = renderPage(page, h.canvas, target);
  h.task = task;
  h.release.push(props.trackRender(task));
  h.timer = setTimeout(() => {
    const live = entries.value.find((e) => e.id === entry.id);
    if (live) live.timedOut = true;
    task.cancel();
  }, PDF_PAGE_TIMEOUT_MS);

  try {
    await task.promise;
  } catch {
    const live = entries.value.find((e) => e.id === entry.id);
    // Cancelled because it was dropped: nothing to report. Otherwise this page,
    // and only this page, failed.
    if (live) live.status = "failed";
    if (h.timer) clearTimeout(h.timer);
    return;
  }
  clearTimeout(h.timer);
  const live = entries.value.find((e) => e.id === entry.id);
  if (!live) return;
  live.status = "done";
  // A successful attempt replaces only older attempts. A newer failure must
  // remain visible even if this older render finishes after it.
  for (const other of [...entries.value]) {
    if (other.id < entry.id && other.page === number) drop(other);
  }
}

async function showPage(number: number): Promise<void> {
  const token = ++pageToken;
  let page: PDFPageProxy;
  try {
    page = await props.doc.getPage(number);
  } catch {
    if (token !== pageToken || !alive) return;
    entries.value = [
      ...entries.value,
      { id: ++sequence, page: number, scale: 0, status: "failed" },
    ];
    return;
  }
  if (token !== pageToken || !alive) return;
  const base = page.getViewport({ scale: 1 });
  pageSize.value = { width: base.width, height: base.height };
  await nextTick();
  if (token !== pageToken || !alive) return;
  await draw(page, number);
}

function goTo(number: number): void {
  const next = Math.min(total.value, Math.max(1, Math.round(number) || 1));
  pageInput.value = String(next);
  if (next === current.value) return;
  current.value = next;
}

// Leaving a page cancels whatever was drawing for any other page.
watch(current, (number) => {
  for (const entry of [...entries.value]) {
    if (entry.page !== number) drop(entry);
  }
  void showPage(number);
});

// A settled zoom draws the page again at the new resolution. Until then the
// canvas already on screen is scaled by CSS, so the gesture feels immediate.
let zoomTimer: ReturnType<typeof setTimeout> | undefined;
watch(scale, (next) => {
  clearTimeout(zoomTimer);
  zoomTimer = setTimeout(() => {
    const on = shown.value;
    if (!on || Math.abs(on.scale - next) < 0.01) return;
    const token = pageToken;
    void props.doc.getPage(current.value).then((page) => {
      if (token === pageToken && alive) void draw(page, current.value);
    });
  }, 150);
});

function retryPage(): void {
  for (const entry of [...entries.value]) {
    if (entry.page === current.value && entry.status === "failed") drop(entry);
  }
  void showPage(current.value);
}

function commitInput(): void {
  goTo(Number(pageInput.value));
}

function onKey(event: KeyboardEvent): void {
  if (view.onZoomKey(event)) return;
  if (event.key === "ArrowRight" || event.key === "PageDown")
    goTo(current.value + 1);
  else if (event.key === "ArrowLeft" || event.key === "PageUp")
    goTo(current.value - 1);
  else return;
  event.preventDefault();
}

onMounted(() => {
  void showPage(current.value);
});
onBeforeUnmount(() => {
  alive = false;
  pageToken += 1;
  clearTimeout(zoomTimer);
  for (const entry of [...entries.value]) drop(entry);
});
</script>

<template>
  <div class="pdf-preview">
    <div
      ref="viewport"
      class="viewport"
      role="group"
      :aria-label="`${name}（PDF，${total} 頁）`"
      tabindex="0"
      @keydown="onKey"
      @pointerdown="view.onPointerDown"
      @pointermove="view.onPointerMove"
      @pointerup="view.onPointerEnd"
      @pointercancel="view.onPointerEnd"
      @pointerleave="view.onPointerEnd"
    >
      <div class="stage">
        <canvas
          v-for="entry in entries"
          v-show="entry === shown && entry.status !== 'failed'"
          :key="entry.id"
          :ref="(el) => bindCanvas(entry.id, el)"
          role="img"
          :aria-label="pageLabel(entry.page)"
          :data-rendered="entry.status === 'done' || undefined"
          draggable="false"
          :style="{ width: `${cssWidth}px`, height: `${cssHeight}px` }"
          @contextmenu.prevent
        />
        <div v-if="failed" class="page-error" role="alert">
          <p>
            {{
              failed.timedOut
                ? `第 ${failed.page} 頁無法在時限內顯示`
                : `第 ${failed.page} 頁無法顯示`
            }}
          </p>
          <button type="button" class="retry" @click="retryPage">
            重試此頁
          </button>
        </div>
      </div>
    </div>

    <p class="sr-only" aria-live="polite">{{ announcement }}</p>

    <div class="toolbar" role="toolbar" aria-label="PDF 翻頁與縮放">
      <p class="note">PDF 以影像顯示，螢幕報讀器無法讀取內文。</p>
      <div class="group">
        <UiIconButton
          label="上一頁"
          variant="secondary"
          :disabled="current <= 1"
          disabled-reason="已是第一頁"
          @click="goTo(current - 1)"
        >
          <ChevronLeft aria-hidden="true" />
        </UiIconButton>
        <label class="page">
          <input
            v-model="pageInput"
            type="text"
            inputmode="numeric"
            pattern="[0-9]*"
            autocomplete="off"
            aria-label="頁碼"
            @keydown.enter.prevent="commitInput"
            @blur="commitInput"
            @focus="($event.target as HTMLInputElement).select()"
          />
          <span aria-hidden="true">／{{ total }}</span>
        </label>
        <UiIconButton
          label="下一頁"
          variant="secondary"
          :disabled="current >= total"
          disabled-reason="已是最後一頁"
          @click="goTo(current + 1)"
        >
          <ChevronRight aria-hidden="true" />
        </UiIconButton>
      </div>
      <div class="group">
        <UiIconButton
          label="縮小"
          variant="secondary"
          :disabled="zoom <= 1"
          disabled-reason="已是符合寬度"
          @click="view.zoomOut"
        >
          <ZoomOut aria-hidden="true" />
        </UiIconButton>
        <UiIconButton
          label="符合寬度"
          variant="secondary"
          :pressed="zoom === 1"
          @click="view.fitToWidth"
        >
          <Maximize2 aria-hidden="true" />
        </UiIconButton>
        <UiIconButton
          label="放大"
          variant="secondary"
          :disabled="zoom >= maxZoom"
          disabled-reason="已是最大倍率"
          @click="view.zoomIn"
        >
          <ZoomIn aria-hidden="true" />
        </UiIconButton>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pdf-preview {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--surface-canvas);
}
.viewport {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
  touch-action: none;
  overscroll-behavior: contain;
}
.viewport:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: -2px;
}
/* `margin: auto` rather than grid centring, so a page wider than the viewport
   stays reachable on both edges. */
.stage {
  position: relative;
  display: flex;
  min-width: 100%;
  min-height: 100%;
  width: max-content;
  padding: 12px 0;
  box-sizing: border-box;
}
canvas {
  display: block;
  margin: 0 auto auto;
  box-shadow: 0 0 0 1px var(--border-subtle);
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
  -webkit-user-drag: none;
}
.page-error {
  position: absolute;
  inset: 0;
  display: grid;
  align-content: center;
  justify-items: center;
  gap: 8px;
  padding: 16px;
  font-size: 12px;
  color: var(--status-error-fg);
}
.page-error p {
  margin: 0;
}
.retry {
  min-height: var(--density-touch);
  padding: 0 14px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font-size: 12px;
  font-weight: 600;
}
.toolbar {
  flex: 0 0 auto;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: flex-end;
  gap: 6px 12px;
  padding: 6px 8px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-default);
}
.group {
  display: flex;
  align-items: center;
  gap: 6px;
}
/* The touch floor as the real box, not a pseudo-element. */
.toolbar :deep(.icon-btn) {
  width: var(--density-touch);
  height: var(--density-touch);
}
.note {
  margin: 0 auto 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.page {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
}
.page input {
  width: 5ch;
  min-height: var(--density-touch);
  padding: 0 6px;
  border: 1px solid var(--border-control);
  border-radius: var(--radius-control);
  background: var(--surface-raised);
  color: var(--text-primary);
  font: inherit;
  text-align: center;
}
.page input:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
}
/* A phone is narrow enough that the note takes its own row above the
   controls, rather than squeezing them. */
@media (max-width: 767px) {
  .page input {
    font-size: 1rem;
  }
  .note {
    flex-basis: 100%;
  }
  .toolbar {
    justify-content: space-between;
  }
}
</style>
