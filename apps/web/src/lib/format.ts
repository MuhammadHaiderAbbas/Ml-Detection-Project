export const PROVENANCE_LABELS: Record<string, string> = {
  synthetic_demo: "Synthetic demo",
  baseline_reproduction: "Baseline reproduction",
  controlled_experiment: "Controlled experiment",
  live_observation: "Live observation",
  original_dissertation: "Original dissertation",
};

const dtf = new Intl.DateTimeFormat(undefined, {
  year: "numeric", month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", timeZoneName: "short",
});

const dtfCompact = new Intl.DateTimeFormat(undefined, {
  month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit", timeZoneName: "short",
});

/** Compact local time for table cells, e.g. "Oct 11, 18:59 UTC". */
export function formatDateTimeCompact(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : dtfCompact.format(d);
}

/** Local time with an explicit zone name, e.g. "10 Oct 2026, 09:00:22 BST". */
export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : dtf.format(d);
}

export function formatNumber(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || Number.isNaN(n)) return "—";
  return n.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

export function formatPct(n: number | null | undefined, digits = 1): string {
  if (n === null || n === undefined) return "—";
  return `${(n * 100).toFixed(digits)}%`;
}

export function formatScore(n: number | null | undefined): string {
  return n === null || n === undefined ? "—" : n.toFixed(3);
}

export function formatBytes(n: number | null | undefined): string {
  if (!n && n !== 0) return "—";
  const units = ["B", "KB", "MB", "GB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
  return `${v.toFixed(i ? 1 : 0)} ${units[i]}`;
}

export function humanize(s: string): string {
  return s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());
}

export function shortHash(h: string | null | undefined, n = 12): string {
  return h ? h.slice(0, n) : "—";
}
