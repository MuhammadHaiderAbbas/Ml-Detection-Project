import { Fragment, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Can, ReadOnlyNote } from "../components/Can";
import { api } from "../api/client";
import type { AlertDetail, AlertStatus, Explanation, Incident, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { AlertStatusBadge, ModelStatusBadge, SeverityBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { ExplanationChart } from "../components/ExplanationChart";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { formatScore, humanize } from "../lib/format";
import { AlertsTable, useUserMap } from "./Alerts";

const NEXT: Record<AlertStatus, { to: AlertStatus; label: string; note: boolean }[]> = {
  new: [{ to: "investigating", label: "Start investigating", note: false }, { to: "false_positive", label: "Mark false positive", note: true }],
  investigating: [{ to: "resolved", label: "Resolve", note: true }, { to: "false_positive", label: "Mark false positive", note: true }],
  resolved: [{ to: "investigating", label: "Re-open", note: true }],
  false_positive: [{ to: "investigating", label: "Re-open", note: true }],
};

export function AlertDetailPage() {
  const { id } = useParams();
  const { user } = useAuth();
  const users = useUserMap();
  const { data, error, loading, reload } = useApi(() => api.get<AlertDetail>(`/alerts/${id}`), [id]);
  const openIncidents = useApi(() => api.get<Page<Incident>>("/incidents", { status: ["open", "investigating"], limit: 100 }), []);
  const [pending, setPending] = useState<{ to: AlertStatus; label: string; note: boolean } | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string>();
  const [err, setErr] = useState<string>();

  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const { alert: a, event: e, prediction: p, model: m } = data;

  const run = async (fn: () => Promise<unknown>, done: string) => {
    setErr(undefined);
    try { await fn(); setMsg(done); reload(); } catch (x) { setErr((x as Error).message); }
  };

  return (
    <>
      <PageHeader title={`Alert #${a.id}`} description={<>Investigation view for one model prediction. {data.interpretation}</>}
        actions={<Link className="btn" to="/alerts">Back to alerts</Link>} />
      {m.provenance === "synthetic_demo" ? <Banner kind="demo"><strong>Synthetic demo model.</strong> This alert was produced by a model trained on generated data.</Banner> : null}
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      {err ? <Banner kind="error">{err}</Banner> : null}

      <div className={loading ? "refetching grid grid-2" : "grid grid-2"}>
        <section className="card" aria-labelledby="triage-h">
          <div className="card-header"><h2 id="triage-h">Triage</h2></div>
          <dl className="kv">
            <dt>Status</dt><dd><AlertStatusBadge status={a.status} /></dd>
            <dt>Severity</dt><dd><SeverityBadge severity={a.severity} /> <span className="muted">rule <code>{a.severity_rule}</code></span></dd>
            <dt>Assignee</dt><dd>{data.assignee ?? <span className="muted">Unassigned</span>}</dd>
            <dt>Incident</dt><dd>{data.incident_id ? <Link to={`/incidents/${data.incident_id}`}>#{data.incident_id}</Link> : (
              <span className="row">
                <span className="muted">Not linked</span>
                <Can perm="incidents.write"><select aria-label="Link to an open incident" value="" onChange={(ev) => void run(() => api.post(`/incidents/${ev.target.value}/alerts`, { alert_ids: [a.id] }), "Alert linked to the incident.")}>
                  <option value="" disabled>Link to incident…</option>
                  {openIncidents.data?.items.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.title}</option>)}
                </select>
                <Link className="btn small" to={`/incidents?create=1&alerts=${a.id}`}>New incident</Link></Can>
              </span>)}</dd>
            <dt>Created</dt><dd><Time iso={a.created_at} /></dd>
          </dl>
          <Can perm="alerts.write" fallback={<ReadOnlyNote what="change, assign or annotate alerts" />}><div className="row" style={{ marginTop: 14 }}>
            {NEXT[a.status].map((t) => <button key={t.to} className="btn" onClick={() => setPending(t)}>{t.label}</button>)}
            <label className="field" style={{ minWidth: 180 }}>
              <span className="sr-only">Assign to</span>
              <select aria-label="Assign to" value={a.assignee_id ?? ""}
                onChange={(ev) => void run(() => api.post(`/alerts/${a.id}/assign`, { assignee_id: ev.target.value ? Number(ev.target.value) : null }), "Assignment updated.")}>
                <option value="">Unassigned</option>
                {[...users.entries()].map(([uid, name]) => <option key={uid} value={uid}>{name}{uid === user?.id ? " (me)" : ""}</option>)}
              </select>
            </label>
          </div></Can>
        </section>

        <section className="card" aria-labelledby="pred-h">
          <div className="card-header"><h2 id="pred-h">Model prediction</h2><span className="hint">automated output</span></div>
          <dl className="kv">
            <dt>Predicted class</dt><dd><strong>{p.predicted_class}</strong></dd>
            <dt>Score</dt><dd>{formatScore(p.score)} <span className="muted">({p.score_kind ? humanize(p.score_kind) : "no score"})</span></dd>
            <dt>Decision rule</dt><dd><code>{p.decision_rule}</code></dd>
            <dt>Model version</dt><dd><Link to={`/models/${m.id}`}><code>{m.version_id}</code></Link> <ModelStatusBadge status={m.status} /></dd>
            <dt>Preprocessing</dt><dd><code>{p.preprocessing_version}</code></dd>
            <dt>Inferred</dt><dd><Time iso={p.inferred_at} /></dd>
            <dt>Explanation</dt><dd><a href="#explain-h">Feature contributions</a> <span className="muted">(below)</span></dd>
          </dl>
        </section>
      </div>

      <ExplanationCard alertId={a.id} />

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <section className="card" aria-labelledby="ev-h">
          <div className="card-header"><h2 id="ev-h">Event</h2><Link className="right" to={`/data-sources/${e.import_id}`}>Import #{e.import_id}</Link></div>
          <dl className="kv">
            <dt>Event key</dt><dd className="mono">{e.event_key ?? `#${e.id}`}</dd>
            <dt>Occurred</dt><dd><Time iso={e.occurred_at} /></dd>
            <dt>Source</dt><dd className="mono">{e.source ?? "—"}</dd>
            <dt>Destination</dt><dd className="mono">{e.destination ?? "—"}</dd>
            {Object.entries(e.context).filter(([k]) => !["Src IP", "Dst IP"].includes(k)).map(([k, v]) => <Fragment key={k}><dt>{k}</dt><dd className="mono">{v ?? "—"}</dd></Fragment>)}
            <dt>Row in file</dt><dd className="num">{e.row_number}</dd>
            <dt>Dataset label</dt><dd>{e.dataset_label ?? "—"} <span className="muted">(supplied with the imported file; not an analyst decision)</span></dd>
          </dl>
        </section>
        <section className="card" aria-labelledby="feat-h">
          <div className="card-header"><h2 id="feat-h">Input features</h2><span className="hint">values the model received, in schema order</span></div>
          <div className="table-wrap" style={{ maxHeight: 320, overflowY: "auto" }}>
            <table className="data features-table">
              <thead><tr><th>Feature</th><th className="num">Value</th></tr></thead>
              <tbody>{Object.entries(e.features).map(([k, v]) => <tr key={k}><td>{k}</td><td className="num">{v ?? "—"}</td></tr>)}</tbody>
            </table>
          </div>
        </section>
      </div>

      <div className="grid grid-2" style={{ marginTop: 16 }}>
        <section className="card" aria-labelledby="notes-h">
          <div className="card-header"><h2 id="notes-h">Analyst notes</h2></div>
          {data.notes.length ? (
            <ul className="timeline">{data.notes.map((n) => <li key={n.id}><div className="when"><Time iso={n.created_at} /> · {n.author}</div>{n.body}</li>)}</ul>
          ) : <p className="muted">No notes yet.</p>}
          <Can perm="alerts.write"><form onSubmit={(ev) => { ev.preventDefault(); if (note.trim()) void run(() => api.post(`/alerts/${a.id}/notes`, { body: note }), "Note added.").then(() => setNote("")); }}>
            <label className="field">Add a note<textarea value={note} onChange={(ev) => setNote(ev.target.value)} maxLength={10000} /></label>
            <button className="btn" type="submit" disabled={!note.trim()} style={{ marginTop: 8 }}>Add note</button>
          </form></Can>
        </section>
        <section className="card" aria-labelledby="hist-h">
          <div className="card-header"><h2 id="hist-h">Status history</h2></div>
          <ul className="timeline">
            {data.history.map((h, i) => (
              <li key={i}><div className="when"><Time iso={h.changed_at} /> · {h.changed_by}</div>
                {h.from_status ? `${humanize(h.from_status)} → ` : ""}{humanize(h.to_status)}{h.note ? <div className="secondary">“{h.note}”</div> : null}</li>
            ))}
          </ul>
        </section>
      </div>

      {data.related_alerts.length ? (
        <section className="card" style={{ marginTop: 16 }} aria-labelledby="rel-h">
          <div className="card-header"><h2 id="rel-h">Related alerts</h2><span className="hint">same import, predicted class, source and destination</span></div>
          <AlertsTable alerts={data.related_alerts} compact />
        </section>
      ) : null}

      {pending ? (
        <ConfirmDialog title={pending.label} confirmLabel={pending.label}
          reasonLabel={pending.note ? "Note explaining the decision" : "Note (optional)"} reasonRequired={pending.note}
          onCancel={() => setPending(null)}
          onConfirm={async (reason) => {
            await api.post(`/alerts/${a.id}/status`, { status: pending.to, note: reason || null });
            setPending(null); setMsg(`Alert moved to ${humanize(pending.to)}.`); reload();
          }}>
          This is recorded in the alert history as your decision.
        </ConfirmDialog>
      ) : null}
    </>
  );
}

