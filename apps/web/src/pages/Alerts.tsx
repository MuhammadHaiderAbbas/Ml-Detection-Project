import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, downloadFile } from "../api/client";
import { Can } from "../components/Can";
import type { Alert, AlertGroup, Page, User } from "../api/types";
import { useApi } from "../api/useApi";
import { AlertStatusBadge, SeverityBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { ImportSelect, ModelSelect } from "../components/Selectors";
import { Empty, ErrorState, Loading, Time } from "../components/States";
import { useUrlFilters } from "../lib/filters";
import { formatNumber, formatScore } from "../lib/format";

const STATUSES = [["new", "New"], ["investigating", "Investigating"], ["resolved", "Resolved"], ["false_positive", "False positive"]] as const;
const SEVERITIES = [["critical", "Critical"], ["high", "High"], ["medium", "Medium"], ["low", "Low"]] as const;

export function AlertsTable({ alerts, compact, users, selectable, selected, onToggle }: {
  alerts: Alert[]; compact?: boolean; users?: Map<number, string>;
  selectable?: boolean; selected?: Set<number>; onToggle?: (id: number) => void;
}) {
  const navigate = useNavigate();
  return (
    <div className="table-wrap">
      <table className="data">
        <thead>
          <tr>
            {selectable ? <th><span className="sr-only">Select</span></th> : null}
            <th>Alert</th><th>Status</th><th>Severity</th><th>Predicted class</th><th className="num">Score*</th>
            {!compact ? <><th>Assignee</th><th>Incident</th></> : null}<th>Created</th>
          </tr>
        </thead>
        <tbody>
          {alerts.map((a) => (
            <tr key={a.id} className="clickable" onClick={() => navigate(`/alerts/${a.id}`)}>
              {selectable ? (
                <td onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" aria-label={`Select alert ${a.id}`} checked={selected?.has(a.id) ?? false}
                    onChange={() => onToggle?.(a.id)} disabled={a.incident_id !== null} />
                </td>
              ) : null}
              <td><Link to={`/alerts/${a.id}`} onClick={(e) => e.stopPropagation()}>#{a.id}</Link></td>
              <td><AlertStatusBadge status={a.status} /></td>
              <td><SeverityBadge severity={a.severity} /></td>
              <td>{a.predicted_class}</td>
              <td className="num">{formatScore(a.score)}</td>
              {!compact ? (
                <>
                  <td>{a.assignee_id ? users?.get(a.assignee_id) ?? `#${a.assignee_id}` : <span className="muted">Unassigned</span>}</td>
                  <td>{a.incident_id ? <Link to={`/incidents/${a.incident_id}`} onClick={(e) => e.stopPropagation()}>#{a.incident_id}</Link> : <span className="muted">—</span>}</td>
                </>
              ) : null}
              <td><Time compact iso={a.created_at} /></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>*Uncalibrated model score. Alerts are model suspicions, not confirmed attacks.</p>
    </div>
  );
}

function MultiCheck({ legend, options, values, onChange }: { legend: string; options: readonly (readonly [string, string])[]; values: string[]; onChange: (v: string[]) => void }) {
  return (
    <fieldset className="field" style={{ border: 0, padding: 0, margin: 0 }}>
      <legend style={{ fontSize: 13, color: "var(--text-secondary)", marginBottom: 4 }}>{legend}</legend>
      <div className="row">
        {options.map(([v, l]) => (
          <label key={v} className="row" style={{ gap: 4 }}>
            <input type="checkbox" checked={values.includes(v)} style={{ minHeight: 0 }}
              onChange={(e) => onChange(e.target.checked ? [...values, v] : values.filter((x) => x !== v))} />{l}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function useUserMap() {
  const { data } = useApi(() => api.get<User[]>("/users"), []);
  return new Map((data ?? []).map((u) => [u.id, u.username]));
}

export function AlertsPage() {
  const f = useUrlFilters();
  const navigate = useNavigate();
  const users = useUserMap();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const status = f.getAll("status");
  const severity = f.getAll("severity");
  const view = f.get("view") || "list";
  const limit = 50;
  const offset = Number(f.get("offset") || 0);
  const query = {
    status, severity, import_id: f.get("import_id"), model_version_id: f.get("model_version_id"),
    predicted_class: f.get("predicted_class"), source: f.get("source"), destination: f.get("destination"),
    group_key: f.get("group_key"), assignee_id: f.get("assignee_id"),
  };
  const key = f.params.toString();
  const list = useApi(() => api.get<Page<Alert>>("/alerts", { ...query, limit, offset }), [key], { pollMs: 30000 });
  const groups = useApi(() => (view === "groups" ? api.get<Page<AlertGroup>>("/alerts/groups", { ...query, limit: 100 }) : Promise.resolve(undefined)), [key, view]);

  const toggle = (id: number) => setSelected((s) => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const clearAll = () => f.set({ status: null, severity: null, import_id: null, model_version_id: null, predicted_class: null, source: null, destination: null, group_key: null, assignee_id: null });
  const activeChips = (["source", "destination", "group_key", "predicted_class", "assignee_id"] as const).filter((k) => f.get(k));

  return (
    <>
      <PageHeader title="Alerts" description="Suspicious predictions awaiting or under analyst review. Severity is a triage priority from configured rules."
        actions={<>
          <Can perm="data.export"><button className="btn" onClick={() => void downloadFile("/alerts/export.csv", "alerts.csv", query)}><Icon name="download" size={16} />Export CSV</button></Can>
          <Can perm="incidents.write"><button className="btn primary" disabled={!selected.size}
            onClick={() => navigate(`/incidents?create=1&alerts=${[...selected].join(",")}`)}>Create incident ({selected.size})</button></Can>
        </>} />
      <div className="card">
        <div className="filters" role="group" aria-label="Alert filters">
          <MultiCheck legend="Status" options={STATUSES} values={status} onChange={(v) => f.set({ status: v })} />
          <MultiCheck legend="Severity" options={SEVERITIES} values={severity} onChange={(v) => f.set({ severity: v })} />
          <ImportSelect value={f.get("import_id")} onChange={(v) => f.set({ import_id: v })} />
          <ModelSelect value={f.get("model_version_id")} onChange={(v) => f.set({ model_version_id: v })} />
          <label className="field">Assignee
            <select value={f.get("assignee_id")} onChange={(e) => f.set({ assignee_id: e.target.value })}>
              <option value="">Anyone</option>
              {[...users.entries()].map(([id, name]) => <option key={id} value={id}>{name}</option>)}
            </select>
          </label>
          <div className="toggle-group" role="group" aria-label="View">
            <button aria-pressed={view === "list"} onClick={() => f.set({ view: null })}>List</button>
            <button aria-pressed={view === "groups"} onClick={() => f.set({ view: "groups" })}>Grouped</button>
          </div>
        </div>
        {activeChips.length || status.length || severity.length ? (
          <div className="row" style={{ marginBottom: 10 }}>
            {activeChips.map((k) => (
              <span className="badge" key={k}>{k.replace("_", " ")}: <span className="mono">{f.get(k)}</span>
                <button className="btn ghost small" aria-label={`Remove ${k} filter`} onClick={() => f.set({ [k]: null })}><Icon name="x" size={12} /></button>
              </span>
            ))}
            <button className="btn small" onClick={clearAll}>Clear filters</button>
          </div>
        ) : null}

        {view === "groups" ? (
          groups.data ? (groups.data.items.length ? (
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Predicted class</th><th>Source → destination</th><th className="num">Alerts</th><th className="num">Max score*</th><th>First seen</th><th>Last seen</th></tr></thead>
                <tbody>
                  {groups.data.items.map((g) => (
                    <tr key={g.group_key} className="clickable" onClick={() => f.set({ group_key: g.group_key, view: null })}>
                      <td>{g.predicted_class}</td><td className="mono">{g.source} → {g.destination}</td>
                      <td className="num">{formatNumber(g.alerts)}</td><td className="num">{formatScore(g.max_score)}</td>
                      <td><Time compact iso={g.first_seen} /></td><td><Time compact iso={g.last_seen} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 12 }}>Groups combine alerts from the same import with the same predicted class, source and destination. Select a group to see its alerts.</p>
            </div>
          ) : <Empty title="No alert groups" />) : groups.error ? <ErrorState error={groups.error} /> : <Loading />
        ) : (
          <>
            {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : null}
            {list.data ? (list.data.items.length ? (
              <div className={list.loading ? "refetching" : ""}>
                <AlertsTable alerts={list.data.items} users={users} selectable selected={selected} onToggle={toggle} />
                <Pagination total={list.data.total} limit={limit} offset={offset} onChange={(o) => f.set({ offset: String(o) })} />
              </div>
            ) : <Empty title="No alerts match these filters">Change or clear the filters above.</Empty>) : <Loading />}
          </>
        )}
      </div>
    </>
  );
}
