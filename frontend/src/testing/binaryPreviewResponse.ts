// Test helper: the response Central sends for a successful binary preview
// (ADR 0029 §6 header set), built from a payload, so the tests that stub the
// API exercise the real body reader rather than a shortcut around it.

import type { BinaryPreviewPayload } from "../api/dto";

export function previewResponse(payload: BinaryPreviewPayload): Response {
  const { meta, bytes } = payload;
  const headers: Record<string, string> = {
    "Content-Type": "application/octet-stream",
    "Content-Length": String(meta.size),
    "X-Content-Type-Options": "nosniff",
    "X-Cliora-Preview-Mime": meta.mime,
    "X-Cliora-Preview-Kind": meta.kind,
  };
  if (meta.width !== undefined)
    headers["X-Cliora-Preview-Width"] = String(meta.width);
  if (meta.height !== undefined)
    headers["X-Cliora-Preview-Height"] = String(meta.height);
  return new Response(bytes, { status: 200, headers });
}
