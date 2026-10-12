import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, downloadFile } from "../api/client";
import { Can, ReadOnlyNote } from "../components/Can";
import type { Disposition, IncidentDetail } from "../api/types";
import { useApi } from "../api/useApi";
import { DispositionBadge, PlainBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { Icon } from "../components/Icon";
import { PageHeader } from "../components/PageHeader";
import { Banner, ErrorState, Loading, Time } from "../components/States";
import { humanize } from "../lib/format";
import { AlertsTable, useUserMap } from "./Alerts";

const DISPOSITIONS: Disposition[] = ["confirmed_attack", "benign", "false_positive", "inconclusive", "undetermined"];

export function IncidentDetailPage() {
  const { id } = useParams();
  const users = useUserMap();
  const { data, error, loading, reload } = useApi(() => api.get<IncidentDetail>(`/incidents/${id}`), [id]);
  const [note, setNote] = useState("");
  const [kind, setKind] = useState<"note" | "evidence">("note");
  const [disp, setDisp] = useState<Disposition | null>(null);
  const [closing, setClosing] = useState(false);
  const [msg, setMsg] = useState<string>();
  const [err, setErr] = useState<string>();
  if (error) return <ErrorState error={error} onRetry={reload} />;
  if (!data) return <Loading />;
  const inc = data.incident;
  const act = async (fn: () => Promise<unknown>, done: string) => {
    setErr(undefined);
    try { await fn(); setMsg(done); reload(); } catch (x) { setErr((x as Error).message); }
  };

  return (
    <>
      <PageHeader title={`Incident #${inc.id}: ${inc.title}`}
        actions={<>
          <Can perm="data.export"><button className="btn" onClick={() => void downloadFile(`/incidents/${inc.id}/export.md`, `incident-${inc.id}.md`)}><Icon name="download" size={16} />Export summary</button></Can>
          <Link className="btn" to="/incidents">Back</Link>
        </>} />
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      {err ? <Banner kind="error">{err}</Banner> : null}
      <div className={loading ? "refetching grid grid-2" : "grid grid-2"}>
        <section className="card" aria-labelledby="dec-h">
          <div className="card-header"><h2 id="dec-h">Status and decision</h2></div>
          <dl className="kv">
            <dt>Status</dt><dd><PlainBadge>{humanize(inc.status)}</PlainBadge></dd>
            <dt>Disposition</dt><dd><DispositionBadge disposition={inc.disposition} /> <span className="muted">analyst decision</span></dd>
            <dt>Owner</dt><dd>{data.owner ?? "—"}</dd>
            <dt>Created</dt><dd><Time iso={inc.created_at} /></dd>
            <dt>Updated</dt><dd><Time iso={inc.updated_at} /></dd>
            {inc.closed_at ? <><dt>Closed</dt><dd><Time iso={inc.closed_at} /></dd></> : null}
            <dt>Sources</dt><dd className="mono">{data.sources.join(", ") || "—"}</dd>
            <dt>Destinations</dt><dd className="mono">{data.destinations.join(", ") || "—"}</dd>
          </dl>
          <Can perm="incidents.write" fallback={<ReadOnlyNote what="change incidents" />}><div className="row" style={{ marginTop: 14 }}>
            <label className="field">Owner
              <select value={inc.owner_id ?? ""} onChange={(e) => void act(() => api.patch(`/incidents/${inc.id}`, { owner_id: e.target.value ? Number(e.target.value) : null }), "Owner updated.")}>
                <option value="">Unassigned</option>
                {[...users.entries()].map(([uid, name]) => <option key={uid} value={uid}>{name}</option>)}
              </select>
            </label>
            <label className="field">Record a decision
              <select value="" onChange={(e) => setDisp(e.target.value as Disposition)}>
                <option value="" disabled>Choose disposition…</option>
                {DISPOSITIONS.filter((d) => d !== inc.disposition).map((d) => <option key={d} value={d}>{humanize(d)}</option>)}
              </select>
            </label>
          </div>
          <div className="row" style={{ marginTop: 10 }}>
            {inc.status === "open" ? <button className="btn" onClick={() => void act(() => api.patch(`/incidents/${inc.id}`, { status: "investigating" }), "Incident is being investigated.")}>Start investigating</button> : null}
            {inc.status !== "closed" ? <button className="btn" onClick={() => setClosing(true)} disabled={inc.disposition === "undetermined"}
              title={inc.disposition === "undetermined" ? "Record a disposition before closing" : undefined}>Close incident</button>
              : <button className="btn" onClick={() => void act(() => api.patch(`/incidents/${inc.id}`, { status: "investigating" }), "Incident re-opened.")}>Re-open</button>}
          </div></Can>
          {inc.summary ? <><h3 style={{ marginTop: 16 }}>Summary</h3><p style={{ whiteSpace: "pre-wrap" }}>{inc.summary}</p></> : null}
        </section>

        <section className="card" aria-labelledby="tl-h">
          <div className="card-header"><h2 id="tl-h">Timeline</h2><span className="hint">events, analyst actions, evidence and decisions</span></div>
          {data.timeline.length ? (
            <ul className="timeline">
              {data.timeline.map((t, i) => (
                <li key={i}><div className="when"><Time iso={t.at} /> · {humanize(t.kind)}{t.actor ? ` · ${t.actor}` : ""}</div><span style={{ whiteSpace: "pre-wrap" }}>{t.text}</span></li>
              ))}
            </ul>
          ) : <p className="muted">Nothing recorded yet.</p>}
          <Can perm="incidents.write"><form style={{ marginTop: 12 }} onSubmit={(e) => { e.preventDefault(); if (note.trim()) void act(() => api.post(`/incidents/${inc.id}/notes`, { body: note, kind }), "Added.").then(() => setNote("")); }}>
            <div className="row">
              <label className="field">Type
                <select value={kind} onChange={(e) => setKind(e.target.value as "note" | "evidence")}><option value="note">Note</option><option value="evidence">Evidence reference</option></select>
              </label>
            </div>
            <label className="field" style={{ marginTop: 8 }}>Text<textarea value={note} onChange={(e) => setNote(e.target.value)} maxLength={10000} /></label>
            <button className="btn" style={{ marginTop: 8 }} disabled={!note.trim()}>Add</button>
          </form></Can>
        </section>
      </div>

      <section className="card" style={{ marginTop: 16 }} aria-labelledby="al-h">
        <div className="card-header"><h2 id="al-h">Linked alerts</h2><span className="hint">automated model output</span>
          <Link className="right" to="/alerts?status=new&status=investigating">Find more alerts</Link></div>
        {data.alerts.length ? <AlertsTable alerts={data.alerts} users={users} /> : <p className="muted">No alerts linked.</p>}
      </section>

      {disp ? (
        <ConfirmDialog title={`Record disposition: ${humanize(disp)}`} confirmLabel="Record decision" reasonLabel="Decision note" reasonRequired
          onCancel={() => setDisp(null)}
          onConfirm={async (reason) => {
            await api.patch(`/incidents/${inc.id}`, { disposition: disp, decision_note: reason });
            setDisp(null); setMsg("Decision recorded."); reload();
          }}>
          {disp === "confirmed_attack" ? "This counts the incident as a confirmed attack on the dashboard." : "This is recorded in the incident timeline."}
        </ConfirmDialog>
      ) : null}
      {closing ? (
        <ConfirmDialog title="Close incident" confirmLabel="Close incident" onCancel={() => setClosing(false)}
          onConfirm={async () => { await api.patch(`/incidents/${inc.id}`, { status: "closed" }); setClosing(false); setMsg("Incident closed."); reload(); }}>
          Disposition: {humanize(inc.disposition)}. No blocking or remediation is performed by the system.
        </ConfirmDialog>
      ) : null}
    </>
  );
}
