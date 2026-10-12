import type { ReactNode } from "react";
import { formatDateTime, formatDateTimeCompact } from "../lib/format";

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading" role="status" aria-live="polite">{label}</div>;
}

export function ErrorState({ error, onRetry }: { error: Error; onRetry?: () => void }) {
  return (
    <div className="banner error" role="alert">
      <strong>Something went wrong.</strong> {error.message}{" "}
      {onRetry ? <button className="btn small" onClick={onRetry}>Try again</button> : null}
    </div>
  );
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return <div className="empty"><h3>{title}</h3>{children ? <div>{children}</div> : null}</div>;
}

export function Banner({ kind = "info", children }: { kind?: "info" | "demo" | "error" | "success"; children: ReactNode }) {
  return <div className={`banner ${kind}`} role={kind === "error" ? "alert" : "note"}>{children}</div>;
}

export function DemoBanner() {
  return (
    <Banner kind="demo">
      <strong>Demonstration data present.</strong> Some records come from SYNTHETIC data generated for software
      testing. Their numbers say nothing about real intrusion-detection performance.
    </Banner>
  );
}

export function Time({ iso, compact }: { iso: string | null | undefined; compact?: boolean }) {
  if (!iso) return <span className="muted">—</span>;
  return <time dateTime={iso} title={`${iso} (UTC)`} style={compact ? { whiteSpace: "nowrap" } : undefined}>{compact ? formatDateTimeCompact(iso) : formatDateTime(iso)}</time>;
}
