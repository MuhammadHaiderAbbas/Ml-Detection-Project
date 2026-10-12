import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { Can } from "../components/Can";
import type { DriftAnalysis, DriftEvent, ImportRecord, ModelVersion, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { DriftSeverityBadge, PlainBadge, VerdictBadge } from "../components/Badges";
import { PageHeader } from "../components/PageHeader";
import { Banner, Empty, ErrorState, Loading, Time } from "../components/States";
import { formatNumber, humanize } from "../lib/format";

const TYPES = ["feature", "prediction", "performance", "concept"] as const;
const TYPE_HELP: Record<string, string> = {
  feature: "Input feature distributions changed versus the reference.",
  prediction: "The model's output distribution changed.",
  performance: "Error rate rose, measured with labels supplied in the data.",
  concept: "Performance dropped without feature drift: the input-label relationship may have changed (suspected, needs labels).",
};

function NewAnalysis({ onCancel }: { onCancel: () => void }) {
  const navigate = useNavigate();
  const imports = useApi(() => api.get<Page<ImportRecord>>("/imports", { status: "completed", limit: 200 }), []);
  const models = useApi(() => api.get<ModelVersion[]>("/models"), []);
  const [f, setF] = useState({ name: "", ref: "", cur: "", refSince: "", refUntil: "", curSince: "", curUntil: "", model: "", mode: "events", size: "500", bucket: "day" });
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });
  const iso = (v: string) => (v ? new Date(v).toISOString() : null);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setError(undefined);
    if (!f.name.trim() || !f.ref || !f.cur) { setError("Give the analysis a name and choose reference and current data."); return; }
    setBusy(true);
    try {
      const a = await api.post<DriftAnalysis>("/drift/analyses", {
        name: f.name.trim(), model_version_id: f.model ? Number(f.model) : null, use_active_model: f.model === "",
        reference: { import_id: Number(f.ref), since: iso(f.refSince), until: iso(f.refUntil) },
        current: { import_id: Number(f.cur), since: iso(f.curSince), until: iso(f.curUntil) },
        window: f.mode === "events" ? { mode: "events", size: Number(f.size) } : { mode: "time", bucket: f.bucket },
      });
      navigate(`/drift/analyses/${a.id}`);
    } catch (x) { setError((x as Error).message); setBusy(false); }
  };
  const opts = imports.data?.items.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.dataset_name}@{i.dataset_version}</option>);
  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="na-h" noValidate>
      <h2 id="na-h">New drift analysis</h2>
      <p className="secondary" style={{ margin: 0 }}>Compare current data with a reference sample (for example the data the model was validated on). Times are in your local zone.</p>
      <div className="grid grid-3">
        <label className="field">Name<input value={f.name} onChange={set("name")} maxLength={200} /></label>
        <label className="field">Model (for prediction drift and performance)
          <select value={f.model} onChange={set("model")}><option value="">Active model</option>{models.data?.map((m) => <option key={m.id} value={m.id}>{m.version_id} ({m.status})</option>)}</select>
        </label>
        <label className="field">Windows over current data
          <select value={f.mode} onChange={set("mode")}><option value="events">Fixed number of events</option><option value="time">Calendar time</option></select>
        </label>
        <label className="field">Reference import<select value={f.ref} onChange={set("ref")}><option value="">Choose…</option>{opts}</select></label>
        <label className="field">Reference from (optional)<input type="datetime-local" value={f.refSince} onChange={set("refSince")} /></label>
        <label className="field">Reference until (optional)<input type="datetime-local" value={f.refUntil} onChange={set("refUntil")} /></label>
        <label className="field">Current import<select value={f.cur} onChange={set("cur")}><option value="">Choose…</option>{opts}</select></label>
        <label className="field">Current from (optional)<input type="datetime-local" value={f.curSince} onChange={set("curSince")} /></label>
        <label className="field">Current until (optional)<input type="datetime-local" value={f.curUntil} onChange={set("curUntil")} /></label>
        {f.mode === "events"
          ? <label className="field">Events per window<input type="number" min={50} value={f.size} onChange={set("size")} /></label>
          : <label className="field">Window length<select value={f.bucket} onChange={set("bucket")}><option value="hour">Hour</option><option value="day">Day</option><option value="week">Week</option></select></label>}
      </div>
      {error ? <Banner kind="error">{error}</Banner> : null}
      <div className="row"><button className="btn primary" disabled={busy}>Run analysis</button><button type="button" className="btn" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}