function ExplanationCard({ alertId }: { alertId: number }) {
  const { data: x, error, loading, reload } = useApi(() => api.get<Explanation>(`/alerts/${alertId}/explanation`), [alertId]);
  return (
    <section className="card" style={{ marginTop: 16 }} aria-labelledby="explain-h">
      <div className="card-header"><h2 id="explain-h">Why the model gave this score</h2><span className="hint">SHAP feature contributions · automated output</span></div>
      {error ? <ErrorState error={error} onRetry={reload} /> : loading && !x ? <Loading label="Computing the explanation from the model…" /> : !x ? null : !x.available ? (
        <p className="muted">{x.reason}</p>
      ) : (
        <>
          <ExplanationChart x={x} />
          <details style={{ marginTop: 12 }}>
            <summary>Method, verification and limitations</summary>
            <dl className="kv" style={{ marginTop: 8 }}>
              <dt>Method</dt><dd>{x.method} <span className="muted">({x.library})</span></dd>
              <dt>Verified</dt><dd>Re-scored with the same artifact (<code>{x.artifact_sha256?.slice(0, 12)}</code>) and preprocessing (<code>{x.preprocessing_version}</code>), which reproduced the stored prediction. Contributions add up to the model output within {x.additivity_error !== null ? x.additivity_error.toExponential(1) : "—"}.</dd>
              <dt>Computed</dt><dd><Time iso={x.computed_at} /></dd>
            </dl>
            <ul className="plain">{x.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
          </details>
        </>
      )}
    </section>
  );
}
