// PDF.js, configured once (ADR 0029 §12, plan/31/05 BP-07 §2).
//
// The ONLY module that imports the library and the only caller of
// `getDocument`; src/pdf/imports.test.ts fails the build otherwise. Everything
// here is loaded lazily with the first PDF, so none of it is in the page's
// initial bundle.
//
// What the pinned release (pdfjs-dist 6.3.289, reviewed in
// docs/security-review-p31.md) actually does with the locked options:
//
//   * `isEvalSupported` and `enableScripting` are not read by `getDocument` in
//     this release at all. The first has no code path left (glyphs are no
//     longer compiled with `new Function`); the second is read only by the
//     annotation layer and the viewer, neither of which is used. Both stay in
//     the locked set so a future release that reads them again inherits the
//     safe value. The structural controls are that no scripting sandbox is
//     imported or shipped (vite.config.ts copies wasm/ without QuickJS) and
//     that no annotation DOM is ever built.
//   * The worker is created here and handed to PDF.js as a port. Given a
//     `workerSrc` instead, PDF.js would fall back to parsing on the main thread
//     ("fake worker") if the worker failed to start; with a port it cannot.
//   * `onPassword` is answered by destroying the load. Its `updatePassword`
//     callback is never called: there is no password input anywhere (OD-8).

import {
  AnnotationMode,
  getDocument,
  PDFWorker,
  type PDFDocumentLoadingTask,
  type PDFPageProxy,
  type PageViewport,
  type RenderTask,
} from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

// ADR 0029 §4 (OD-2): refused before any page renders.
export const PDF_MAX_PAGES = 200;
// Per page; a timeout fails that page only (plan/31/05 BP-07 §3).
export const PDF_PAGE_TIMEOUT_MS = 10_000;

// Self-hosted by vite.config.ts from node_modules/pdfjs-dist; same origin, so
// the unchanged CSP (`connect-src 'self'`) covers the worker fetching them.
const ASSETS = `${import.meta.env.BASE_URL}pdfjs/`;

export const LOCKED_OPTIONS = Object.freeze({
  isEvalSupported: false,
  enableScripting: false,
  enableXfa: false,
  disableAutoFetch: true,
  disableStream: true,
  disableRange: true,
  stopAtErrors: true,
  // CJK documents need the CMaps; Traditional Chinese is the main audience.
  cMapUrl: `${ASSETS}cmaps/`,
  cMapPacked: true,
  standardFontDataUrl: `${ASSETS}standard_fonts/`,
  // JPX (OpenJPEG), JBIG2 and colour management (QCMS) decoders.
  wasmUrl: `${ASSETS}wasm/`,
  iccUrl: `${ASSETS}iccs/`,
});

/**
 * Whether this browser can run the pinned modern build. These four builtins
 * are called without a fallback in 6.3.289 (checked by grep at pin time); an
 * engine without them would fail part-way through a document, so it is told
 * `unsupported_browser` up front instead (OD-9).
 */
export function pdfSupported(): boolean {
  return (
    typeof Worker === "function" &&
    typeof (Map.prototype as { getOrInsertComputed?: unknown })
      .getOrInsertComputed === "function" &&
    typeof (Math as { sumPrecise?: unknown }).sumPrecise === "function" &&
    typeof (Promise as { try?: unknown }).try === "function" &&
    typeof (Uint8Array as { fromBase64?: unknown }).fromBase64 === "function"
  );
}

export interface PdfHandle {
  task: PDFDocumentLoadingTask;
  /** Tear down the document, PDF.js's worker handle and the Worker. Idempotent. */
  destroy(): Promise<void>;
  destroyed(): boolean;
}

// How long PDF.js gets to finish its own teardown before the worker is
// terminated regardless.
const TEARDOWN_GRACE_MS = 1_000;

export function openPdf(
  bytes: Uint8Array<ArrayBuffer>,
  options: { onPassword: () => void },
): PdfHandle {
  const worker = new Worker(workerUrl, { type: "module" });
  // `create` rather than the constructor: its parameters are typed with the
  // Worker a port may be (the constructor's generated type says `null`).
  const port = PDFWorker.create({ port: worker });
  // The locked options, then the two things that differ per document. Nothing
  // from the caller is spread in: there is no way to pass a URL or an option.
  const task = getDocument({ ...LOCKED_OPTIONS, data: bytes, worker: port });

  let teardown: Promise<void> | null = null;
  function destroy(): Promise<void> {
    if (!teardown) {
      teardown = (async () => {
        const graceful = task.destroy().catch(() => undefined);
        await Promise.race([
          graceful,
          new Promise((done) => setTimeout(done, TEARDOWN_GRACE_MS)),
        ]);
        port.destroy();
        worker.terminate();
      })();
    }
    return teardown;
  }

  task.onPassword = () => {
    options.onPassword();
    void destroy();
  };

  return { task, destroy, destroyed: () => teardown !== null };
}

/**
 * Paint one page. `AnnotationMode.ENABLE` draws annotation appearance streams
 * into the canvas and nothing else: no DOM for links, forms or attachments is
 * created, so nothing in the document is clickable (OD-4).
 */
export function renderPage(
  page: PDFPageProxy,
  canvas: HTMLCanvasElement,
  viewport: PageViewport,
): RenderTask {
  return page.render({
    canvas,
    viewport,
    annotationMode: AnnotationMode.ENABLE,
  });
}
