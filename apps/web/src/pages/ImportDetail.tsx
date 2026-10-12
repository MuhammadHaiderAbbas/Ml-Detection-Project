import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ImportRecord, ModelVersion, Page, RejectedRow, ScoringRun } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { PlainBadge, ProvenanceBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { formatBytes, formatNumber, humanize } from "../lib/format";

export function ImportDetailPage() {
  const { id } = useParams();
  const rec = useApi(() => api.get<ImportRecord>(`/imports/${id}`), [id], { pollMs: 4000 });
  const runs = useApi(() => api.get<ScoringRun[]>("/scoring-runs", { import_id: id }), [id], { pollMs: 4000 });
  const active = useApi(() => api.get<ModelVersion | null>("/models/active"), []);
  const [offset, setOffset] = useState(0);
  const rejected = useApi(() => api.get<Page<RejectedRow>>(`/imports/${id}/rejected-rows`, { limit: 50, offset }), [id, offset, rec.data?.status]);
  const { can } = useAuth();
  const [confirm, setConfirm] = useState<"score" | "cancel" | null>(null);
  const [msg, setMsg] = useState<string>();
  if (rec.error) return <ErrorState error={rec.error} onRetry={rec.reload} />;
  const r = rec.data;
  if (!r) return <Loading />;
  const scoredByActive = runs.data?.some((x) => x.model_version_id === active.data?.id && x.status !== "failed");

  return (
    <>
      <PageHeader title={`Import #${r.id}: ${r.dataset_name}@${r.dataset_version}`} description={r.original_filename}
        actions={<>
          {["queued", "running"].includes(r.status) && can("data.import") ? <button className="btn danger" onClick={() => setConfirm("cancel")}>Cancel import</button> : null}
          {r.status === "completed" && can("scoring.run") ? <button className="btn primary" disabled={!active.data || scoredByActive} onClick={() => setConfirm("score")}
            title={!active.data ? "No active model" : scoredByActive ? "Already scored by the active model" : undefined}>Score with active model</button> : null}
          <Link className="btn" to="/data-sources">Back</Link>
        </>} />
      {r.provenance === "synthetic_demo" ? <Banner kind="demo"><strong>Synthetic demo data.</strong> Generated for software testing only.</Banner> : null}
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      {r.errors.length ? <Banner kind="error"><strong>Import errors:</strong><ul style={{ margin: "4px 0 0" }}>{r.errors.map((e, i) => <li key={i}>{e}</li>)}</ul></Banner> : null}
      <div className="grid grid-2">
        <section className="card" aria-labelledby="rec-h">
          <div className="card-header"><h2 id="rec-h">Import record</h2></div>
          <dl className="kv">
            <dt>Status</dt><dd><PlainBadge>{humanize(r.status)}</PlainBadge></dd>
            <dt>Provenance</dt><dd><ProvenanceBadge provenance={r.provenance} /></dd>
            <dt>Import ID</dt><dd className="mono">{r.import_uid}</dd>
            <dt>File SHA-256</dt><dd className="mono">{r.file_sha256 ?? "—"}</dd>
            <dt>File size</dt><dd>{formatBytes(r.file_bytes)}</dd>
            <dt>Schema</dt><dd><code>{r.schema_id}</code></dd>
            <dt>Column mapping</dt><dd className="mono">{Object.keys(r.column_mapping).length ? JSON.stringify(r.column_mapping) : "none"}</dd>
            <dt>Data source</dt><dd>{r.data_source ?? "—"}</dd>
            <dt>Started</dt><dd><Time iso={r.started_at} /></dd>
            <dt>Completed</dt><dd><Time iso={r.completed_at} /></dd>
          </dl>
        </section>
        <section className="card" aria-labelledby="val-h">
          <div className="card-header"><h2 id="val-h">Validation summary</h2></div>
          <dl className="kv">
            <dt>Total rows</dt><dd className="num">{formatNumber(r.total_rows)}</dd>
            <dt>Accepted</dt><dd className="num">{formatNumber(r.accepted_rows)}</dd>
            <dt>Rejected</dt><dd className="num">{formatNumber(r.rejected_rows)}</dd>
            <dt>Duplicates</dt><dd className="num">{formatNumber(r.duplicate_rows)} ({r.duplicate_policy === "drop" ? `${formatNumber(r.duplicates_dropped)} dropped` : "kept"})</dd>
            <dt>Labels in file</dt><dd>{Object.entries(r.label_distribution).map(([k, v]) => `${k}: ${formatNumber(v)}`).join(" · ") || "—"}</dd>
          </dl>
          {Object.keys(r.rejection_reason_counts).length ? (
            <><h3 style={{ marginTop: 14 }}>Rejection reasons</h3>
              <table className="data"><tbody>{Object.entries(r.rejection_reason_counts).slice(0, 12).map(([k, v]) => <tr key={k}><td className="mono">{k}</td><td className="num">{formatNumber(v)}</td></tr>)}</tbody></table></>
          ) : null}
          {r.warnings.length ? <><h3 style={{ marginTop: 14 }}>Warnings</h3><ul>{r.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul></> : null}
        </section>
      </div>
      <section className="card" style={{ marginTop: 16 }} aria-labelledby="runs-h">
        <div className="card-header"><h2 id="runs-h">Scoring runs</h2></div>
        {runs.data?.length ? (
          <table className="data">
            <thead><tr><th>Run</th><th>Model</th><th>Status</th><th className="num">Events</th><th className="num">Scored</th><th className="num">Rejected</th><th className="num">Alerts</th><th className="num">Duration</th><th>Completed</th></tr></thead>
            <tbody>{runs.data.map((x) => (
              <tr key={x.id}>
                <td>#{x.id}</td><td><Link to={`/models/${x.model_version_id}`}>#{x.model_version_id}</Link></td>
                <td>{humanize(x.status)}{x.error ? <div className="field-error">{x.error}</div> : null}</td>
                <td className="num">{formatNumber(x.events_total)}</td><td className="num">{formatNumber(x.events_scored)}</td><td className="num">{formatNumber(x.events_rejected)}</td>
                <td className="num"><Link to={`/alerts?import_id=${r.id}&model_version_id=${x.model_version_id}`}>{formatNumber(x.alerts_created)}</Link></td>
                <td className="num">{x.duration_ms !== null ? `${(x.duration_ms / 1000).toFixed(2)} s` : "—"}</td><td><Time compact iso={x.completed_at} /></td>
              </tr>
            ))}</tbody>
          </table>
        ) : <p className="muted">Not scored yet.</p>}
      </section>
      <section className="card" style={{ marginTop: 16 }} aria-labelledby="rej-h">
        <div className="card-header"><h2 id="rej-h">Rejected rows</h2><span className="hint">row numbers refer to data rows in the file (header excluded)</span></div>
        {rejected.data ? (rejected.data.items.length ? (
          <>
            <table className="data"><thead><tr><th className="num">Row</th><th>Reasons</th></tr></thead>
              <tbody>{rejected.data.items.map((x) => <tr key={x.row_number}><td className="num">{x.row_number}</td><td className="mono">{x.reasons}</td></tr>)}</tbody></table>
            <Pagination total={rejected.data.total} limit={50} offset={offset} onChange={setOffset} />
          </>
        ) : <p className="muted">No rows were rejected.</p>) : <Loading />}
      </section>
      {confirm === "score" ? (
        <ConfirmDialog title="Score this import" confirmLabel="Start scoring" onCancel={() => setConfirm(null)}
          onConfirm={async () => { await api.post(`/imports/${r.id}/score`, {}); setConfirm(null); setMsg("Scoring started. Alerts appear when the run completes."); runs.reload(); }}>
          Every accepted event will be scored by the active model <code>{active.data?.version_id}</code>. Suspicious predictions create alerts with status “New”.
        </ConfirmDialog>
      ) : null}
      {confirm === "cancel" ? (
        <ConfirmDialog title="Cancel import" confirmLabel="Cancel import" danger onCancel={() => setConfirm(null)}
          onConfirm={async () => { await api.post(`/imports/${r.id}/cancel`); setConfirm(null); rec.reload(); }}>
          No events from this file will be stored.
        </ConfirmDialog>
      ) : null}
    </>
  );
}
