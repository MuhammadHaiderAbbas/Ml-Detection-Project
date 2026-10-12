import { Fragment } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadFile } from "../api/client";
import { Can } from "../components/Can";
import type { EvaluationDetail, Gate, GovMetric, GovMetrics } from "../api/types";
import { useApi } from "../api/useApi";
import { EvaluationVerdictBadge, ProvenanceBadge } from "../components/Badges";
import { DifferenceChart, METRIC_LABEL } from "../components/GovernanceCharts";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { formatNumber, formatPct, humanize, shortHash } from "../lib/format";

const METRICS: GovMetric[] = ["attack_recall", "false_positive_rate", "precision", "f1", "accuracy"];

function gateValue(g: Gate): string {
  if (g.id.startsWith("non_inferior_")) {
    const f = (v: number | null) => (v === null ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(2)} pp`);
    return `${f(g.value)} ${g.id.endsWith("false_positive_rate") ? "≤" : "≥"} ${f(g.threshold)}`;
  }
  const pctish = !["labelled_events", "attack_events", "benign_events"].includes(g.id);
  const f = (v: number | null) => (v === null ? "—" : pctish ? `${(v * 100).toFixed(2)} %` : formatNumber(v));
  const op = g.id.startsWith("max_") || g.id.endsWith("failed_predictions") || g.id === "non_inferior_false_positive_rate" ? "≤" : "≥";
  return `${f(g.value)} ${op} ${f(g.threshold)}`;
}

export function GateList({ gates }: { gates: Gate[] }) {
  return (
    <ul className="gate-list">
      {gates.map((g) => (
        <li key={g.id}>
          <span style={{ color: g.passed ? "var(--status-good)" : g.passed === false ? "var(--status-critical)" : "var(--text-muted)", display: "inline-flex", marginTop: 2 }}>
            <Icon name={g.passed ? "check" : g.passed === false ? "x" : "circle"} size={16} title={g.passed ? "Passed" : g.passed === false ? "Failed" : "Not applicable"} />
          </span>
          <div><div>{g.detail.charAt(0).toUpperCase() + g.detail.slice(1)}</div><div className="gk">{g.kind === "validity" ? "Validity gate" : "Performance gate"} · <code>{g.id}</code></div></div>
          <div className="gv num">{gateValue(g)}</div>
        </li>
      ))}
    </ul>
  );
}

function verdictText(ev: EvaluationDetail): string {
  const failed = (ev.gates ?? []).filter((g) => g.passed === false).map((g) => g.detail);
  if (ev.verdict === "pass") return "Every gate passed. An administrator can approve this candidate; approval is still a separate, explicit decision.";
  if (ev.verdict === "fail") return `The evidence is valid, but these gates failed: ${failed.join("; ")}. Approving needs an explicit override with a written justification, which is audited separately.`;
  return `The evidence is not sufficient (${failed.join("; ")}). This evaluation cannot support an approval, with or without an override.`;
}

function MetricsTable({ c, b }: { c: GovMetrics; b?: GovMetrics }) {
  return (
    <div className="table-wrap">
      <table className="data">
        <thead><tr><th>Attack vs benign</th><th className="num">Candidate</th>{b ? <th className="num">Baseline</th> : null}</tr></thead>
        <tbody>
          {METRICS.map((m) => <tr key={m}><td>{METRIC_LABEL[m]}</td><td className="num">{formatPct(c[m], 2)}</td>{b ? <td className="num">{formatPct(b[m], 2)}</td> : null}</tr>)}
          {(["tp", "fp", "tn", "fn"] as const).map((k) => (
            <tr key={k}><td className="secondary">{{ tp: "Attacks flagged (TP)", fp: "Benign flagged (FP)", tn: "Benign passed (TN)", fn: "Attacks missed (FN)" }[k]}</td>
              <td className="num">{formatNumber(c.confusion[k])}</td>{b ? <td className="num">{formatNumber(b.confusion[k])}</td> : null}</tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function EvaluationDetailPage() {
  const { id } = useParams();
  const q = useApi(() => api.get<EvaluationDetail>(`/evaluations/${id}`), [id], { pollMs: 3000 });
  if (q.error) return <ErrorState error={q.error} onRetry={q.reload} />;
  const ev = q.data;
  if (!ev) return <Loading />;
  const d = ev.data;
  const r = ev.results;
  const done = ev.status === "completed" && r;
  const synthetic = [d.provenance, d.candidate.provenance, d.baseline?.provenance].includes("synthetic_demo");
  const c = r?.metrics.candidate, b = r?.metrics.baseline;
  return (
    <>
      <PageHeader title={`Candidate evaluation #${ev.id}`}
        description={<><code>{d.candidate.version_id}</code> vs {d.baseline ? <code>{d.baseline.version_id}</code> : "no baseline"} · protocol v{ev.protocol_version}</>}
        actions={<>
          {done ? <Can perm="data.export"><button className="btn" onClick={() => void downloadFile(`/evaluations/${ev.id}/report.md`, `evaluation-${ev.id}.md`)}><Icon name="download" size={16} />Report</button></Can> : null}
          <Link className="btn" to={`/models/${ev.model_version_id}`}>Back to model</Link>
        </>} />
      {synthetic ? <Banner kind="demo"><strong>Synthetic demo.</strong> Generated data or a synthetic model is involved; these numbers show the workflow, not real detection performance.</Banner> : null}
      {ev.status === "failed" ? <Banner kind="error">Evaluation failed: {ev.error}</Banner> : null}
      {!done && ev.status !== "failed" ? <Loading label={`Evaluation ${ev.status}…`} /> : null}
      {done && c ? (
        <>
          <section className="card" aria-labelledby="vd-h">
            <div className="card-header"><h2 id="vd-h">Verdict</h2><EvaluationVerdictBadge verdict={ev.verdict} /></div>
            <p style={{ margin: 0 }}>{verdictText(ev)}</p>
          </section>
          <div className="grid grid-kpi" style={{ marginTop: 16 }}>
            <div className="kpi"><div className="label">Compared events</div><div className="value">{formatNumber(r.counts.compared_events)}</div>
              <div className="sub">{formatNumber(r.counts.attack_events)} attack · {formatNumber(r.counts.benign_events)} benign (dataset labels)</div></div>
            <div className="kpi"><div className="label">Attack recall</div><div className="value">{formatPct(c.attack_recall, 1)}</div>
              <div className="sub">{b ? `baseline ${formatPct(b.attack_recall, 1)}` : "candidate only"}</div></div>
            <div className="kpi"><div className="label">False-positive rate</div><div className="value">{formatPct(c.false_positive_rate, 2)}</div>
              <div className="sub">{b ? `baseline ${formatPct(b.false_positive_rate, 2)}` : "candidate only"}</div></div>
            <div className="kpi"><div className="label">F1 (attack class)</div><div className="value">{formatPct(c.f1, 1)}</div>
              <div className="sub">{b ? `baseline ${formatPct(b.f1, 1)}` : "candidate only"}</div></div>
          </div>
          <div className="grid grid-wide-left" style={{ marginTop: 16 }}>
            <section className="card" aria-labelledby="df-h">
              <div className="card-header"><h2 id="df-h">Candidate vs baseline</h2><span className="hint">same events, same labels</span></div>
              {r.baseline_present ? <DifferenceChart ev={ev} /> : (
                <p className="muted">No model was active when this evaluation started, so there is no baseline to compare with. Only the validity
                  gates{(ev.gates ?? []).some((g) => g.kind === "performance") ? " and the protocol's absolute requirements" : ""} apply.</p>
              )}
            </section>
            <section className="card" aria-labelledby="mt-h">
              <div className="card-header"><h2 id="mt-h">Metrics</h2></div>
              <MetricsTable c={c} b={b} />
            </section>
          </div>
          <div className="grid grid-2" style={{ marginTop: 16 }}>
            <section className="card" aria-labelledby="gt-h">
              <div className="card-header"><h2 id="gt-h">Protocol gates</h2><span className="hint">v{ev.protocol_version}</span></div>
              <GateList gates={ev.gates ?? []} />
            </section>
            <section className="card" aria-labelledby="dp-h">
              <div className="card-header"><h2 id="dp-h">Evidence</h2></div>
              <dl className="kv">
                <dt>Data</dt><dd><Link to={`/data-sources/${d.import_id}`}>Import #{d.import_id}</Link> · {d.dataset} <ProvenanceBadge provenance={d.provenance} /></dd>
                <dt>File SHA-256</dt><dd className="mono">{shortHash(d.file_sha256, 16)}</dd>
                <dt>Truth</dt><dd>{d.truth}</dd>
                <dt>Basis</dt><dd>{r.basis}</dd>
                <dt>Candidate</dt><dd><Link to={`/models/${ev.model_version_id}`}><code>{d.candidate.version_id}</code></Link></dd>
                <dt>Baseline</dt><dd>{d.baseline && ev.baseline_model_version_id ? <Link to={`/models/${ev.baseline_model_version_id}`}><code>{d.baseline.version_id}</code></Link> : "—"}</dd>
                <dt>McNemar</dt><dd>{r.mcnemar ? <>Candidate alone right on {formatNumber(r.mcnemar.candidate_only_correct)} events, baseline alone on {formatNumber(r.mcnemar.baseline_only_correct)};
                  p = {r.mcnemar.p_value.toPrecision(3)} ({r.mcnemar.method}). <span className="muted">Context only, not a gate.</span></> : "—"}</dd>
                <dt>Run</dt><dd><Time iso={ev.completed_at} /> · {((ev.duration_ms ?? 0) / 1000).toFixed(1)} s</dd>
              </dl>
              <details style={{ marginTop: 12 }}>
                <summary>Protocol settings</summary>
                <dl className="kv" style={{ marginTop: 8 }}>
                  {Object.entries(ev.protocol).map(([k, v]) => <Fragment key={k}><dt>{humanize(k)}</dt><dd className="mono">{v === null ? "not set" : String(v)}</dd></Fragment>)}
                </dl>
              </details>
            </section>
          </div>
        </>
      ) : null}
    </>
  );
}
