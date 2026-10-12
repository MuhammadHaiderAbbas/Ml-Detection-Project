import { useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadFile } from "../api/client";
import { Can } from "../components/Can";
import type { DriftAnalysisDetail, DriftEvent, DriftWindow, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { DriftSeverityBadge, ProvenanceBadge, VerdictBadge } from "../components/Badges";
import { DistributionChart, ErrorRateChart, PsiByWindowChart } from "../components/DriftCharts";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { formatNumber, formatPct, humanize } from "../lib/format";
import { EventsTable } from "./Drift";

const fmt = (v: number | null | undefined, d = 3) => (v === null || v === undefined ? "—" : Math.abs(v) >= 1e4 ? v.toExponential(2) : v.toFixed(d));
const fmtP = (v: number | null | undefined) => (v === null || v === undefined ? "—" : v < 1e-4 ? "< 0.0001" : v.toFixed(4));

export function DriftAnalysisPage() {
  const { id } = useParams();
  const a = useApi(() => api.get<DriftAnalysisDetail>(`/drift/analyses/${id}`), [id], { pollMs: 4000 });
  const done = a.data?.status === "completed";
  const wins = useApi(() => (done ? api.get<DriftWindow[]>(`/drift/analyses/${id}/windows`) : Promise.resolve(undefined)), [id, done]);
  const events = useApi(() => (done ? api.get<Page<DriftEvent>>("/drift/events", { analysis_id: id, limit: 200 }) : Promise.resolve(undefined)), [id, done]);
  const [selected, setSelected] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<"psi" | "name">("psi");

  const featureRows = useMemo(() => {
    const feats = a.data?.overall?.features ?? {};
    const rows = Object.entries(feats).map(([name, v]) => ({ name, ...v }));
    return rows.sort((x, y) => (sortKey === "name" ? x.name.localeCompare(y.name) : (y.psi ?? -1) - (x.psi ?? -1)));
  }, [a.data, sortKey]);
  const onset = useMemo(() => {
    const m = new Map<string, number>();
    for (const w of wins.data ?? []) for (const f of w.drifted_features) if (!m.has(f)) m.set(f, w.window_index);
    return m;
  }, [wins.data]);

  if (a.error) return <ErrorState error={a.error} onRetry={a.reload} />;
  const d = a.data;
  if (!d) return <Loading />;
  const s = d.summary, o = d.overall;
  const demo = [d.reference_spec.provenance, d.current_spec.provenance].includes("synthetic_demo");
  const sel = selected ?? featureRows[0]?.name ?? null;
  const hasPerf = (wins.data ?? []).some((w) => w.performance?.error_rate !== null && w.performance?.error_rate !== undefined);

  return (
    <>
      <PageHeader title={d.name} description={<>Drift analysis #{d.id}. {s?.interpretation}</>}
        actions={<>
          {done ? <Can perm="data.export">
            <button className="btn" onClick={() => void downloadFile(`/drift/analyses/${d.id}/report.md`, `drift-report-${d.id}.md`)}><Icon name="download" size={16} />Report</button>
            <button className="btn" onClick={() => void downloadFile(`/drift/analyses/${d.id}/windows.csv`, `drift-windows-${d.id}.csv`)}><Icon name="download" size={16} />Windows CSV</button>
          </Can> : null}
          <Link className="btn" to="/drift">Back</Link>
        </>} />
      {demo ? <Banner kind="demo"><strong>Synthetic demo data.</strong> This analysis compares generated datasets; it says nothing about real traffic.</Banner> : null}
      {d.status === "failed" ? <Banner kind="error">Analysis failed: {d.error}</Banner> : null}
      {!done && d.status !== "failed" ? <Loading label={`Analysis ${d.status}…`} /> : null}

      <div className="grid grid-2">
        <section className="card" aria-labelledby="setup-h">
          <div className="card-header"><h2 id="setup-h">Setup</h2></div>
          <dl className="kv">
            <dt>Reference</dt><dd>Import <Link to={`/data-sources/${d.reference_spec.import_id}`}>#{d.reference_spec.import_id}</Link> {d.reference_spec.dataset} <ProvenanceBadge provenance={d.reference_spec.provenance} />
              {d.reference_spec.since || d.reference_spec.until ? <div className="muted"><Time iso={d.reference_spec.since} /> – <Time iso={d.reference_spec.until} /></div> : null}</dd>
            <dt>Current</dt><dd>Import <Link to={`/data-sources/${d.current_spec.import_id}`}>#{d.current_spec.import_id}</Link> {d.current_spec.dataset} <ProvenanceBadge provenance={d.current_spec.provenance} />
              {d.current_spec.since || d.current_spec.until ? <div className="muted"><Time iso={d.current_spec.since} /> – <Time iso={d.current_spec.until} /></div> : null}</dd>
            <dt>Events</dt><dd className="num">{formatNumber(d.n_reference)} reference · {formatNumber(d.n_current)} current</dd>
            <dt>Model</dt><dd>{d.model_version_id ? <Link to={`/models/${d.model_version_id}`}>#{d.model_version_id}</Link> : "None"}</dd>
            <dt>Windows</dt><dd>{d.window_spec.mode === "events" ? `${d.window_spec.size} events each` : `per ${d.window_spec.bucket}`}{s ? ` · ${s.n_windows} windows` : ""}</dd>
            <dt>Features</dt><dd>{d.features.length} tested</dd>
            <dt>Run time</dt><dd>{d.timings ? `${(d.timings.total_ms / 1000).toFixed(2)} s` : "—"}</dd>
          </dl>
        </section>
        <section className="card" aria-labelledby="ver-h">
          <div className="card-header"><h2 id="ver-h">Verdicts</h2><span className="hint">four signals, kept separate</span></div>
          {s ? (
            <div className="table-wrap"><table className="data">
              <tbody>{(["feature", "prediction", "performance", "concept"] as const).map((t) => (
                <tr key={t}><th scope="row" style={{ textAlign: "left" }}>{humanize(t)} drift</th>
                  <td><VerdictBadge status={s[t].status} /></td><td>{s[t].severity ? <DriftSeverityBadge severity={s[t].severity!} /> : null}</td>
                  <td className="muted">{s[t].reason ?? (t === "feature" && s.features_drifted.length ? s.features_drifted.join(", ") : "")}</td></tr>
              ))}</tbody>
            </table></div>
          ) : <Loading />}
          {o?.prediction ? (
            <p className="secondary" style={{ marginBottom: 0 }}>Suspicious rate: {formatPct(o.prediction.suspicious_rate_ref)} reference → {formatPct(o.prediction.suspicious_rate_cur)} current
              {o.prediction.psi !== null ? ` · class-mix PSI ${fmt(o.prediction.psi)}` : ""}.</p>
          ) : null}
          {o ? <p className="secondary" style={{ marginBottom: 0 }}>Error rate (dataset labels): {formatPct(o.performance.reference.error_rate, 2)} reference → {formatPct(o.performance.current.error_rate, 2)} current
            {o.performance.reference.n_labelled === 0 ? " — no labels, performance not assessable." : "."}</p> : null}
        </section>
      </div>

      {done && wins.data ? (
        <>
          <section className="card" style={{ marginTop: 16 }} aria-labelledby="psi-h">
            <div className="card-header"><h2 id="psi-h">Drift over time</h2><span className="hint">current windows compared with the reference</span></div>
            <PsiByWindowChart windows={wins.data} moderate={Number(d.config.psi_moderate)} major={Number(d.config.psi_major)} hasPrediction={!!d.model_version_id && !!o?.prediction} />
          </section>
          {hasPerf ? (
            <section className="card" aria-labelledby="perf-h">
              <div className="card-header"><h2 id="perf-h">Error rate over time</h2></div>
              <ErrorRateChart windows={wins.data} referenceRate={o?.performance.reference.error_rate ?? null} />
            </section>
          ) : null}
        </>
      ) : null}

      {o ? (
        <div className="stack" style={{ marginTop: 16 }}>
          <section className="card" aria-labelledby="feat-h">
            <div className="card-header"><h2 id="feat-h">Features</h2><span className="hint">whole current sample vs reference · select a row</span>
              <div className="right toggle-group" role="group" aria-label="Sort">
                <button aria-pressed={sortKey === "psi"} onClick={() => setSortKey("psi")}>By PSI</button>
                <button aria-pressed={sortKey === "name"} onClick={() => setSortKey("name")}>By name</button>
              </div></div>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Feature</th><th className="num">PSI</th><th className="num">KS D</th><th className="num">p (adj.)</th><th className="num">Ref median</th><th className="num">Cur median</th><th>Severity</th><th className="num">Onset window</th></tr></thead>
                <tbody>{featureRows.map((r) => (
                  <tr key={r.name} className="clickable" onClick={() => setSelected(r.name)} aria-selected={sel === r.name}
                    style={sel === r.name ? { background: "var(--accent-wash)" } : undefined}>
                    <td className="mono" style={{ whiteSpace: "nowrap" }}><button className="btn ghost small mono" style={{ padding: 0, minHeight: 0 }} onClick={() => setSelected(r.name)}>{r.name}</button></td>
                    <td className="num">{fmt(r.psi)}</td><td className="num">{fmt(r.ks_d)}</td><td className="num" style={{ whiteSpace: "nowrap" }}>{fmtP(r.ks_p_adj)}</td>
                    <td className="num">{fmt(r.ref_median, 2)}</td><td className="num">{fmt(r.cur_median, 2)}</td>
                    <td><DriftSeverityBadge severity={r.severity} /></td><td className="num">{onset.has(r.name) ? `#${onset.get(r.name)}` : "—"}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          </section>
          <section className="card" aria-labelledby="dist-h">
            <div className="card-header"><h2 id="dist-h">Distribution: <span className="mono">{sel}</span></h2></div>
            {sel && o.features[sel] ? <DistributionChart feature={sel} stat={o.features[sel]} /> : null}
          </section>
        </div>
      ) : null}

      {done ? (
        <section className="card" style={{ marginTop: 16 }} aria-labelledby="dev-h">
          <div className="card-header"><h2 id="dev-h">Drift events from this analysis</h2></div>
          {events.data ? (events.data.items.length ? <EventsTable events={events.data.items} /> : <p className="muted">No drift events were raised.</p>) : <Loading />}
        </section>
      ) : null}

      <details className="card" style={{ marginTop: 16 }}>
        <summary><strong>Thresholds and rules used</strong></summary>
        <dl className="kv" style={{ marginTop: 12 }}>
          <dt>PSI</dt><dd>moderate ≥ {String(d.config.psi_moderate)}, major ≥ {String(d.config.psi_major)} ({String(d.config.psi_bins)} reference-quantile bins)</dd>
          <dt>Significance</dt><dd>KS (features) or chi-square (class mix) p after Bonferroni &lt; {String(d.config.alpha)}; PSI alone never triggers</dd>
          <dt>Minimum sample</dt><dd>{String(d.config.min_window_events)} events per sample/window; {String(d.config.perf_min_labels)} labels for performance</dd>
          <dt>Performance</dt><dd>error-rate rise ≥ {String(d.config.perf_moderate)} moderate, ≥ {String(d.config.perf_major)} major</dd>
          <dt>Streaming</dt><dd>ADWIN (River), delta {String(d.config.adwin_delta)}, on 0/1 suspicious and error indicators in event-time order</dd>
          <dt>Concept drift</dt><dd>reported as suspected only when performance degrades without feature drift</dd>
        </dl>
      </details>
    </>
  );
}