export function EventsTable({ events }: { events: DriftEvent[] }) {
  const navigate = useNavigate();
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th>Event</th><th>Type</th><th>Signal</th><th>Severity</th><th>Status</th><th>Onset (event time)</th><th>Analysis</th></tr></thead>
        <tbody>{events.map((e) => (
          <tr key={e.id} className="clickable" onClick={() => navigate(`/drift/events/${e.id}`)}>
            <td><Link to={`/drift/events/${e.id}`} onClick={(x) => x.stopPropagation()}>#{e.id}</Link></td><td>{humanize(e.drift_type)}</td>
            <td className="mono">{e.signal}</td><td><DriftSeverityBadge severity={e.severity} /></td><td><PlainBadge>{humanize(e.status)}</PlainBadge></td>
            <td><Time compact iso={e.detected_at} /></td><td><Link to={`/drift/analyses/${e.analysis_id}`} onClick={(x) => x.stopPropagation()}>#{e.analysis_id}</Link></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export function DriftPage() {
  const [creating, setCreating] = useState(false);
  const analyses = useApi(() => api.get<Page<DriftAnalysis>>("/drift/analyses", { limit: 50 }), [], { pollMs: 5000 });
  const open = useApi(() => api.get<Page<DriftEvent>>("/drift/events", { status: ["new", "acknowledged", "investigating"], limit: 50 }), [], { pollMs: 15000 });
  const latest = analyses.data?.items.find((a) => a.status === "completed");
  return (
    <>
      <PageHeader title="Drift Monitor"
        description="Feature drift, prediction drift, performance degradation and suspected concept drift are tracked separately. A drift signal is a prompt for review, not evidence of an attack, and never retrains or promotes a model."
        actions={!creating ? <Can perm="drift.write"><button className="btn primary" onClick={() => setCreating(true)}>New analysis</button></Can> : null} />
      {creating ? <div style={{ marginBottom: 16 }}><NewAnalysis onCancel={() => setCreating(false)} /></div> : null}
      {latest?.summary ? (
        <section className="card" aria-labelledby="latest-h">
          <div className="card-header"><h2 id="latest-h">Latest analysis: <Link to={`/drift/analyses/${latest.id}`}>{latest.name}</Link></h2><span className="hint">completed <Time iso={latest.completed_at} /></span></div>
          <div className="grid grid-kpi">
            {TYPES.map((t) => (
              <Link key={t} className="kpi" to={`/drift/analyses/${latest.id}`} title={TYPE_HELP[t]}>
                <div className="label">{humanize(t)} drift</div>
                <div className="value text" style={{ marginTop: 6 }}><VerdictBadge status={latest.summary![t].status} /></div>
                <div className="sub">{latest.summary![t].severity ? <DriftSeverityBadge severity={latest.summary![t].severity!} /> : TYPE_HELP[t]}</div>
              </Link>
            ))}
          </div>
        </section>
      ) : null}
      <section className="card" aria-labelledby="ev-h">
        <div className="card-header"><h2 id="ev-h">Open drift events</h2><span className="hint">new, acknowledged or under investigation</span></div>
        {open.error ? <ErrorState error={open.error} onRetry={open.reload} /> : open.data ? (open.data.items.length ? <EventsTable events={open.data.items} />
          : <Empty title="No open drift events" />) : <Loading />}
      </section>
      <section className="card" aria-labelledby="an-h">
        <div className="card-header"><h2 id="an-h">Analyses</h2></div>
        {analyses.error ? <ErrorState error={analyses.error} onRetry={analyses.reload} /> : analyses.data ? (analyses.data.items.length ? (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Analysis</th><th>Reference</th><th>Current</th><th>Status</th><th className="num">Events compared</th><th>Feature</th><th>Prediction</th><th>Performance</th><th>Concept</th><th>Created</th></tr></thead>
              <tbody>{analyses.data.items.map((a) => (
                <tr key={a.id}>
                  <td><Link to={`/drift/analyses/${a.id}`}>#{a.id} {a.name}</Link></td>
                  <td>#{a.reference_spec.import_id}</td><td>#{a.current_spec.import_id}</td>
                  <td>{humanize(a.status)}{a.error ? <div className="field-error">{a.error}</div> : null}</td>
                  <td className="num">{a.n_current !== null ? `${formatNumber(a.n_reference)} / ${formatNumber(a.n_current)}` : "—"}</td>
                  {TYPES.map((t) => <td key={t}>{a.summary ? <VerdictBadge status={a.summary[t].status} /> : "—"}</td>)}
                  <td><Time compact iso={a.created_at} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="No drift analyses yet">Choose “New analysis” to compare current data with a reference sample, or run <code>adaptive-ids demo</code>.</Empty>) : <Loading />}
      </section>
    </>
  );
}
