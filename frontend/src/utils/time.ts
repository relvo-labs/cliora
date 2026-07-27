// Render an RFC 3339 UTC instant in the viewer's locale/timezone. Callers show
// the full instant in a title tooltip so the exact UTC value stays available.
export function formatInstant(iso: string | null): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString();
}

// The viewer's IANA time zone (e.g. "Asia/Taipei"). Rendered next to any column
// of instants: a localized timestamp without its zone is ambiguous the moment it
// is copied into a ticket or compared with a server log.
export function localTimeZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
}

// Humanize a duration given in seconds (e.g. daemon uptime) into a compact
// "Nd Nh Nm" / "Nh Nm" / "Nm" / "Ns" label. Returns "—" for null/invalid input.
export function formatDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) {
    return "—";
  }
  const total = Math.floor(seconds);
  const days = Math.floor(total / 86400);
  const hours = Math.floor((total % 86400) / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  if (days > 0) {
    return `${days}d ${hours}h ${minutes}m`;
  }
  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m`;
  }
  return `${total}s`;
}
