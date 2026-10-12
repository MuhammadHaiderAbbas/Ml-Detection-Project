import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { ExperimentRun } from "../api/types";
import { useApi } from "../api/useApi";
import { ProvenanceBadge } from "../components/Badges";
import { PageHeader } from "../components/PageHeader";
import { Banner, Empty, ErrorState, Loading } from "../components/States";
import { formatPct } from "../lib/format";

export function ExperimentsPage() {
  const runs = useApi(() => api.get<ExperimentRun[]>("/experiment-runs"), []);
  return (
    <>
      <PageHeader title="Experiments" description="Reproducible experiment runs on the server. Each run directory holds result.json and report.md with dataset hash, split manifest, environment and limitations." />
      <Banner kind="info">
        Run experiments with <code>adaptive-ids run &lt;config.json&gt;</code>. Original dissertation results, baseline reproductions,
        new controlled experiments and synthetic demos are kept separate by their provenance label.
      </Banner>
      <section className="card">
        {runs.error ? <ErrorState error={runs.error} onRetry={runs.reload} /> : runs.data ? (runs.data.length ? (
          <table className="data">
            <thead><tr><th>Run directory</th><th>Experiment</th><th>Provenance</th><th>Model version</th><th className="num">Test accuracy</th><th>Registered</th></tr></thead>
            <tbody>{runs.data.map((r) => (
              <tr key={r.run_name}><td className="mono">{r.run_name}</td><td>{r.experiment_id}</td><td>{r.provenance ? <ProvenanceBadge provenance={r.provenance} /> : "—"}</td>
                <td className="mono">{r.model_version}</td><td className="num">{formatPct(r.test_accuracy)}</td><td>{r.registered ? "Yes" : <Link to="/models">Register…</Link>}</td></tr>
            ))}</tbody>
          </table>
        ) : <Empty title="No experiment runs yet" />) : <Loading />}
      </section>
    </>
  );
}
