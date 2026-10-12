import { useState } from "react";
import type { Explanation } from "../api/types";

const TOP = 10;
const SPACE_UNIT: Record<string, string> = {
  probability: "score", log_odds: "log-odds", class_logit: "raw class score",
};

function signed(v: number, digits = 4): string {
  const s = Math.abs(v).toFixed(digits);
  return v > 0 ? `+${s}` : v < 0 ? `−${s}` : s;
}

function num(v: number | null | undefined): string {
  if (v === null || v === undefined) return "—";
  return Number.isInteger(v) ? String(v) : Number(v.toPrecision(6)).toString();
}

/**
 * Diverging bars of SHAP contributions for one prediction: right (orange) pushes the model's output
 * toward the explained class, left (blue) pushes it away. The top features are shown individually and
 * the rest are summed into one row, so the bars still add up from the base value to the model output.
 */
export function ExplanationChart({ x }: { x: Explanation }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const [hover, setHover] = useState<string | null>(null);
  const all = x.contributions;
  const top = all.slice(0, TOP);
  const rest = all.slice(TOP);
  const restSum = rest.reduce((s, c) => s + c.contribution, 0);
  const rows = [
    ...top.map((c) => ({ key: c.feature, label: c.feature, value: c.contribution, raw: c.raw_value, input: c.model_input as number | null })),
    ...(rest.length ? [{ key: "__rest", label: `${rest.length} other features`, value: restSum, raw: null, input: null }] : []),
  ];
  // Domain spans only the signs present, so one-sided explanations use the full width; zero stays marked.
  const lo = Math.min(0, ...rows.map((r) => r.value));
  const hi = Math.max(0, ...rows.map((r) => r.value));
  const span = Math.max(1e-12, hi - lo);
  const at = (v: number) => `${((v - lo) / span) * 100}%`;
  const unit = SPACE_UNIT[x.output_space ?? "probability"];
  const target = x.target_class ?? "";
  const width = (v: number) => `${(Math.abs(v) / span) * 100}%`;

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 10 }}>
        <div className="chart-legend">
          <span><i style={{ background: "var(--series-2)" }} />Raises the {unit} for “{target}”</span>
          <span><i style={{ background: "var(--series-1)" }} />Lowers it</span>
        </div>
        <div className="toggle-group" role="group" aria-label="View">
          <button aria-pressed={view === "chart"} onClick={() => setView("chart")}>Chart</button>
          <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
        </div>
      </div>
      <p className="shap-sum">
        Base value <span className="num">{num(x.base_value)}</span>
        {" + "}contributions <span className="num">{signed((x.model_output ?? 0) - (x.base_value ?? 0))}</span>
        {" = "}model output <strong className="num">{num(x.model_output)}</strong>
        <span className="muted"> ({unit} for “{target}”)</span>
      </p>
      {view === "chart" ? (
        <div className="shap" role="img" aria-label={`Feature contributions to the ${unit} for ${target}. Use the table view for exact values.`}>
          {rows.map((r) => (
            <div className="shap-row" key={r.key} onMouseEnter={() => setHover(r.key)} onMouseLeave={() => setHover(null)}>
              <div className={r.key === "__rest" ? "shap-label muted" : "shap-label"} title={r.label}>{r.label}</div>
              <div className="shap-track">
                <span className="shap-zero" style={{ left: at(0) }} />
                <span className={r.value >= 0 ? "shap-bar pos" : "shap-bar neg"}
                  style={{ left: at(Math.min(0, r.value)), width: width(r.value) }} />
                {hover === r.key ? (
                  <div className="chart-tooltip shap-tip" style={{ left: at(r.value / 2) }}>
                    <div className="t">{r.label}</div>
                    <div className="r"><span>Contribution</span><span className="num">{signed(r.value, 6)}</span></div>
                    {r.key !== "__rest" ? <>
                      <div className="r"><span>Imported value</span><span className="num">{num(r.raw)}</span></div>
                      <div className="r"><span>Model input</span><span className="num">{num(r.input)}</span></div>
                    </> : <div className="r"><span>Sum of</span><span>{rest.length} smaller contributions</span></div>}
                  </div>
                ) : null}
              </div>
              <div className="shap-value num">{signed(r.value)}</div>
            </div>
          ))}
        </div>
      ) : (
        <div className="table-wrap" style={{ maxHeight: 360, overflowY: "auto" }}>
          <table className="data">
            <thead><tr><th>Feature</th><th className="num">Imported value</th><th className="num">Model input</th><th className="num">Contribution</th></tr></thead>
            <tbody>{all.map((c) => (
              <tr key={c.feature}><td>{c.feature}</td><td className="num">{num(c.raw_value)}</td><td className="num">{num(c.model_input)}</td><td className="num">{signed(c.contribution, 6)}</td></tr>
            ))}</tbody>
          </table>
        </div>
      )}
    </div>
  );
}
