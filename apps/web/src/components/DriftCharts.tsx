import { useState, type ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { DriftFeatureStat, DriftWindow } from "../api/types";
import { formatNumber } from "../lib/format";

// Categorical slots 1-2 of the validated palette; a single-series chart uses slot 1 only.
const S1 = "var(--series-1)";
const S2 = "var(--series-2)";
const AXIS = { stroke: "var(--axis)", tick: { fill: "var(--text-muted)", fontSize: 11 }, tickLine: false } as const;

interface TipRow { name?: unknown; value?: unknown; color?: string; dataKey?: unknown }
function Tip({ active, payload, title, fmt }: { active?: boolean; payload?: readonly TipRow[]; title: string; fmt: (v: number) => string }) {
  if (!active || !payload?.length) return null;
  return (
    <div className="chart-tooltip">
      <div className="t">{title}</div>
      {payload.map((p) => (
        <div className="r" key={String(p.dataKey)}><span><i style={{ background: p.color }} />{String(p.name)}</span>
          <span className="num">{p.value === null || p.value === undefined ? "—" : fmt(Number(p.value))}</span></div>
      ))}
    </div>
  );
}

function ViewToggle({ view, setView }: { view: string; setView: (v: "chart" | "table") => void }) {
  return (
    <div className="toggle-group" role="group" aria-label="View">
      <button aria-pressed={view === "chart"} onClick={() => setView("chart")}>Chart</button>
      <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
    </div>
  );
}

function Frame({ legend, view, setView, label, chart, table, note }: { legend: ReactNode; view: string; setView: (v: "chart" | "table") => void; label: string; chart: ReactNode; table: ReactNode; note?: ReactNode }) {
  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div className="chart-legend">{legend}</div><ViewToggle view={view} setView={setView} />
      </div>
      {view === "chart" ? <div style={{ width: "100%", height: 260 }} role="img" aria-label={label}><ResponsiveContainer>{chart as React.ReactElement}</ResponsiveContainer></div>
        : <div className="table-wrap" style={{ maxHeight: 260, overflowY: "auto" }}>{table}</div>}
      {note ? <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>{note}</p> : null}
    </div>
  );
}

