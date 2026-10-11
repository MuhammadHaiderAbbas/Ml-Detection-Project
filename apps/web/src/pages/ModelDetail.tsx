import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { ModelDetail, ModelHistory } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { ModelStatusBadge, ProvenanceBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { MetricsView } from "../components/MetricsView";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { humanize } from "../lib/format";
import { useUserMap } from "./Alerts";

type Action = { path: string; label: string; body: string; danger?: boolean };

export function ModelDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const users = useUserMap();
  const model = useApi(() => api.get<ModelDetail>(`/models/${id}`), [id]);
  const hist = useApi(() => api.get<ModelHistory[]>(`/models/${id}/history`), [id]);
  const [action, setAction] = useState<Action | null>(null);
  const [msg, setMsg] = useState<string>();
  if (model.error) return <ErrorState error={model.error} onRetry={model.reload} />;
  const m = model.data;
  if (!m) return <Loading />;
  const admin = user?.role === "admin";
  const actions: Action[] = [];
  if (["candidate", "evaluating"].includes(m.status)) {
    actions.push({ path: "approve", label: "Approve", body: "Approval confirms the recorded test-set evaluation was reviewed. It does not activate the model." });
    actions.push({ path: "reject", label: "Reject", body: "Rejected versions can never be activated.", danger: true });
  }
  if (m.status === "approved") actions.push({ path: "activate", label: "Activate", body: "The current active version will be archived. New scoring runs will use this version." });
  if (m.status === "archived" && m.approved_at) actions.push({ path: "activate", label: "Roll back to this version", body: "Re-activates this previously approved version and archives the current one. Recorded as a rollback." });
  const test = m.evaluation.test;

  return (
    <>
      <PageHeader title={m.name} description={<code>{m.version_id}</code>} actions={<Link className="btn" to="/models">Back</Link>} />
      {m.provenance === "synthetic_demo" ? <Banner kind="demo"><strong>Synthetic demo model.</strong> Trained and evaluated on generated data; its metrics say nothing about real detection performance.</Banner> : null}
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      <div className="grid grid-2">
        <section className="card" aria-labelledby="gov-h">
          <div className="card-header"><h2 id="gov-h">Governance</h2></div>
          <dl className="kv">
            <dt>Status</dt><dd><ModelStatusBadge status={m.status} /></dd>
            <dt>Provenance</dt><dd><ProvenanceBadge provenance={m.provenance} /></dd>
            <dt>Registered</dt><dd><Time iso={m.created_at} /></dd>
            <dt>Approved</dt><dd><Time iso={m.approved_at} /></dd>
            <dt>Activated</dt><dd><Time iso={m.activated_at} /></dd>
          </dl>
          {actions.length ? (
            <div className="row" style={{ marginTop: 14 }}>
              {admin ? actions.map((a) => <button key={a.label} className={`btn ${a.danger ? "danger" : ""}`} onClick={() => setAction(a)}>{a.label}</button>)
                : <span className="muted">Lifecycle changes require an administrator.</span>}
            </div>
          ) : null}
          <h3 style={{ marginTop: 18 }}>Lifecycle history</h3>
          <ul className="timeline" style={{ marginTop: 8 }}>
            {hist.data?.map((h, i) => (
              <li key={i}><div className="when"><Time iso={h.changed_at} /> · {h.changed_by_id ? users.get(h.changed_by_id) ?? `#${h.changed_by_id}` : "system"}</div>
                {h.from_status ? `${humanize(h.from_status)} → ` : ""}{humanize(h.to_status)}{h.reason ? <div className="secondary">“{h.reason}”</div> : null}</li>
            ))}
          </ul>
        </section>
        <section className="card" aria-labelledby="art-h">
          <div className="card-header"><h2 id="art-h">Artifact and lineage</h2></div>
          <dl className="kv">
            <dt>Model type</dt><dd>{m.model_type}</dd>
            <dt>Artifact SHA-256</dt><dd className="mono">{m.artifact_sha256}</dd>
            <dt>Format</dt><dd>{m.artifact_format} <span className="muted">(re-hashed before every load)</span></dd>
            <dt>Feature schema</dt><dd><code>{m.feature_schema_id}</code></dd>
            <dt>Preprocessing</dt><dd><code>{m.preprocessing_version}</code></dd>
            <dt>Decision</dt><dd>{m.threshold !== null ? `score(${m.positive_class}) ≥ ${m.threshold}` : `suspicious when class ≠ “${m.benign_label}”`}</dd>
            <dt>Training dataset</dt><dd>{m.training_dataset ?? "—"}</dd>
            <dt>Experiment</dt><dd>{m.evaluation.experiment_id ?? "—"} <span className="muted">{m.source_run}</span></dd>
            <dt>Split</dt><dd>{m.evaluation.split_method ?? "—"}</dd>
            <dt>Software</dt><dd className="mono">{Object.entries(m.software_versions).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(", ")}</dd>
          </dl>
        </section>
      </div>
      <section className="card" style={{ marginTop: 16 }} aria-labelledby="ev-h">
        <div className="card-header"><h2 id="ev-h">Recorded test-set evaluation</h2><span className="hint">from the experiment run that registered this version</span></div>
        {test ? <MetricsView m={test} /> : <p className="muted">No test-set evaluation recorded; this version cannot be approved.</p>}
        {m.evaluation.limitations?.length ? (
          <><h3 style={{ marginTop: 16 }}>Limitations recorded by the experiment</h3><ul>{m.evaluation.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></>
        ) : null}
      </section>
      {action ? (
        <ConfirmDialog title={`${action.label}: ${m.version_id}`} confirmLabel={action.label} danger={action.danger}
          reasonLabel="Reason (recorded in the audit log)" reasonRequired onCancel={() => setAction(null)}
          onConfirm={async (reason) => {
            await api.post(`/models/${m.id}/${action.path}`, { reason });
            setAction(null); setMsg(`${action.label} recorded.`); model.reload(); hist.reload();
          }}>{action.body}</ConfirmDialog>
      ) : null}
    </>
  );
}
