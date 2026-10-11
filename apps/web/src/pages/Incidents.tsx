import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { Incident, IncidentDetail, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { DispositionBadge, PlainBadge } from "../components/Badges";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { Empty, ErrorState, Loading, Time } from "../components/States";
import { useUrlFilters } from "../lib/filters";
import { humanize } from "../lib/format";
import { useUserMap } from "./Alerts";

function CreateIncident({ alertIds, onCancel }: { alertIds: number[]; onCancel: () => void }) {
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!title.trim()) { setError("A title is required."); return; }
    setBusy(true);
    try {
      const d = await api.post<IncidentDetail>("/incidents", { title: title.trim(), summary: summary.trim() || null, alert_ids: alertIds });
      navigate(`/incidents/${d.incident.id}`);
    } catch (x) { setError((x as Error).message); setBusy(false); }
  };
  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="new-inc">
      <h2 id="new-inc">New incident</h2>
      <p className="secondary" style={{ margin: 0 }}>{alertIds.length ? `Linking ${alertIds.length} alert(s): ${alertIds.map((i) => `#${i}`).join(", ")}` : "No alerts selected; you can link alerts later."}</p>
      <label className="field">Title<input value={title} onChange={(e) => setTitle(e.target.value)} maxLength={300} required /></label>
      <label className="field">Summary (optional)<textarea value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={20000} /></label>
      {error ? <p className="field-error" role="alert">{error}</p> : null}
      <div className="row"><button className="btn primary" disabled={busy}>Create incident</button><button type="button" className="btn" onClick={onCancel}>Cancel</button></div>
    </form>
  );
}

export function IncidentsPage() {
  const f = useUrlFilters();
  const users = useUserMap();
  const limit = 50;
  const offset = Number(f.get("offset") || 0);
  const creating = f.get("create") === "1";
  const alertIds = (f.get("alerts") || "").split(",").filter(Boolean).map(Number);
  const { data, error, loading, reload } = useApi(
    () => api.get<Page<Incident>>("/incidents", { status: f.getAll("status"), disposition: f.get("disposition"), limit, offset }),
    [f.params.toString()]);
  return (
    <>
      <PageHeader title="Incidents" description="Groups of related alerts with evidence and the analyst's decision. Only an incident's disposition records a confirmed attack."
        actions={!creating ? <button className="btn primary" onClick={() => f.set({ create: "1" })}>New incident</button> : null} />
      {creating ? <div style={{ marginBottom: 16 }}><CreateIncident alertIds={alertIds} onCancel={() => f.set({ create: null, alerts: null })} /></div> : null}
      <div className="card">
        <div className="filters">
          <label className="field">Status
            <select value={f.get("status")} onChange={(e) => f.set({ status: e.target.value })}>
              <option value="">Any</option><option value="open">Open</option><option value="investigating">Investigating</option><option value="closed">Closed</option>
            </select>
          </label>
          <label className="field">Disposition
            <select value={f.get("disposition")} onChange={(e) => f.set({ disposition: e.target.value })}>
              <option value="">Any</option>
              {["undetermined", "confirmed_attack", "benign", "false_positive", "inconclusive"].map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
            </select>
          </label>
        </div>
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        {data ? (data.items.length ? (
          <div className={loading ? "refetching" : ""}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Incident</th><th>Title</th><th>Status</th><th>Disposition</th><th>Owner</th><th>Updated</th></tr></thead>
                <tbody>
                  {data.items.map((i) => (
                    <tr key={i.id}>
                      <td><Link to={`/incidents/${i.id}`}>#{i.id}</Link></td><td>{i.title}</td>
                      <td><PlainBadge>{humanize(i.status)}</PlainBadge></td><td><DispositionBadge disposition={i.disposition} /></td>
                      <td>{i.owner_id ? users.get(i.owner_id) ?? `#${i.owner_id}` : "—"}</td><td><Time compact iso={i.updated_at} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination total={data.total} limit={limit} offset={offset} onChange={(o) => f.set({ offset: String(o) })} />
          </div>
        ) : <Empty title="No incidents">Select alerts on the <Link to="/alerts">Alerts</Link> page and choose “Create incident”.</Empty>) : <Loading />}
      </div>
    </>
  );
}
