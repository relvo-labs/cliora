// The event's own words, assembled from the payload.
//
// Kept in the browser rather than sent by the server so the wording can change without a
// migration. Extracted from `ProjectDetailView.vue` when it was split (PX-64) because
// **two** pages render a timeline — Overview shows the last ten and Activity shows all of
// them — and a duplicated switch is two places for a new event kind to be forgotten in.

export function describeActivity(
  kind: string,
  payload: Record<string, unknown>,
): string {
  const path = typeof payload.path === "string" ? payload.path : "";
  const node = typeof payload.node_name === "string" ? payload.node_name : "";
  switch (kind) {
    case "project.created":
      return String(payload.name ?? "");
    case "project.updated":
      return payload.from && payload.to
        ? `${payload.from} → ${payload.to}`
        : ((payload.changed as string[] | undefined)?.join(", ") ?? "");
    case "workspace.bound":
    case "workspace.unbound":
      return node ? `${node}:${path}` : path;
    case "session.started":
      return String(payload.name ?? payload.runtime ?? "");
    case "session.ended":
      return String(payload.status ?? "");
    default:
      return "";
  }
}
