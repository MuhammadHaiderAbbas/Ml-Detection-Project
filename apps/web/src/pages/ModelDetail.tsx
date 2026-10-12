import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { Evaluation, ImportRecord, ModelDetail, ModelHistory, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { EvaluationVerdictBadge, ModelStatusBadge, ProvenanceBadge, RestoreBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { MetricsView } from "../components/MetricsView";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { humanize } from "../lib/format";
import { useUserMap } from "./Alerts";

type Action = { path: string; label: string; body: string; danger?: boolean };
const MIN_OVERRIDE = 20;

export function ModelDetailPage() {
  const { id } = useParams();
  const { can } = useAuth();
  const users = useUserMap();
  const model = useApi(() => api.get<ModelDetail>(`/models/${id}`), [id]);
  const hist = useApi(() => api.get<ModelHistory[]>(`/models/${id}/history`), [id]);
  const evals = useApi(() => api.get<Evaluation[]>(`/models/${id}/evaluations`), [id]);
  const active = useApi(() => api.get<ModelDetail | null>("/models/active"), [id]);
  const navigate = useNavigate();
  const [action, setAction] = useState<Action | null>(null);
  const [override, setOverride] = useState(false);
  const [msg, setMsg] = useState<string>();
  const [err, setErr] = useState<string>();
  const [checking, setChecking] = useState(false);
  if (model.error) return <ErrorState error={model.error} onRetry={model.reload} />;
  const m = model.data;
  if (!m) return <Loading />;
  const admin = can("models.manage");
  const candidate = ["candidate", "evaluating"].includes(m.status);
  const latest = evals.data?.find((e) => e.status === "completed");
  const stale = latest ? (latest.baseline_model_version_id ?? null) !== (active.data?.id ?? null) : false;
  const actions: Action[] = [];
  if (candidate) {
    actions.push({ path: "approve", label: "Approve", body: "" });
    actions.push({ path: "reject", label: "Reject", body: "Rejected versions can never be activated.", danger: true });
  }
  const restoreNote = " The artifact is re-hashed, re-loaded and replayed on its recorded sample first; activation is refused if that fails.";
  if (m.status === "approved") actions.push({ path: "activate", label: "Activate", body: "The current active version will be archived. New scoring runs will use this version." + restoreNote });
  if (m.status === "archived" && m.approved_at) actions.push({ path: "activate", label: "Roll back to this version", body: "Re-activates this previously approved version and archives the current one. Recorded as a rollback." + restoreNote });
  const test = m.evaluation.test;
  const verify = async () => {
    setChecking(true); setErr(undefined);
    try { const r = await api.post<ModelDetail>(`/models/${m.id}/verify-restore`, {}); setMsg(r.restore_check?.ok ? "Restorability check passed." : "Restorability check FAILED; see details."); model.reload(); }
    catch (x) { setErr((x as Error).message); } finally { setChecking(false); }
  };
  const approveBody = !latest ? <p>This candidate has no completed evaluation. Evaluate it against the active model first; the server refuses approval without one.</p> : (
    <>
      <p>Approval relies on <Link to={`/evaluations/${latest.id}`}>evaluation #{latest.id}</Link> (protocol v{latest.protocol_version}): <EvaluationVerdictBadge verdict={latest.verdict} />.
        It does not activate the model.</p>
      {stale ? <p className="field-error">The active model changed after this evaluation. The server will ask for a new evaluation.</p> : null}
      {latest.verdict === "fail" ? (
        <label className="check-inline">
          <input type="checkbox" checked={override} onChange={(e) => setOverride(e.target.checked)} />
          <span>Override the failed performance gates. I have reviewed the trade-off; my justification below (at least {MIN_OVERRIDE} characters) is recorded and audited as an override.</span>
        </label>
      ) : null}
      {latest.verdict === "insufficient_evidence" ? <p className="field-error">Insufficient evidence cannot be overridden. Evaluate on a larger labelled import.</p> : null}
    </>
  );

  return (
    <>
      <PageHeader title={m.name} description={<code>{m.version_id}</code>} actions={<Link className="btn" to="/models">Back</Link>} />
      {m.provenance === "synthetic_demo" ? <Banner kind="demo"><strong>Synthetic demo model.</strong> Trained and evaluated on generated data; its metrics say nothing about real detection performance.</Banner> : null}
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      {err ? <Banner kind="error">{err}</Banner> : null}
      <div className="grid grid-2">
        <section className="card" aria-labelledby="gov-h">
          <div className="card-header"><h2 id="gov-h">Governance</h2></div>
          <dl className="kv">
            <dt>Status</dt><dd><ModelStatusBadge status={m.status} /></dd>
            <dt>Provenance</dt><dd><ProvenanceBadge provenance={m.provenance} /></dd>
            <dt>Registered</dt><dd><Time iso={m.created_at} /></dd>
            <dt>Approved</dt><dd><Time iso={m.approved_at} /></dd>
            <dt>Activated</dt><dd><Time iso={m.activated_at} /></dd>
            <dt>Approval basis</dt><dd>{m.approval_evaluation_id ? <><Link to={`/evaluations/${m.approval_evaluation_id}`}>Evaluation #{m.approval_evaluation_id}</Link>{m.approval_override ? <> · <strong>override of failed gates</strong></> : null}</> : m.approved_at ? "approved before evaluations were required" : "—"}</dd>
            <dt>Restorability</dt><dd>
              <RestoreBadge ok={m.restore_check ? m.restore_check.ok : null} partial={m.restore_check?.partial} />
              {m.restore_check ? <span className="muted"> checked <Time iso={m.restore_check.checked_at} /></span> : null}
              {admin ? <button className="btn small" style={{ marginLeft: 8 }} disabled={checking} onClick={() => void verify()}>{checking ? "Checking…" : "Verify now"}</button> : null}
              {m.restore_check ? (
                <details style={{ marginTop: 6 }}><summary>Checks</summary>
                  <ul className="plain">{m.restore_check.checks.map((c) => <li key={c.id}>{c.passed ? "✓" : c.passed === false ? "✗" : "–"} <code>{c.id}</code>: {c.detail}</li>)}</ul>
                </details>) : null}
            </dd>
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
      <EvaluationsCard model={m} evals={evals.data} admin={admin} candidate={candidate} activeVersion={active.data?.version_id ?? null}
        onStarted={(eid) => navigate(`/evaluations/${eid}`)} onError={setErr} />
      <section className="card" style={{ marginTop: 16 }} aria-labelledby="ev-h">
        <div className="card-header"><h2 id="ev-h">Recorded test-set evaluation</h2><span className="hint">from the experiment run that registered this version</span></div>
        {test ? <MetricsView m={test} /> : <p className="muted">No test-set evaluation recorded; this version cannot be approved.</p>}
        {m.evaluation.limitations?.length ? (
          <><h3 style={{ marginTop: 16 }}>Limitations recorded by the experiment</h3><ul>{m.evaluation.limitations.map((l, i) => <li key={i}>{l}</li>)}</ul></>
        ) : null}
      </section>
      {action ? (
        <ConfirmDialog title={`${action.label}: ${m.version_id}`} confirmLabel={action.path === "approve" && override ? "Approve with override" : action.label} danger={action.danger}
          reasonLabel={action.path === "approve" && override ? "Justification for overriding failed gates (audited)" : "Reason (recorded in the audit log)"} reasonRequired
          onCancel={() => { setAction(null); setOverride(false); }}
          onConfirm={async (reason) => {
            if (action.path === "approve" && override && reason.length < MIN_OVERRIDE) throw new Error(`An override needs a justification of at least ${MIN_OVERRIDE} characters.`);
            const body = action.path === "approve" ? { reason, evaluation_id: latest?.id, override } : { reason };
            await api.post(`/models/${m.id}/${action.path}`, body);
            setAction(null); setOverride(false); setMsg(`${action.label} recorded.`); model.reload(); hist.reload();
          }}>{action.path === "approve" ? approveBody : action.body}</ConfirmDialog>
      ) : null}
    </>
  );
}

function EvaluationsCard({ model, evals, admin, candidate, activeVersion, onStarted, onError }: {
  model: ModelDetail; evals: Evaluation[] | undefined; admin: boolean; candidate: boolean; activeVersion: string | null;
  onStarted: (id: number) => void; onError: (m: string) => void;
}) {
  const imports = useApi(() => (admin && candidate ? api.get<Page<ImportRecord>>("/imports", { status: "completed", limit: 200 }) : Promise.resolve(undefined)), [admin, candidate]);
  const usable = (imports.data?.items ?? []).filter((i) => i.schema_id === model.feature_schema_id);
  const [importId, setImportId] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const start = async () => {
    setBusy(true);
    try { const ev = await api.post<Evaluation>(`/models/${model.id}/evaluations`, { import_id: Number(importId) }); onStarted(ev.id); }
    catch (x) { onError((x as Error).message); setBusy(false); }
  };
  return (
    <section className="card" style={{ marginTop: 16 }} aria-labelledby="ce-h">
      <div className="card-header"><h2 id="ce-h">Candidate evaluations</h2>
        <span className="hint">scored side by side with the active model under the <Link to="/models#protocol">governance protocol</Link></span></div>
      {admin && candidate ? (
        <div className="row" style={{ marginBottom: 14, alignItems: "flex-end" }}>
          <label className="field" style={{ minWidth: 260, flex: "1 1 260px" }}>Labelled import to evaluate on
            <select value={importId} onChange={(e) => setImportId(e.target.value)}>
              <option value="">Choose an import…</option>
              {usable.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.dataset_name}@{i.dataset_version} ({i.accepted_rows} rows)</option>)}
            </select>
          </label>
          <button className="btn primary" disabled={!importId || busy} onClick={() => void start()}>
            {busy ? "Starting…" : activeVersion ? "Evaluate against the active model" : "Evaluate (no active baseline)"}</button>
          <span className="muted" style={{ flexBasis: "100%", fontSize: 12.5 }}>
            Imports of the file this model{activeVersion ? " or the active model" : ""} was trained on are refused. Baseline: {activeVersion ? <code>{activeVersion}</code> : "none"}.
          </span>
        </div>
      ) : null}
      {evals === undefined ? <Loading /> : evals.length ? (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Evaluation</th><th>Verdict</th><th>Baseline</th><th>Data</th><th className="num">Labelled events</th><th>Protocol</th><th>Completed</th></tr></thead>
            <tbody>{evals.map((e) => (
              <tr key={e.id}>
                <td><Link to={`/evaluations/${e.id}`}>#{e.id}</Link></td>
                <td><EvaluationVerdictBadge verdict={e.verdict} status={e.status} /></td>
                <td>{e.data.baseline ? <code>{e.data.baseline.version_id}</code> : <span className="muted">none</span>}</td>
                <td>{e.data.dataset}</td><td className="num">{e.data.labelled_events.toLocaleString()}</td>
                <td>v{e.protocol_version}</td><td><Time compact iso={e.completed_at} /></td>
              </tr>
            ))}</tbody>
          </table>
        </div>
      ) : <p className="muted" style={{ margin: 0 }}>{candidate ? "Not evaluated yet. A completed evaluation is required before this candidate can be approved." : "No candidate evaluations recorded for this version."}</p>}
    </section>
  );
}
