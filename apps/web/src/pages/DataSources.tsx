import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { Can, ReadOnlyNote } from "../components/Can";
import { api } from "../api/client";
import type { ImportRecord, Page, Preview, SchemaInfo } from "../api/types";
import { useApi } from "../api/useApi";
import { PlainBadge, ProvenanceBadge } from "../components/Badges";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Pagination } from "../components/Pagination";
import { Banner, Empty, ErrorState, Loading, Time } from "../components/States";
import { useUrlFilters } from "../lib/filters";
import { formatBytes, formatNumber, humanize } from "../lib/format";

const PROVENANCE_CHOICES = [
  ["controlled_experiment", "Controlled experiment (public research data)"],
  ["baseline_reproduction", "Baseline reproduction"],
  ["live_observation", "Live observation (authorised traffic)"],
  ["synthetic_demo", "Synthetic demo"],
] as const;

function UploadForm() {
  const navigate = useNavigate();
  const schemas = useApi(() => api.get<SchemaInfo[]>("/schemas"), []);
  const [file, setFile] = useState<File | null>(null);
  const [schemaId, setSchemaId] = useState("");
  const [name, setName] = useState("");
  const [version, setVersion] = useState("");
  const [provenance, setProvenance] = useState("");
  const [source, setSource] = useState("");
  const [mapping, setMapping] = useState("");
  const [dupes, setDupes] = useState("keep");
  const [preview, setPreview] = useState<Preview>();
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  const form = () => {
    const fd = new FormData();
    if (file) fd.append("file", file);
    fd.append("schema_id", schemaId);
    if (mapping.trim()) fd.append("column_mapping", mapping.trim());
    return fd;
  };
  const doPreview = async () => {
    setError(undefined); setPreview(undefined);
    if (!file || !schemaId) { setError("Choose a CSV file and a schema first."); return; }
    setBusy(true);
    try { setPreview(await api.upload<Preview>("/imports/preview", form())); } catch (x) { setError((x as Error).message); }
    setBusy(false);
  };
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setError(undefined);
    const missing = [!file && "file", !schemaId && "schema", !name.trim() && "dataset name", !version.trim() && "dataset version", !provenance && "provenance"].filter(Boolean);
    if (missing.length) { setError(`Please provide: ${missing.join(", ")}.`); return; }
    const fd = form();
    fd.append("dataset_name", name.trim()); fd.append("dataset_version", version.trim());
    fd.append("provenance", provenance); fd.append("duplicate_policy", dupes);
    if (source.trim()) fd.append("data_source", source.trim());
    setBusy(true);
    try { const rec = await api.upload<ImportRecord>("/imports", fd); navigate(`/data-sources/${rec.id}`); }
    catch (x) { setError((x as Error).message); setBusy(false); }
  };
  const schema = schemas.data?.find((s) => s.schema_id === schemaId);

  return (
    <form className="card stack" onSubmit={submit} aria-labelledby="up-h" noValidate>
      <div className="card-header" style={{ marginBottom: 0 }}><h2 id="up-h">Import a CSV file</h2><span className="hint">validated against a feature schema; rejected rows are reported, never silently fixed</span></div>
      <div className="grid grid-3">
        <label className="field">CSV file<input type="file" accept=".csv,text/csv" onChange={(e) => { setFile(e.target.files?.[0] ?? null); setPreview(undefined); }} /></label>
        <label className="field">Feature schema
          <select value={schemaId} onChange={(e) => { setSchemaId(e.target.value); setPreview(undefined); }}>
            <option value="">Choose…</option>
            {schemas.data?.map((s) => <option key={s.schema_id} value={s.schema_id}>{s.schema_id} ({s.status})</option>)}
          </select>
        </label>
        <label className="field">Provenance
          <select value={provenance} onChange={(e) => setProvenance(e.target.value)}>
            <option value="">Choose…</option>
            {PROVENANCE_CHOICES.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="field">Dataset name<input value={name} onChange={(e) => setName(e.target.value)} maxLength={200} /></label>
        <label className="field">Dataset version<input value={version} onChange={(e) => setVersion(e.target.value)} maxLength={100} /></label>
        <label className="field">Data source label (optional)<input value={source} onChange={(e) => setSource(e.target.value)} maxLength={200} /></label>
        <label className="field">Duplicate rows
          <select value={dupes} onChange={(e) => setDupes(e.target.value)}><option value="keep">Keep and count</option><option value="drop">Drop repeats</option></select>
        </label>
        <label className="field" style={{ gridColumn: "span 2" }}>Column mapping (optional JSON: {"{"}"file column": "schema column"{"}"})
          <input value={mapping} onChange={(e) => setMapping(e.target.value)} className="mono" placeholder='{"Destination Port": "Dst Port"}' />
        </label>
      </div>
      {schema && schema.status !== "verified" ? <Banner kind="info">Schema <code>{schema.schema_id}</code> is <strong>{schema.status}</strong>: it has not been confirmed against the original research pipeline.</Banner> : null}
      {error ? <Banner kind="error">{error}</Banner> : null}
      {preview ? (
        <div>
          {preview.compatibility.missing.length ? <Banner kind="error">Missing required columns: <code>{preview.compatibility.missing.join(", ")}</code>. Fix the file or the column mapping.</Banner>
            : <Banner kind="success">All schema columns found.{preview.compatibility.extra.length ? ` ${preview.compatibility.extra.length} extra column(s) will be ignored.` : ""}</Banner>}
          <div className="table-wrap" style={{ maxHeight: 260, overflow: "auto" }}>
            <table className="data">
              <thead><tr>{preview.columns.map((c) => <th key={c}>{c}</th>)}</tr></thead>
              <tbody>{preview.rows.map((r, i) => <tr key={i}>{preview.columns.map((c) => <td key={c} className="mono">{r[c]}</td>)}</tr>)}</tbody>
            </table>
          </div>
        </div>
      ) : null}
      <div className="row">
        <button type="button" className="btn" onClick={() => void doPreview()} disabled={busy}>Preview</button>
        <button className="btn primary" disabled={busy}><Icon name="upload" size={16} />Import</button>
      </div>
    </form>
  );
}

