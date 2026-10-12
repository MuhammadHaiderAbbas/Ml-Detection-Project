import { api } from "../api/client";
import type { AuditEntry, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { Banner, Empty, ErrorState, Loading, Time } from "../components/States";
import { useUrlFilters } from "../lib/filters";

export function AuditPage() {
  const { can } = useAuth();
  const f = useUrlFilters();
  const limit = 100;
  const offset = Number(f.get("offset") || 0);
  const { data, error, loading, reload } = useApi(
    () => (can("audit.read") ? api.get<Page<AuditEntry>>("/audit-logs", { action: f.get("action"), entity_type: f.get("entity_type"), limit, offset }) : Promise.resolve(undefined)),
    [f.params.toString(), can]);
  if (!can("audit.read")) return <><PageHeader title="Audit Logs" /><Banner kind="info">Audit logs are visible to administrators only.</Banner></>;
  return (
    <>
      <PageHeader title="Audit Logs" description="Sensitive actions: sign-ins, user changes, imports, scoring, model lifecycle, alert and incident decisions, exports." />
      <section className="card">
        <div className="filters">
          <label className="field">Action<input value={f.get("action")} onChange={(e) => f.set({ action: e.target.value })} placeholder="e.g. model.activate" /></label>
          <label className="field">Entity type
            <select value={f.get("entity_type")} onChange={(e) => f.set({ entity_type: e.target.value })}>
              <option value="">Any</option>{["user", "import", "scoring_run", "model_version", "alert", "incident"].map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
          </label>
        </div>
        {error ? <ErrorState error={error} onRetry={reload} /> : data ? (data.items.length ? (
          <div className={loading ? "refetching" : ""}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Details</th><th>Client IP</th></tr></thead>
                <tbody>{data.items.map((a) => (
                  <tr key={a.id}><td><Time compact iso={a.at} /></td><td>{a.actor_name ?? "—"}</td><td className="mono">{a.action}</td>
                    <td>{a.entity_type ? `${a.entity_type} #${a.entity_id}` : "—"}</td>
                    <td className="mono" style={{ maxWidth: 420 }}>{Object.keys(a.details).length ? JSON.stringify(a.details) : ""}</td><td className="mono">{a.client_ip ?? "—"}</td></tr>
                ))}</tbody>
              </table>
            </div>
            <Pagination total={data.total} limit={limit} offset={offset} onChange={(o) => f.set({ offset: String(o) })} />
          </div>
        ) : <Empty title="No matching audit records" />) : <Loading />}
      </section>
    </>
  );
}
