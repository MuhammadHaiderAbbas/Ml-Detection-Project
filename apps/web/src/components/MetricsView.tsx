import type { Metrics } from "../api/types";
import { formatNumber, formatPct } from "../lib/format";

export function MetricsView({ m }: { m: Metrics }) {
  const b = m.binary_attack_vs_benign;
  const cm = m.confusion_matrix;
  return (
    <div className="stack">
      <div className="grid grid-kpi">
        <div className="kpi"><div className="label">Accuracy</div><div className="value">{formatPct(m.accuracy)}</div><div className="sub">{formatNumber(m.n_scored)} scored rows</div></div>
        <div className="kpi"><div className="label">Macro F1</div><div className="value">{formatPct(m.averages.macro.f1)}</div></div>
        {b ? <>
          <div className="kpi"><div className="label">Attack recall</div><div className="value">{formatPct(b.recall_detection_rate)}</div></div>
          <div className="kpi"><div className="label">False-positive rate</div><div className="value">{formatPct(b.false_positive_rate, 2)}</div></div>
        </> : null}
      </div>
      <div className="table-wrap">
        <table className="data">
          <thead><tr><th>Class</th><th className="num">Precision</th><th className="num">Recall</th><th className="num">F1</th><th className="num">Support</th></tr></thead>
          <tbody>{Object.entries(m.per_class).map(([k, v]) => (
            <tr key={k}><td>{k}</td><td className="num">{formatPct(v.precision)}</td><td className="num">{formatPct(v.recall)}</td><td className="num">{formatPct(v.f1)}</td><td className="num">{formatNumber(v.support)}</td></tr>
          ))}</tbody>
        </table>
      </div>
      <div className="table-wrap">
        <table className="data" aria-label="Confusion matrix, rows are true classes and columns are predicted classes">
          <caption className="muted" style={{ textAlign: "left", paddingBottom: 6 }}>Confusion matrix (rows = true class, columns = predicted)</caption>
          <thead><tr><th>True \ Predicted</th>{cm.labels.map((l) => <th key={l} className="num">{l}</th>)}</tr></thead>
          <tbody>{cm.rows_true_cols_pred.map((row, i) => (
            <tr key={cm.labels[i]}><th scope="row" style={{ textAlign: "left" }}>{cm.labels[i]}</th>{row.map((v, j) => <td key={j} className="num">{formatNumber(v)}</td>)}</tr>
          ))}</tbody>
        </table>
      </div>
    </div>
  );
}
