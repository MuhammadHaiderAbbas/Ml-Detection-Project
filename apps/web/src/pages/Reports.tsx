import { Link } from "react-router-dom";
import { downloadFile } from "../api/client";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";

export function ReportsPage() {
  return (
    <>
      <PageHeader title="Reports" description="Exports available today. Each carries its methodology notes; model outputs are labelled as suspicions with uncalibrated scores." />
      <div className="grid grid-2">
        <section className="card">
          <h2>Alerts (CSV)</h2>
          <p className="secondary">All alerts with status, severity rule, model version, import and group. Filter on the <Link to="/alerts">Alerts</Link> page to export a subset.</p>
          <button className="btn" onClick={() => void downloadFile("/alerts/export.csv", "alerts.csv")}><Icon name="download" size={16} />Download all alerts</button>
        </section>
        <section className="card">
          <h2>Incident summary (Markdown)</h2>
          <p className="secondary">Linked alerts, timeline, evidence and the analyst disposition. Export from any <Link to="/incidents">incident</Link> page.</p>
        </section>
        <section className="card">
          <h2>Experiment and baseline reports</h2>
          <p className="secondary">Classification report, confusion matrix, dataset hash, split, environment and limitations are written by
            <code> adaptive-ids run</code> to each run's <code>report.md</code>. See <Link to="/experiments">Experiments</Link>.</p>
        </section>
        <section className="card">
          <h2>Drift reports (Markdown, CSV)</h2>
          <p className="secondary">Verdicts, per-feature statistics, thresholds, events and limitations, plus per-window results as CSV. Export from any <Link to="/drift">drift analysis</Link>.</p>
        </section>
        <section className="card">
          <h2>Planned</h2>
          <p className="secondary">Model comparison reports (Phase 6) and PDF output are not available yet.</p>
        </section>
      </div>
    </>
  );
}
