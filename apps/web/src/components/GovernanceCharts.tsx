import { useState } from "react";
import type { EvaluationDetail, GovMetric } from "../api/types";

export const METRIC_LABEL: Record<GovMetric, string> = {
  attack_recall: "Attack recall", false_positive_rate: "False-positive rate", precision: "Precision", f1: "F1", accuracy: "Accuracy",
};
const ORDER: GovMetric[] = ["attack_recall", "false_positive_rate", "f1", "precision", "accuracy"];
const pp = (v: number) => `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(2)} pp`;

function niceStep(span: number): number {
  const raw = span / 4;
  const p = 10 ** Math.floor(Math.log10(raw));
  return [1, 2, 2.5, 5, 10].map((m) => m * p).find((s) => s >= raw) ?? raw;
}

/**
 * Forest plot of candidate − baseline with the protocol's confidence interval, on the true sign.
 * For gated metrics the dashed line is the non-inferiority margin and the shaded side is
 * "beyond the margin" (left for recall and F1, right for the false-positive rate).
 */
export function DifferenceChart({ ev }: { ev: EvaluationDetail }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<GovMetric | null>(null);
  const r = ev.results!;
  const p = ev.protocol;
  const margins: Partial<Record<GovMetric, number>> = {
    attack_recall: Number(p.recall_margin), f1: Number(p.f1_margin), false_positive_rate: Number(p.fpr_margin),
  };
  const conf = Math.round(Number(p.confidence) * 100);
  const rows = ORDER.filter((m) => r.differences[m]?.difference !== null && r.differences[m]?.difference !== undefined).map((m) => {
    const d = r.differences[m]!;
    const lowerBetter = d.better_when === "lower";
    const lo = d.ci_low ?? d.difference!, hi = d.ci_high ?? d.difference!;
    const gate = ev.gates?.find((g) => g.id === `non_inferior_${m}`);
    const margin = margins[m] === undefined ? undefined : (lowerBetter ? margins[m]! : -margins[m]!);
    return { m, point: d.difference!, lo, hi, raw: d, margin, lowerBetter, gate };
  });
  const extent = Math.max(0.005, ...rows.flatMap((x) => [Math.abs(x.lo), Math.abs(x.hi), x.margin ?? 0])) * 1.2;
  const step = niceStep(2 * extent);
  const max = Math.ceil(extent / step) * step;
  const ticks: number[] = [];
  for (let t = -max; t <= max + 1e-12; t += step) ticks.push(Math.round(t * 1e6) / 1e6);
  const x = (v: number) => `${((v + max) / (2 * max)) * 100}%`;

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <div className="chart-legend">
          <span><i style={{ background: "var(--series-1)" }} />Candidate − baseline, {conf} % CI</span>
          <span><i className="dash" />Non-inferiority margin</span>
        </div>
        <div className="toggle-group" role="group" aria-label="View">
          <button aria-pressed={view === "chart"} onClick={() => setView("chart")}>Chart</button>
          <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
        </div>
      </div>
      {view === "chart" ? (
        <div className="forest" role="img" aria-label={`Difference between candidate and baseline per metric with ${conf} percent confidence intervals and non-inferiority margins. Use the table view for values.`}>
          {rows.map((row) => (
            <div className="forest-row" key={row.m} onMouseEnter={() => setHover(row.m)} onMouseLeave={() => setHover(null)}>
              <div className="forest-label">{METRIC_LABEL[row.m]}{row.lowerBetter || row.margin === undefined ? <span className="muted">{[row.lowerBetter ? "lower is better" : "", row.margin === undefined ? "not gated" : ""].filter(Boolean).join(" · ")}</span> : null}</div>
              <div className="forest-track">
                {row.margin !== undefined ? <span className="forest-beyond" style={row.lowerBetter ? { left: x(row.margin), right: 0 } : { left: 0, width: x(row.margin) }} /> : null}
                <span className="forest-zero" style={{ left: x(0) }} />
                {row.margin !== undefined ? <span className="forest-margin" style={{ left: x(row.margin) }} /> : null}
                <span className="forest-ci" style={{ left: x(row.lo), width: `${((row.hi - row.lo) / (2 * max)) * 100}%` }} />
                <span className="forest-pt" style={{ left: x(row.point) }} />
                {hover === row.m ? (
                  <div className="chart-tooltip forest-tip" style={{ left: x(row.point) }}>
                    <div className="t">{METRIC_LABEL[row.m]}</div>
                    <div className="r"><span>Difference</span><span className="num">{pp(row.raw.difference!)}</span></div>
                    <div className="r"><span>{conf} % CI</span><span className="num">{pp(row.raw.ci_low!)} … {pp(row.raw.ci_high!)}</span></div>
                    {row.margin !== undefined ? <div className="r"><span>Gate</span><span>{row.gate?.passed ? "within margin" : "beyond margin"}</span></div> : null}
                  </div>
                ) : null}
              </div>
              <div className="forest-value num">{pp(row.raw.difference!)}</div>
            </div>
          ))}
          <div className="forest-row forest-axis" aria-hidden="true">
            <div className="forest-label" />
            <div className="forest-track">
              {ticks.map((t) => <span key={t} className="forest-tick" style={{ left: x(t) }}>{t === 0 ? "0" : `${t > 0 ? "+" : "−"}${Math.abs(t * 100).toFixed(step * 100 < 1 ? 1 : 0)}`}</span>)}
            </div>
            <div className="forest-value" />
          </div>
          <div className="forest-row forest-axis" aria-hidden="true">
            <div className="forest-label" />
            <div className="forest-track forest-dir"><span>← lower</span><span>candidate − baseline (pp)</span><span>higher →</span></div>
            <div className="forest-value" />
          </div>
        </div>
      ) : (
        <div className="table-wrap">
          <table className="data">
            <thead><tr><th>Metric</th><th className="num">Difference</th><th className="num">{conf} % CI low</th><th className="num">{conf} % CI high</th><th>Better when</th><th className="num">Margin</th><th>Gate</th></tr></thead>
            <tbody>{rows.map((row) => (
              <tr key={row.m}><td>{METRIC_LABEL[row.m]}</td><td className="num">{pp(row.raw.difference!)}</td><td className="num">{pp(row.raw.ci_low!)}</td>
                <td className="num">{pp(row.raw.ci_high!)}</td><td>{row.raw.better_when}</td>
                <td className="num">{row.margin !== undefined ? pp(row.margin) : "—"}</td>
                <td>{row.gate ? (row.gate.passed ? "Pass" : "Fail") : "Not gated"}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
        Paired bootstrap over the same events ({String(p.bootstrap_iterations)} resamples). A gate passes when the whole interval stays
        out of the shaded area beyond its margin.
      </p>
    </div>
  );
}
