import type { AlertStatus, Disposition, Severity } from "../api/types";
import { PROVENANCE_LABELS } from "../lib/format";
import { Icon, type IconName } from "./Icon";

// Severity is a triage priority. Status colours always come with an icon and a text label.
const SEVERITY: Record<Severity, { color: string; icon: IconName; label: string }> = {
  low: { color: "var(--text-muted)", icon: "circle", label: "Low" },
  medium: { color: "var(--status-warning)", icon: "info", label: "Medium" },
  high: { color: "var(--status-serious)", icon: "alert", label: "High" },
  critical: { color: "var(--status-critical)", icon: "alert", label: "Critical" },
};

export function SeverityBadge({ severity }: { severity: Severity }) {
  const s = SEVERITY[severity] ?? SEVERITY.low;
  return (
    <span className="badge" title="Triage priority from the configured severity rules, not a verified severity">
      <span style={{ color: s.color, display: "inline-flex" }}><Icon name={s.icon} size={12} /></span>
      {s.label}
    </span>
  );
}

const ALERT_STATUS: Record<AlertStatus, { icon: IconName; label: string }> = {
  new: { icon: "bell", label: "New" },
  investigating: { icon: "search", label: "Investigating" },
  resolved: { icon: "check", label: "Resolved" },
  false_positive: { icon: "x", label: "False positive" },
};

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  const s = ALERT_STATUS[status];
  return <span className="badge"><Icon name={s.icon} size={12} />{s.label}</span>;
}

const DISPOSITION: Record<Disposition, string> = {
  undetermined: "Undetermined", confirmed_attack: "Confirmed attack", benign: "Benign",
  false_positive: "False positive", inconclusive: "Inconclusive",
};

export function DispositionBadge({ disposition }: { disposition: Disposition }) {
  const icon: IconName = disposition === "confirmed_attack" ? "alert" : disposition === "undetermined" ? "clock" : "check";
  const color = disposition === "confirmed_attack" ? "var(--status-critical)" : undefined;
  return (
    <span className="badge" title="Analyst decision">
      <span style={{ color, display: "inline-flex" }}><Icon name={icon} size={12} /></span>
      {DISPOSITION[disposition]}
    </span>
  );
}

export function PlainBadge({ children, icon }: { children: React.ReactNode; icon?: IconName }) {
  return <span className="badge">{icon ? <Icon name={icon} size={12} /> : null}{children}</span>;
}

export function ProvenanceBadge({ provenance }: { provenance: string }) {
  const demo = provenance === "synthetic_demo";
  return (
    <span className="badge" style={demo ? { background: "var(--demo-bg)", borderColor: "var(--demo-border)", color: "var(--demo-ink)" } : undefined}
      title={demo ? "Generated data for software demonstration only" : undefined}>
      {demo ? <Icon name="flask" size={12} /> : null}
      {PROVENANCE_LABELS[provenance] ?? provenance}
    </span>
  );
}

export function ModelStatusBadge({ status }: { status: string }) {
  const icons: Record<string, IconName> = { active: "check", approved: "audit", candidate: "clock", evaluating: "search", archived: "database", rejected: "x" };
  return <span className="badge"><Icon name={icons[status] ?? "circle"} size={12} />{status.charAt(0).toUpperCase() + status.slice(1)}</span>;
}
