<script setup lang="ts">
// Canvas image viewer for the read-only binary preview (ADR 0029 §11).
//
// Paints an ImageBitmap it is handed and owns nothing: the bitmap and this
// canvas both belong to `useBinaryPreview`, which zeroes the canvas on every
// disposal. The canvas is registered with it on mount for exactly that.
//
// A canvas and never an <img>: an <img> offers "save image", "open image in
// new tab" and drag-out, and on iOS a long-press "Save to Photos" — a download
// by another name. The context menu is also suppressed here, because Firefox
// offers "Save Image As…" on a canvas too.
//
// Zoom: fit-to-width by default, ＋／−／fit buttons, pinch and drag through
// pointer events. The backing store never exceeds the image's own resolution,
// so it stays within the 16 777 216 px limit the header check already
// enforced; zooming past natural size is CSS scaling, not a larger canvas.

import { Maximize2, ZoomIn, ZoomOut } from "lucide-vue-next";
import { computed, onBeforeUnmount, onMounted, ref, watch } from "vue";

import { IMAGE_MAX_PIXELS } from "../../composables/useBinaryPreview";
import { usePanZoom } from "../../composables/usePanZoom";
import UiIconButton from "../ui/UiIconButton.vue";

const props = defineProps<{
  bitmap: ImageBitmap;
  /** File name only, for the accessible label. */
  name: string;
  /** GIF: the platform decodes the first frame only (OD-1). */
  firstFrameOnly?: boolean;
  register: (canvas: HTMLCanvasElement) => () => void;
}>();

const viewport = ref<HTMLElement | null>(null);
const canvas = ref<HTMLCanvasElement | null>(null);

// Fit to width, but never enlarge past the image's own size to do it. Eight
// screen pixels per image pixel is enough to inspect a screenshot; past that it
// is only a bigger blur.
const view = usePanZoom(viewport, {
  fit: (width) => Math.min(1, width / props.bitmap.width),
  maxScale: 8,
});
const { zoom, scale, maxZoom } = view;

const displayWidth = computed(() =>
  Math.max(1, Math.round(props.bitmap.width * scale.value)),
);
const displayHeight = computed(() =>
  Math.max(1, Math.round(props.bitmap.height * scale.value)),
);
const percent = computed(() => `${Math.round(scale.value * 100)}%`);
const label = computed(
  () => `${props.name}，${props.bitmap.width}×${props.bitmap.height} 像素`,
);

function draw(): void {
  const el = canvas.value;
  if (!el) return;
  const ratio = globalThis.devicePixelRatio || 1;
  // As sharp as the screen can show, never sharper than the image is.
  let factor = Math.min(1, scale.value * ratio || 1);
  const pixels = props.bitmap.width * props.bitmap.height * factor * factor;
  if (pixels > IMAGE_MAX_PIXELS) {
    factor *= Math.sqrt(IMAGE_MAX_PIXELS / pixels);
  }
  const width = Math.max(1, Math.floor(props.bitmap.width * factor));
  const height = Math.max(1, Math.floor(props.bitmap.height * factor));
  if (el.width !== width) el.width = width;
  if (el.height !== height) el.height = height;
  const context = el.getContext("2d");
  if (!context) return;
  context.imageSmoothingEnabled = true;
  context.imageSmoothingQuality = "high";
  context.clearRect(0, 0, width, height);
  context.drawImage(props.bitmap, 0, 0, width, height);
}

watch([() => props.bitmap, displayWidth, displayHeight], () => draw(), {
  flush: "post",
});

let unregister: (() => void) | null = null;
onMounted(() => {
  if (canvas.value) unregister = props.register(canvas.value);
  draw();
});
onBeforeUnmount(() => {
  unregister?.();
  unregister = null;
});
</script>

<template>
  <div class="image-preview">
    <div
      ref="viewport"
      class="viewport"
      role="group"
      aria-label="圖片檢視區（可捲動、以 ＋／− 縮放）"
      tabindex="0"
      @keydown="view.onZoomKey"
      @pointerdown="view.onPointerDown"
      @pointermove="view.onPointerMove"
      @pointerup="view.onPointerEnd"
      @pointercancel="view.onPointerEnd"
      @pointerleave="view.onPointerEnd"
    >
      <div class="stage">
        <canvas
          ref="canvas"
          role="img"
          :aria-label="label"
          draggable="false"
          :style="{ width: `${displayWidth}px`, height: `${displayHeight}px` }"
          @contextmenu.prevent
        />
      </div>
    </div>

    <div class="toolbar" role="toolbar" aria-label="圖片縮放">
      <p v-if="firstFrameOnly" class="note">動畫僅顯示第一幀</p>
      <span class="zoom" aria-live="polite">{{ percent }}</span>
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
</template>

<style scoped>
.image-preview {
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
/* `margin: auto` rather than grid centring: when the image is larger than the
   viewport, grid centring pushes its left and top edges out of scroll reach. */
.stage {
  display: flex;
  min-width: 100%;
  min-height: 100%;
  width: max-content;
}
canvas {
  display: block;
  margin: auto;
  /* No long-press menu, no selection highlight, no drag ghost (BP-OM-03). */
  -webkit-touch-callout: none;
  -webkit-user-select: none;
  user-select: none;
  -webkit-user-drag: none;
}
.toolbar {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  padding: 6px 8px;
  border-top: 1px solid var(--border-subtle);
  background: var(--surface-default);
}
/* The touch floor as the real box, not a pseudo-element: on a phone these are
   the only way to zoom without a pinch. */
.toolbar :deep(.icon-btn) {
  width: var(--density-touch);
  height: var(--density-touch);
}
.note {
  margin: 0 auto 0 0;
  font-size: 12px;
  color: var(--text-secondary);
}
.zoom {
  min-width: 4ch;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
  color: var(--text-secondary);
  text-align: right;
}
/* No safe-area inset here: PreviewPane is the element that touches the bottom
   edge on a phone and already applies it (plan/29 MS-02); a second one would
   double the gap under the toolbar. */
</style>
