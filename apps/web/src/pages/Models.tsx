import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api/client";
import type { ExperimentRun, ModelVersion } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { ModelStatusBadge, ProvenanceBadge } from "../components/Badges";
import { PageHeader } from "../components/PageHeader";
import { Banner, Empty, ErrorState, Loading, Time } from "../components/States";
import { formatPct, shortHash } from "../lib/format";

export function ModelsPage() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const models = useApi(() => api.get<ModelVersion[]>("/models"), []);
  const runs = useApi(() => api.get<ExperimentRun[]>("/experiment-runs"), []);
  const [err, setErr] = useState<string>();
  const register = async (run: string) => {
    setErr(undefined);
    try { const m = await api.post<ModelVersion>("/models/register-run", { run_name: run }); navigate(`/models/${m.id}`); }
    catch (x) { setErr((x as Error).message); }
  };
  return (
    <>
      <PageHeader title="Model Management" description="Registered model versions and their lifecycle. Promotion always needs recorded test results and an explicit admin approval; nothing is promoted automatically." />
      {err ? <Banner kind="error">{err}</Banner> : null}
      <section className="card" aria-labelledby="mv-h">
        <div className="card-header"><h2 id="mv-h">Model versions</h2></div>
        {models.error ? <ErrorState error={models.error} onRetry={models.reload} /> : models.data ? (models.data.length ? (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Version</th><th>Type</th><th>Status</th><th>Provenance</th><th>Artifact SHA-256</th><th>Registered</th><th>Activated</th></tr></thead>
              <tbody>{models.data.map((m) => (
                <tr key={m.id} className="clickable" onClick={() => navigate(`/models/${m.id}`)}>
                  <td><Link to={`/models/${m.id}`} onClick={(e) => e.stopPropagation()}><code>{m.version_id}</code></Link></td>
                  <td>{m.model_type}</td><td><ModelStatusBadge status={m.status} /></td><td><ProvenanceBadge provenance={m.provenance} /></td>
                  <td className="mono">{shortHash(m.artifact_sha256)}</td><td><Time compact iso={m.created_at} /></td><td><Time compact iso={m.activated_at} /></td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="No model versions registered">Register an experiment run below (admin only).</Empty>) : <Loading />}
      </section>
      <section className="card" aria-labelledby="runs-h">
        <div className="card-header"><h2 id="runs-h">Experiment runs available to register</h2><span className="hint">from the server's experiments directory</span></div>
        {runs.data ? (runs.data.length ? (
          <div className="table-wrap">
            <table className="data">
              <thead><tr><th>Run</th><th>Experiment</th><th>Provenance</th><th className="num">Test accuracy</th><th></th></tr></thead>
              <tbody>{runs.data.map((r) => (
                <tr key={r.run_name}>
                  <td className="mono">{r.run_name}</td><td>{r.experiment_id}</td><td>{r.provenance ? <ProvenanceBadge provenance={r.provenance} /> : "—"}</td>
                  <td className="num">{formatPct(r.test_accuracy)}</td>
                  <td>{r.registered ? <span className="muted">Registered</span> : user?.role === "admin"
                    ? <button className="btn small" onClick={() => void register(r.run_name)}>Register as candidate</button> : <span className="muted">Admin can register</span>}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
        ) : <Empty title="No experiment runs">Run an experiment with <code>adaptive-ids run</code>.</Empty>) : <Loading />}
      </section>
    </>
  );
}