export function DataSourcesPage() {
  const f = useUrlFilters();
  const limit = 25;
  const offset = Number(f.get("offset") || 0);
  const list = useApi(() => api.get<Page<ImportRecord>>("/imports", { limit, offset }), [offset], { pollMs: 10000 });
  return (
    <>
      <PageHeader title="Data Sources" description="Imported datasets with their file hash, schema, validation summary and processing status. Live telemetry (Zeek, NetFlow) is a later integration." />
      <Can perm="data.import" fallback={<div className="card"><ReadOnlyNote what="import data" /></div>}><UploadForm /></Can>
      <section className="card" aria-labelledby="imp-h">
        <div className="card-header"><h2 id="imp-h">Imports</h2></div>
        {list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : list.data ? (list.data.items.length ? (
          <>
            <div className="table-wrap">
              <table className="data">
                <thead><tr><th>Import</th><th>Dataset</th><th>Provenance</th><th>Status</th><th className="num">Rows</th><th className="num">Accepted</th><th className="num">Rejected</th><th className="num">Size</th><th>Created</th></tr></thead>
                <tbody>{list.data.items.map((i) => (
                  <tr key={i.id}>
                    <td><Link to={`/data-sources/${i.id}`}>#{i.id}</Link></td><td>{i.dataset_name}@{i.dataset_version}<div className="muted">{i.original_filename}</div></td>
                    <td><ProvenanceBadge provenance={i.provenance} /></td><td><PlainBadge>{humanize(i.status)}</PlainBadge></td>
                    <td className="num">{formatNumber(i.total_rows)}</td><td className="num">{formatNumber(i.accepted_rows)}</td><td className="num">{formatNumber(i.rejected_rows)}</td>
                    <td className="num">{formatBytes(i.file_bytes)}</td><td><Time compact iso={i.created_at} /></td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
            <Pagination total={list.data.total} limit={limit} offset={offset} onChange={(o) => f.set({ offset: String(o) })} />
          </>
        ) : <Empty title="No imports yet">Import a CSV above, or run <code>adaptive-ids demo</code> for clearly labelled synthetic data.</Empty>) : <Loading />}
      </section>
    </>
  );
}
