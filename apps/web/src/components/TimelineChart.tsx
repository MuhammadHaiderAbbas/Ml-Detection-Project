import { useMemo, useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Timeline } from "../api/types";
import { formatNumber } from "../lib/format";

// Two categorical series in fixed order (validated reference palette slots 1 and 2); a third slot
// (aqua) is added only when some events have no prediction. Colour follows the series, never the rank.
const SERIES = [
  { key: "not_flagged", label: "Not flagged", color: "var(--series-1)" },
  { key: "suspicious", label: "Suspicious", color: "var(--series-2)" },
  { key: "unscored", label: "Not scored", color: "var(--series-3, #1baf7a)" },
] as const;

function tickLabel(iso: string, bucket: string): string {
  const d = new Date(iso);
  if (bucket === "day") return d.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
  return d.toLocaleString(undefined, { month: "short", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

interface TipProps {
  active?: boolean;
  payload?: readonly { dataKey?: unknown; name?: unknown; value?: unknown; color?: string }[];
  label?: unknown;
  bucket: string;
}

function ChartTooltip({ active, payload, label, bucket }: TipProps) {
  if (!active || !payload?.length) return null;
  const total = payload.reduce((s, p) => s + (Number(p.value) || 0), 0);
  return (
    <div className="chart-tooltip">
      <div className="t">{tickLabel(String(label), bucket)}</div>
      {[...payload].reverse().map((p) => (
        <div className="r" key={String(p.dataKey)}>
          <span><i style={{ background: p.color }} />{String(p.name)}</span><span className="num">{formatNumber(Number(p.value))}</span>
        </div>
      ))}
      <div className="r" style={{ borderTop: "1px solid var(--border)", marginTop: 4, paddingTop: 4 }}>
        <span>Total events</span><span className="num">{formatNumber(total)}</span>
      </div>
    </div>
  );
}

export function TimelineChart({ data }: { data: Timeline }) {
  const [view, setView] = useState<"chart" | "table">("chart");
  const series = useMemo(() => SERIES.filter((s) => s.key !== "unscored" || data.points.some((p) => p.unscored > 0)), [data]);
  const top = series[series.length - 1].key;

  return (
    <div>
      <div className="row" style={{ justifyContent: "space-between", marginBottom: 8 }}>
        <div className="chart-legend" aria-hidden={view === "table"}>
          {series.map((s) => <span key={s.key}><i style={{ background: s.color }} />{s.label}</span>)}
        </div>
        <div className="toggle-group" role="group" aria-label="View">
          <button aria-pressed={view === "chart"} onClick={() => setView("chart")}>Chart</button>
          <button aria-pressed={view === "table"} onClick={() => setView("table")}>Table</button>
        </div>
      </div>
      {view === "chart" ? (
        <div style={{ width: "100%", height: 280 }} role="img"
          aria-label={`Events per ${data.bucket} by model verdict, ${data.points.length} intervals. Use the Table view for exact values.`}>
          <ResponsiveContainer>
            <BarChart data={data.points} margin={{ top: 8, right: 8, left: 0, bottom: 4 }} barCategoryGap={2}>
              <CartesianGrid vertical={false} stroke="var(--grid)" />
              <XAxis dataKey="bucket_start" tickFormatter={(v) => tickLabel(v, data.bucket)} stroke="var(--axis)"
                tick={{ fill: "var(--text-muted)", fontSize: 11 }} tickLine={false} minTickGap={40} />
              <YAxis allowDecimals={false} stroke="var(--axis)" tick={{ fill: "var(--text-muted)", fontSize: 11 }}
                tickLine={false} axisLine={false} width={44} />
              <Tooltip cursor={{ fill: "var(--surface-2)" }} content={(props) => <ChartTooltip active={props.active} payload={props.payload as TipProps["payload"]} label={props.label} bucket={data.bucket} />} />
              {series.map((s) => (
                <Bar key={s.key} dataKey={s.key} name={s.label} stackId="v" fill={s.color} stroke="var(--surface-1)"
                  strokeWidth={1} radius={s.key === top ? [4, 4, 0, 0] : 0} isAnimationActive={false} />
              ))}
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        <div className="table-wrap" style={{ maxHeight: 280, overflowY: "auto" }}>
          <table className="data">
            <thead><tr><th>Interval start</th>{series.map((s) => <th key={s.key} className="num">{s.label}</th>)}<th className="num">Total</th></tr></thead>
            <tbody>
              {data.points.map((p) => (
                <tr key={p.bucket_start}>
                  <td>{tickLabel(p.bucket_start, data.bucket)}</td>
                  {series.map((s) => <td key={s.key} className="num">{formatNumber(p[s.key])}</td>)}
                  <td className="num">{formatNumber(p.events)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted" style={{ fontSize: 12, margin: "8px 0 0" }}>
        Grouped by event time in UTC intervals; labels show your local time. “Suspicious” means the model did not predict the benign class; it is not a confirmed attack.
        {data.events_without_timestamp ? ` ${formatNumber(data.events_without_timestamp)} events without a timestamp are not shown.` : ""}
      </p>
    </div>
  );
}
