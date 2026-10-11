import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api/client";
import type { DriftEventDetail } from "../api/types";
import { useApi } from "../api/useApi";
import { DriftSeverityBadge, PlainBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { humanize } from "../lib/format";

const DETAIL_LABELS: Record<string, string> = {
  psi: "PSI", ks_d: "KS D", ks_p_adj: "KS p (Bonferroni)", ref_mean: "Reference mean", cur_mean: "Current mean",
  ref_median: "Reference median", cur_median: "Current median", chi2_p: "Chi-square p", js_distance: "Jensen-Shannon distance",
  suspicious_rate_ref: "Suspicious rate (reference)", suspicious_rate_cur: "Suspicious rate (current)", error_rate_change: "Error-rate change",
  mean_before: "Mean before", mean_after: "Mean after", position: "Position in stream", approx_change_start: "Approx. change start",
};

const NEXT: Record<string, { to: string; label: string; note: boolean }[]> = {
  new: [{ to: "acknowledged", label: "Acknowledge", note: false }, { to: "investigating", label: "Investigate", note: false }, { to: "closed", label: "Close", note: true }],
  acknowledged: [{ to: "investigating", label: "Investigate", note: false }, { to: "closed", label: "Close", note: true }],
  investigating: [{ to: "closed", label: "Close", note: true }],
  closed: [{ to: "investigating", label: "Re-open", note: true }],
};

export function DriftEventPage() {
  const { id } = useParams();
  const { data, error, reload } = useApi(() => api.get<DriftEventDetail>(`/drift/events/${id}`), [id]);
  const [pending, setPending] = useState<{ to: string; label: string; note: boolean } | null>(null);
  const [note, setNote] = useState("");
  const [msg, setMsg] = useState<string>();
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const e = data.event;
  return (
    <>
      <PageHeader title={`Drift event #${e.id}`} description={data.interpretation} actions={<Link className="btn" to={`/drift/analyses/${e.analysis_id}`}>Open analysis #{e.analysis_id}</Link>} />
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      <div className="grid grid-2">
        <section className="card" aria-labelledby="sig-h">
          <div className="card-header"><h2 id="sig-h">Signal</h2><span className="hint">automated detection</span></div>
          <dl className="kv">
            <dt>Type</dt><dd>{humanize(e.drift_type)} drift</dd>
            <dt>Signal</dt><dd className="mono">{e.signal}</dd>
            <dt>Severity</dt><dd><DriftSeverityBadge severity={e.severity} /></dd>
            <dt>Rule</dt><dd>{e.rule}</dd>
            <dt>Onset</dt><dd>{e.window_index !== null ? `window #${e.window_index}, ` : ""}<Time iso={e.detected_at} /></dd>
            <dt>Recorded</dt><dd><Time iso={e.created_at} /></dd>
            <dt>Details</dt><dd>
              <table className="data"><tbody>{Object.entries(e.details).filter(([, v]) => typeof v !== "object" || v === null).map(([k, v]) => (
                <tr key={k}><td>{DETAIL_LABELS[k] ?? humanize(k)}</td><td className="num">{typeof v === "number" ? (Math.abs(v) < 1e-4 && v !== 0 ? v.toExponential(2) : Number(v.toPrecision(4))) : String(v)}</td></tr>
              ))}</tbody></table>
            </dd>
          </dl>
        </section>
        <section className="card" aria-labelledby="rev-h">
          <div className="card-header"><h2 id="rev-h">Review</h2><span className="hint">analyst actions</span></div>
          <dl className="kv"><dt>Status</dt><dd><PlainBadge>{humanize(e.status)}</PlainBadge></dd></dl>
          <div className="row" style={{ marginTop: 12 }}>{NEXT[e.status].map((t) => <button key={t.to} className="btn" onClick={() => setPending(t)}>{t.label}</button>)}</div>
          <ul className="timeline" style={{ marginTop: 16 }}>
            {data.notes.map((n) => <li key={n.id}><div className="when"><Time iso={n.created_at} /> · {n.author} · {n.kind === "status" ? "status change" : "note"}</div><span style={{ whiteSpace: "pre-wrap" }}>{n.body}</span></li>)}
          </ul>
          <form onSubmit={(x) => { x.preventDefault(); if (note.trim()) void api.post(`/drift/events/${e.id}/notes`, { body: note }).then(() => { setNote(""); setMsg("Note added."); reload(); }); }}>
            <label className="field">Investigation note<textarea value={note} onChange={(x) => setNote(x.target.value)} maxLength={10000} /></label>
            <button className="btn" style={{ marginTop: 8 }} disabled={!note.trim()}>Add note</button>
          </form>
        </section>
      </div>
      {pending ? (
        <ConfirmDialog title={pending.label} confirmLabel={pending.label} reasonLabel={pending.note ? "Outcome of the review" : "Note (optional)"} reasonRequired={pending.note}
          onCancel={() => setPending(null)}
          onConfirm={async (reason) => { await api.post(`/drift/events/${e.id}/status`, { status: pending.to, note: reason || null }); setPending(null); setMsg(`Event ${humanize(pending.to).toLowerCase()}.`); reload(); }}>
          {pending.to === "closed" ? "Record what was found. Closing does not change any model; retraining or promotion goes through Model Management." : "Recorded in the event history."}
        </ConfirmDialog>
      ) : null}
    </>
  );
}
