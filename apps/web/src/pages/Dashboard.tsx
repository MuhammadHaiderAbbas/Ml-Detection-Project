import { Fragment } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DashboardSummary, ScoringRun, Timeline } from "../api/types";
import { useApi } from "../api/useApi";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { ImportSelect, ModelSelect } from "../components/Selectors";
import { DemoBanner, Empty, ErrorState, Loading, Time } from "../components/States";
import { TimelineChart } from "../components/TimelineChart";
import { AlertsTable } from "./Alerts";
import { RANGE_PRESETS, sinceFromPreset, useUrlFilters } from "../lib/filters";
import { formatNumber, formatPct, humanize } from "../lib/format";
import type { Alert, Page } from "../api/types";

function Kpi({ label, value, sub, to, definition, unavailable, text }: { label: string; value: string; sub?: string; to: string; definition?: string; unavailable?: boolean; text?: boolean }) {
  return (
    <Link className="kpi" to={to} title={definition}>
      <div className="label">{label}{definition ? <Icon name="info" size={13} /> : null}</div>
      <div className={`value${unavailable ? " unavailable" : text ? " text" : ""}`}>{value}</div>
      {sub ? <div className="sub">{sub}</div> : null}
    </Link>
  );
}

function BarList({ rows, to, header = "Address", mono = true }: { rows: { value: string; alerts: number }[]; to: (v: string) => string; header?: string; mono?: boolean }) {
  if (!rows.length || rows.every((r) => r.alerts === 0)) return <Empty title="No flagged traffic">Nothing has been flagged for this selection.</Empty>;
  const max = Math.max(1, ...rows.map((r) => r.alerts));
  return (
    <table className="data">
      <thead><tr><th>{header}</th><th className="num">Alerts</th><th style={{ width: "40%" }}><span className="sr-only">Share</span></th></tr></thead>
      <tbody>
        {rows.map((r) => (
          <tr key={r.value}>
            <td><Link to={to(r.value)} className={mono ? "mono" : undefined}>{mono ? r.value : humanize(r.value)}</Link></td>
            <td className="num">{formatNumber(r.alerts)}</td>
            <td><div className="bar-inline" style={{ width: `${(r.alerts / max) * 100}%` }} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function DashboardPage() {
  const f = useUrlFilters();
  const importId = f.get("import_id");
  const modelId = f.get("model_version_id");
  const range = f.get("range");
  const severity = f.get("severity");
  const since = sinceFromPreset(range);
  const q = { import_id: importId, model_version_id: modelId, since };

  const summary = useApi(() => api.get<DashboardSummary>("/dashboard/summary", q), [importId, modelId, range], { pollMs: 30000 });
  const timeline = useApi(() => api.get<Timeline>("/dashboard/timeline", { import_id: importId, model_version_id: modelId, bucket: f.get("bucket") || "hour" }),
    [importId, modelId, f.get("bucket")]);
  const recent = useApi(() => api.get<Page<Alert>>("/alerts", { ...q, severity: severity || undefined, limit: 8 }), [importId, modelId, range, severity], { pollMs: 30000 });
  const runs = useApi(() => api.get<ScoringRun[]>("/scoring-runs", { import_id: importId }), [importId]);

  const s = summary.data;
  const alertQs = new URLSearchParams();
  if (importId) alertQs.set("import_id", importId);
  if (modelId) alertQs.set("model_version_id", modelId);
  const withQs = (extra: string) => `/alerts?${[alertQs.toString(), extra].filter(Boolean).join("&")}`;
  const open = s ? s.alerts_by_status.new + s.alerts_by_status.investigating : 0;
  const closed = s ? s.alerts_by_status.resolved + s.alerts_by_status.false_positive : 0;

  return (
    <>
      <PageHeader title="Dashboard" description="Every number here comes from database records. Hover a tile for its counting rule; click it for the underlying records." />
      <div className="filters" role="group" aria-label="Dashboard filters">
        <label className="field">Time range (processing time)
          <select value={range} onChange={(e) => f.set({ range: e.target.value })}>
            {RANGE_PRESETS.map((r) => <option key={r.value} value={r.value}>{r.label}</option>)}
          </select>
        </label>
        <ImportSelect value={importId} onChange={(v) => f.set({ import_id: v })} />
        <ModelSelect value={modelId} onChange={(v) => f.set({ model_version_id: v })} />
        <label className="field">Severity (recent alerts)
          <select value={severity} onChange={(e) => f.set({ severity: e.target.value })}>
            <option value="">All</option><option value="critical">Critical</option><option value="high">High</option>
            <option value="medium">Medium</option><option value="low">Low</option>
          </select>
        </label>
      </div>

      {summary.error ? <ErrorState error={summary.error} onRetry={summary.reload} /> : null}
      {!s && summary.loading ? <Loading /> : null}
      {s ? (
        <div className={summary.loading ? "refetching stack" : "stack"}>
          {s.demo_data_present ? <DemoBanner /> : null}
          <div className="grid grid-kpi">
            <Kpi label="Events processed" value={formatNumber(s.events_processed)} to={`/traffic${importId ? `?import_id=${importId}` : ""}`}
              sub={`${formatNumber(s.events_scored)} scored`} definition={s.definitions.events_processed} />
            <Kpi label="Suspicious predictions" value={formatNumber(s.suspicious_predictions)}
              sub={s.events_scored ? `${formatPct(s.suspicious_predictions / s.events_scored)} of scored events` : undefined}
              to={`/traffic?suspicious=1${importId ? `&import_id=${importId}` : ""}`} definition={s.definitions.suspicious_predictions} />
            <Kpi label="High-priority open alerts" value={formatNumber(s.high_priority_open_alerts)}
              to={withQs("status=new&status=investigating&severity=high&severity=critical")} definition={s.definitions.high_priority_alerts} />
            <Kpi label="Confirmed attacks" unavailable={s.confirmed_attacks === null}
              value={s.confirmed_attacks === null ? "Unavailable" : formatNumber(s.confirmed_attacks)}
              sub={s.confirmed_attacks === null ? "No analyst decisions yet" : "Analyst-confirmed incidents"}
              to="/incidents?disposition=confirmed_attack" definition={s.definitions.confirmed_attacks ?? s.confirmed_attacks_note ?? undefined} />
            <Kpi label="Open alerts" value={formatNumber(open)} sub={`${formatNumber(s.alerts_by_status.new)} new · ${formatNumber(s.alerts_by_status.investigating)} investigating`}
              to={withQs("status=new&status=investigating")} definition={s.definitions.alerts_by_status} />
            <Kpi label="Closed alerts" value={formatNumber(closed)} sub={`${formatNumber(s.alerts_by_status.resolved)} resolved · ${formatNumber(s.alerts_by_status.false_positive)} false positive`}
              to={withQs("status=resolved&status=false_positive")} definition={s.definitions.alerts_by_status} />
            <Kpi label="Active model" text value={s.active_model ? s.active_model.version_id.split("@")[0] : "None"} unavailable={!s.active_model}
              sub={s.active_model ? `Activated ${new Date(s.active_model.activated_at).toLocaleDateString()}` : "Approve and activate a model"}
              to={s.active_model ? `/models/${s.active_model.id}` : "/models"} />
            <Kpi label="Last approved evaluation" text unavailable={!s.last_approved_evaluation}
              value={s.last_approved_evaluation ? new Date(s.last_approved_evaluation.approved_at).toLocaleDateString() : "None"}
              sub={s.last_approved_evaluation?.experiment_id ?? undefined}
              to={s.last_approved_evaluation ? `/models/${s.last_approved_evaluation.model_id}` : "/models"} />
            <Kpi label="Drift monitoring" text unavailable={s.drift_monitoring.status === "not_configured"}
              value={s.drift_monitoring.status === "not_configured" ? "No analyses yet" : `${Object.values(s.drift_monitoring.open_events).reduce((x, y) => x + y, 0)} open events`}
              sub={s.drift_monitoring.status === "not_configured" ? "Run a drift analysis" : Object.entries(s.drift_monitoring.open_events).map(([k, v]) => `${v} ${k}`).join(" · ") || "No open drift events"}
              to="/drift" definition={s.definitions.drift_monitoring ?? s.drift_monitoring.note} />
            <Kpi label="Ingestion health" value={s.ingestion.recent[0] ? s.ingestion.recent[0].status.replace(/_/g, " ") : "No imports"} unavailable
              sub={`${s.ingestion.failed_in_range} failed in range`} to="/data-sources" definition={s.definitions.ingestion_health} />
            <Kpi label="Processing latency" text unavailable={!s.processing_latency}
              value={s.processing_latency ? `${s.processing_latency.ms_per_event.toFixed(3)} ms/event` : "No runs yet"}
              sub={s.processing_latency ? `${formatNumber(s.processing_latency.events)} events in ${(s.processing_latency.duration_ms / 1000).toFixed(1)} s` : undefined}
              to="/data-sources" definition={s.definitions.processing_latency} />
          </div>

          <section className="card" aria-labelledby="tl-h">
            <div className="card-header">
              <h2 id="tl-h">Traffic and suspicious events over time</h2>
              <span className="hint">events per interval</span>
              <div className="right toggle-group" role="group" aria-label="Interval">
                {["minute", "hour", "day"].map((b) => (
                  <button key={b} aria-pressed={(f.get("bucket") || "hour") === b} onClick={() => f.set({ bucket: b === "hour" ? null : b })}>{b[0].toUpperCase() + b.slice(1)}</button>
                ))}
              </div>
            </div>
            {timeline.error ? <ErrorState error={timeline.error} onRetry={timeline.reload} /> : null}
            {timeline.data ? (timeline.data.points.length ? <div className={timeline.loading ? "refetching" : ""}><TimelineChart data={timeline.data} /></div>
              : <Empty title="No timestamped events">Import data with a timestamp column to see the timeline.</Empty>) : timeline.loading ? <Loading /> : null}
          </section>

          <div className="grid grid-wide-left">
            <section className="card" aria-labelledby="ra-h">
              <div className="card-header"><h2 id="ra-h">Recent alerts</h2><Link className="right" to={withQs(severity ? `severity=${severity}` : "")}>View all</Link></div>
              {recent.data ? (recent.data.items.length ? <AlertsTable alerts={recent.data.items} compact /> : <Empty title="No alerts">Nothing matches this selection.</Empty>) : <Loading />}
            </section>
            <section className="card" aria-labelledby="sev-h">
              <div className="card-header"><h2 id="sev-h">Alerts by severity</h2><span className="hint">triage priority, all statuses</span></div>
              <BarList rows={["critical", "high", "medium", "low"].map((k) => ({ value: k, alerts: s.alerts_by_severity[k] ?? 0 }))}
                to={(v) => withQs(`severity=${v}`)} header="Severity" mono={false} />
            </section>
          </div>

          <div className="grid grid-2">
            <section className="card" aria-labelledby="src-h">
              <div className="card-header"><h2 id="src-h">Most flagged sources</h2><span className="hint">{s.definitions.top_sources}</span></div>
              <BarList rows={s.top_sources} to={(v) => withQs(`source=${encodeURIComponent(v)}`)} />
            </section>
            <section className="card" aria-labelledby="dst-h">
              <div className="card-header"><h2 id="dst-h">Most flagged destinations</h2></div>
              <BarList rows={s.top_destinations} to={(v) => withQs(`destination=${encodeURIComponent(v)}`)} />
            </section>
          </div>

          <section className="card" aria-labelledby="perf-h">
            <div className="card-header">
              <h2 id="perf-h">Model performance history</h2>
              <span className="hint">measured against labels supplied with each imported file, not analyst-confirmed outcomes</span>
            </div>
            {runs.data?.length ? (
              <div className="table-wrap">
                <table className="data">
                  <thead><tr><th>Scoring run</th><th>Completed</th><th>Import</th><th>Model</th><th className="num">Events</th><th className="num">Accuracy</th><th className="num">Attack recall</th><th className="num">False-positive rate</th><th>Status</th></tr></thead>
                  <tbody>
                    {runs.data.map((r) => {
                      const b = r.label_metrics?.binary_attack_vs_benign;
                      return (
                        <tr key={r.id}>
                          <td>#{r.id}</td><td><Time compact iso={r.completed_at} /></td>
                          <td><Link to={`/data-sources/${r.import_id}`}>#{r.import_id}</Link></td>
                          <td><Link to={`/models/${r.model_version_id}`}>#{r.model_version_id}</Link></td>
                          <td className="num">{formatNumber(r.events_total)}</td>
                          <td className="num">{formatPct(r.label_metrics?.accuracy)}</td>
                          <td className="num">{formatPct(b?.recall_detection_rate)}</td>
                          <td className="num">{formatPct(b?.false_positive_rate, 2)}</td>
                          <td>{r.status}{r.error ? <span className="field-error"> — {r.error}</span> : null}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : runs.loading ? <Loading /> : <Empty title="No scoring runs">Score an import with the active model to see performance here.</Empty>}
          </section>

          <details className="card">
            <summary><strong>Counting rules</strong></summary>
            <dl className="kv" style={{ marginTop: 12 }}>
              {Object.entries(s.definitions).map(([k, v]) => (<Fragment key={k}><dt>{humanize(k)}</dt><dd>{v}</dd></Fragment>))}
            </dl>
          </details>
        </div>
      ) : null}
    </>
  );
}
