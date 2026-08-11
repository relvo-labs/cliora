/**
 * Byte sizes, as a person reads them.
 *
 * Shared rather than written twice, because the two places that show sizes show the
 * *same* number from two angles — a run's disk footprint and the node quota that
 * footprint counts against — and two formatters would eventually disagree about where
 * MB becomes GB. Then「用了 4915 MB / 5.0 GB」ships, and the reader has to do the
 * conversion the page exists to save them.
 *
 * Binary units, matching the daemon's own quotas (`total_quota_bytes` is 8 GiB), with
 * the conventional short labels.
 */

const KIB = 1024;
const MIB = 1024 * KIB;
const GIB = 1024 * MIB;

/** A size, or an em dash when there is nothing to report.
 *
 * `null` is deliberately not `0 B`: "this was never measured" and "this is empty" are
 * different facts, and on a disk-usage row the second one reads as plenty of room.
 */
export function formatBytes(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (value < KIB) return `${value} B`;
  if (value < MIB) return `${Math.round(value / KIB)} KB`;
  if (value < GIB) return `${(value / MIB).toFixed(1)} MB`;
  return `${(value / GIB).toFixed(1)} GB`;
}