const winLabel = (w: DriftWindow) => (w.start ? new Date(w.start).toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" }) : `#${w.window_index}`);

/** Largest per-feature PSI and prediction PSI per window, against the configured thresholds. */
export function PsiByWindowChart({ windows, moderate, major, hasPrediction }: { windows: DriftWindow[]; moderate: number; major: number; hasPrediction: boolean }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const FLOOR = 0.001; // log scale: values below the floor (incl. 0) are drawn at the floor
  const clamp = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.max(FLOOR, v));
  const data = windows.map((w) => ({
    label: winLabel(w), idx: w.window_index, n: w.n_events, drifted: w.drifted_features.length,
    feature: clamp(w.max_feature_psi), prediction: clamp(w.prediction?.psi), rawFeature: w.max_feature_psi, rawPrediction: w.prediction?.psi ?? null,
  }));
  const top = Math.max(1, ...data.map((d) => Math.max(d.feature ?? 0, d.prediction ?? 0)));
  const ticks = [0.001, 0.01, 0.1, 1, 10, 100].filter((t) => t <= top * 10);
  return (
    <Frame view={view} setView={setView}
      label={`Population stability index per window: largest feature PSI${hasPrediction ? " and prediction PSI" : ""}, ${data.length} windows. Use the table view for values.`}
      legend={<>
        <span><i style={{ background: S1 }} />Largest feature PSI</span>
        {hasPrediction ? <span><i style={{ background: S2 }} />Prediction (class-mix) PSI</span> : null}
        <span className="muted">Thresholds: moderate {moderate}, major {major}</span>
      </>}
      chart={
        <LineChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="label" {...AXIS} minTickGap={30} />
          <YAxis {...AXIS} axisLine={false} width={48} scale="log" domain={[FLOOR, ticks[ticks.length - 1]]} ticks={ticks}
            allowDataOverflow tickFormatter={(v) => String(v)} />
          <ReferenceLine y={moderate} stroke="var(--text-muted)" strokeDasharray="4 4" label={{ value: `moderate ${moderate}`, position: "insideBottomRight", fill: "var(--text-muted)", fontSize: 11 }} />
          <ReferenceLine y={major} stroke="var(--text-secondary)" strokeDasharray="4 4" label={{ value: `major ${major}`, position: "insideTopLeft", fill: "var(--text-secondary)", fontSize: 11 }} />
          <Tooltip content={(p) => <Tip active={p.active} payload={p.payload as readonly TipRow[]} title={String(p.label)} fmt={(v) => (v <= FLOOR ? `< ${FLOOR}` : v.toFixed(3))} />} />
          <Line type="linear" dataKey="feature" name="Largest feature PSI" stroke={S1} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)", fill: S1 }} isAnimationActive={false} />
          {hasPrediction ? <Line type="linear" dataKey="prediction" name="Prediction PSI" stroke={S2} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)", fill: S2 }} isAnimationActive={false} /> : null}
        </LineChart>}
      table={
        <table className="data"><thead><tr><th>Window</th><th>Start</th><th className="num">Events</th><th className="num">Largest feature PSI</th>{hasPrediction ? <th className="num">Prediction PSI</th> : null}<th className="num">Features drifted</th></tr></thead>
          <tbody>{data.map((d) => <tr key={d.idx}><td>#{d.idx}</td><td>{d.label}</td><td className="num">{formatNumber(d.n)}</td><td className="num">{d.rawFeature?.toFixed(3) ?? "—"}</td>{hasPrediction ? <td className="num">{d.rawPrediction?.toFixed(3) ?? "—"}</td> : null}<td className="num">{d.drifted}</td></tr>)}</tbody></table>}
      note="Logarithmic scale (values below 0.001, including 0, are drawn at 0.001). PSI compares each window with the reference sample using reference-quantile bins; a window is only judged when it has enough events and the change is statistically significant." />
  );
}

/** Error rate per window, measured against labels supplied with the imported data. */
export function ErrorRateChart({ windows, referenceRate }: { windows: DriftWindow[]; referenceRate: number | null }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const data = windows.map((w) => ({ label: winLabel(w), idx: w.window_index, rate: w.performance?.error_rate ?? null, n: w.performance?.n_labelled ?? 0 }));
  return (
    <Frame view={view} setView={setView} label={`Error rate per window against dataset labels, ${data.length} windows.`}
      legend={<><span><i style={{ background: S1 }} />Error rate (current windows)</span>{referenceRate !== null ? <span className="muted">Reference error rate {(referenceRate * 100).toFixed(1)}%</span> : null}</>}
      chart={
        <LineChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 4 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="label" {...AXIS} minTickGap={30} />
          <YAxis {...AXIS} axisLine={false} width={52} tickFormatter={(v: number) => `${(v * 100).toFixed(v > 0 && v < 0.01 ? 2 : v < 0.1 ? 1 : 0)}%`} />
          {referenceRate !== null ? <ReferenceLine y={referenceRate} stroke="var(--text-muted)" strokeDasharray="4 4" label={{ value: "reference", position: "insideTopRight", fill: "var(--text-muted)", fontSize: 11 }} /> : null}
          <Tooltip content={(p) => <Tip active={p.active} payload={p.payload as readonly TipRow[]} title={String(p.label)} fmt={(v) => `${(v * 100).toFixed(2)}%`} />} />
          <Line type="linear" dataKey="rate" name="Error rate" stroke={S1} strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--surface-1)", fill: S1 }} isAnimationActive={false} />
        </LineChart>}
      table={<table className="data"><thead><tr><th>Window</th><th>Start</th><th className="num">Labelled events</th><th className="num">Error rate</th></tr></thead>
        <tbody>{data.map((d) => <tr key={d.idx}><td>#{d.idx}</td><td>{d.label}</td><td className="num">{formatNumber(d.n)}</td><td className="num">{d.rate === null ? "—" : `${(d.rate * 100).toFixed(2)}%`}</td></tr>)}</tbody></table>}
      note="Uses labels that came with the imported files, not analyst-confirmed outcomes." />
  );
}

function binLabels(edges: number[]): string[] {
  const f = (v: number) => (Math.abs(v) >= 1000 ? v.toExponential(1) : Number(v.toPrecision(3)).toString());
  if (!edges.length) return ["all values"];
  return [`≤ ${f(edges[0])}`, ...edges.slice(1).map((e, i) => `${f(edges[i])}–${f(e)}`), `> ${f(edges[edges.length - 1])}`];
}

/** Reference vs current share of observations per reference-quantile bin for one feature. */
export function DistributionChart({ feature, stat }: { feature: string; stat: DriftFeatureStat }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  if (!stat.bins) return <p className="muted">No distribution available for {feature}.</p>;
  const labels = binLabels(stat.bins.edges);
  const data = labels.map((l, i) => ({ bin: l, reference: stat.bins!.ref[i], current: stat.bins!.cur[i] }));
  return (
    <Frame view={view} setView={setView} label={`Distribution of ${feature}: share of reference and current observations per bin.`}
      legend={<><span><i style={{ background: S1 }} />Reference</span><span><i style={{ background: S2 }} />Current</span></>}
      chart={
        <BarChart data={data} margin={{ top: 10, right: 16, left: 0, bottom: 4 }} barGap={2} barCategoryGap="20%">
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="bin" {...AXIS} interval={0} angle={data.length > 6 ? -25 : 0} textAnchor={data.length > 6 ? "end" : "middle"} height={data.length > 6 ? 56 : 30} />
          <YAxis {...AXIS} axisLine={false} width={44} tickFormatter={(v) => `${Math.round(v * 100)}%`} />
          <Tooltip cursor={{ fill: "var(--surface-2)" }} content={(p) => <Tip active={p.active} payload={p.payload as readonly TipRow[]} title={String(p.label)} fmt={(v) => `${(v * 100).toFixed(1)}%`} />} />
          <Bar dataKey="reference" name="Reference" fill={S1} radius={[4, 4, 0, 0]} isAnimationActive={false} />
          <Bar dataKey="current" name="Current" fill={S2} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        </BarChart>}
      table={<table className="data"><thead><tr><th>Bin</th><th className="num">Reference</th><th className="num">Current</th></tr></thead>
        <tbody>{data.map((d) => <tr key={d.bin}><td className="mono">{d.bin}</td><td className="num">{(d.reference * 100).toFixed(1)}%</td><td className="num">{(d.current * 100).toFixed(1)}%</td></tr>)}</tbody></table>}
      note="Bins are reference quantiles, so each reference bar is roughly equal for continuous features; discrete features have fewer bins." />
  );
}
