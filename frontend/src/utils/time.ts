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

// "3 分鐘前" for an instant in the past, for the places where *how long ago* is the
// point rather than the wall-clock value: a tunnel URL that the provider may have
// reassigned, or a node capability report that goes stale by construction. Callers pair
// it with `formatInstant` in a tooltip, because a relative label alone cannot be
// compared with a server log.
export function formatRelative(
  iso: string | null,
  now: number = Date.now(),
): string {
  if (!iso) {
    return "—";
  }
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) {
    return iso;
  }
  const seconds = Math.round((now - then) / 1000);
  const future = seconds < 0;
  const magnitude = Math.abs(seconds);
  const label =
    magnitude < 60
      ? `${magnitude} 秒`
      : magnitude < 3600
        ? `${Math.floor(magnitude / 60)} 分鐘`
        : magnitude < 86400
          ? `${Math.floor(magnitude / 3600)} 小時`
          : `${Math.floor(magnitude / 86400)} 天`;
  return future ? `${label}後` : `${label}前`;
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
