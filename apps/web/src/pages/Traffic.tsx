import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Page, TrafficRow } from "../api/types";
import { useApi } from "../api/useApi";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { ImportSelect, ModelSelect } from "../components/Selectors";
import { Banner, Empty, ErrorState, Loading, Time } from "../components/States";
import { useUrlFilters } from "../lib/filters";
import { formatScore } from "../lib/format";

export function TrafficPage() {
  const f = useUrlFilters();
  const limit = 50;
  const offset = Number(f.get("offset") || 0);
  const suspicious = f.get("suspicious") === "1";
  const { data, error, loading, reload } = useApi(
    () => api.get<Page<TrafficRow>>("/traffic", { import_id: f.get("import_id"), model_version_id: f.get("model_version_id"), suspicious_only: suspicious, limit, offset }),
    [f.params.toString()], { pollMs: 30000 });
  return (
    <>
      <PageHeader title="Live Traffic" description="Recorded network events and the latest model verdict for each, newest event time first." />
      <Banner kind="info">
        This version replays <strong>imported, recorded data</strong>. Live telemetry (Zeek, NetFlow/IPFIX) is a later integration;
        nothing here is captured from your network.
      </Banner>
      <div className="card">
        <div className="filters">
          <ImportSelect value={f.get("import_id")} onChange={(v) => f.set({ import_id: v })} />
          <ModelSelect value={f.get("model_version_id")} onChange={(v) => f.set({ model_version_id: v })} />
          <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={suspicious} style={{ minHeight: 0 }}
            onChange={(e) => f.set({ suspicious: e.target.checked ? "1" : null })} />Suspicious only</label>
        </div>
        {error ? <ErrorState error={error} onRetry={reload} /> : null}
        {data ? (data.items.length ? (
          <div className={loading ? "refetching" : ""}>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Event time</th><th>Event</th><th>Source</th><th>Destination</th><th>Verdict</th><th>Predicted class</th><th className="num">Score*</th><th>Dataset label</th></tr></thead>
                <tbody>
                  {data.items.map(({ event: e, prediction: p }) => (
                    <tr key={e.id}>
                      <td><Time compact iso={e.occurred_at} /></td>
                      <td className="mono">{e.event_key ?? `#${e.id}`}</td>
                      <td className="mono">{e.source ?? "—"}</td>
                      <td className="mono">{e.destination ?? "—"}</td>
                      <td>{!p ? <span className="muted">Not scored</span> : p.status !== "ok" ? <span className="badge">Rejected</span>
                        : p.is_suspicious ? <span className="badge" style={{ borderColor: "var(--series-2)" }}>Suspicious</span> : <span className="badge">Not flagged</span>}</td>
                      <td>{p?.predicted_class ?? "—"}</td>
                      <td className="num">{formatScore(p?.score)}</td>
                      <td className="muted">{e.dataset_label ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p className="muted" style={{ fontSize: 12 }}>*Uncalibrated model score. The dataset label came with the imported file and is shown for evaluation context only. Suspicious events have alerts on the <Link to="/alerts">Alerts</Link> page.</p>
            <Pagination total={data.total} limit={limit} offset={offset} onChange={(o) => f.set({ offset: String(o) })} />
          </div>
        ) : <Empty title="No events">Import data on the <Link to="/data-sources">Data Sources</Link> page, then score it.</Empty>) : <Loading />}
      </div>
    </>
  );
}
