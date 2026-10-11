import { useState, type FormEvent } from "react";
import { api } from "../api/client";
import type { SeverityRules, User } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { SeverityBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { PageHeader } from "../components/PageHeader";
import { Banner, Loading, Time } from "../components/States";

function Users() {
  const { user: me } = useAuth();
  const users = useApi(() => api.get<User[]>("/users"), []);
  const [form, setForm] = useState({ username: "", password: "", role: "analyst" });
  const [msg, setMsg] = useState<string>();
  const [err, setErr] = useState<string>();
  const [toggle, setToggle] = useState<User | null>(null);
  const submit = async (e: FormEvent) => {
    e.preventDefault(); setErr(undefined);
    if (form.password.length < 12) { setErr("Passwords must be at least 12 characters."); return; }
    try { await api.post("/users", form); setMsg(`User ${form.username} created.`); setForm({ username: "", password: "", role: "analyst" }); users.reload(); }
    catch (x) { setErr((x as Error).message); }
  };
  return (
    <section className="card" aria-labelledby="u-h">
      <div className="card-header"><h2 id="u-h">Users</h2><span className="hint">admin only</span></div>
      {msg ? <Banner kind="success">{msg}</Banner> : null}
      {err ? <Banner kind="error">{err}</Banner> : null}
      {users.data ? (
        <table className="data">
          <thead><tr><th>User</th><th>Role</th><th>Status</th><th>Last sign-in</th><th></th></tr></thead>
          <tbody>{users.data.map((u) => (
            <tr key={u.id}><td>{u.username}</td><td>{u.role}</td><td>{u.is_active ? "Active" : "Deactivated"}</td><td><Time compact iso={u.last_login_at} /></td>
              <td>{u.id !== me?.id ? <button className="btn small" onClick={() => setToggle(u)}>{u.is_active ? "Deactivate" : "Reactivate"}</button> : <span className="muted">You</span>}</td></tr>
          ))}</tbody>
        </table>
      ) : <Loading />}
      <form className="filters" style={{ marginTop: 14 }} onSubmit={submit}>
        <label className="field">Username<input value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} autoComplete="off" /></label>
        <label className="field">Initial password (min 12)<input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} autoComplete="new-password" /></label>
        <label className="field">Role<select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}><option value="analyst">Analyst</option><option value="admin">Admin</option></select></label>
        <button className="btn primary">Create user</button>
      </form>
      {toggle ? (
        <ConfirmDialog title={`${toggle.is_active ? "Deactivate" : "Reactivate"} ${toggle.username}`} confirmLabel={toggle.is_active ? "Deactivate" : "Reactivate"}
          danger={toggle.is_active} onCancel={() => setToggle(null)}
          onConfirm={async () => { await api.patch(`/users/${toggle.id}`, { is_active: !toggle.is_active }); setToggle(null); users.reload(); }}>
          {toggle.is_active ? "Their active sessions are revoked immediately." : "They will be able to sign in again."}
        </ConfirmDialog>
      ) : null}
    </section>
  );
}

export function SettingsPage() {
  const { user } = useAuth();
  const rules = useApi(() => api.get<SeverityRules>("/severity-rules"), []);
  return (
    <>
      <PageHeader title="Settings" />
      <div className="stack">
        <section className="card" aria-labelledby="acct-h">
          <div className="card-header"><h2 id="acct-h">Your account</h2></div>
          <dl className="kv"><dt>Username</dt><dd>{user?.username}</dd><dt>Role</dt><dd>{user?.role}</dd><dt>Last sign-in</dt><dd><Time iso={user?.last_login_at} /></dd>
            <dt>Times shown in</dt><dd>{Intl.DateTimeFormat().resolvedOptions().timeZone} (hover any time to see UTC)</dd></dl>
        </section>
        <section className="card" aria-labelledby="sev-h">
          <div className="card-header"><h2 id="sev-h">Severity rules</h2><span className="hint">configured on the server in configs/severity-rules.json</span></div>
          {rules.data ? (
            <>
              <p className="secondary">{rules.data.description}</p>
              <table className="data">
                <thead><tr><th>Order</th><th>Rule</th><th>Predicted class matches</th><th className="num">Min score</th><th>Severity</th></tr></thead>
                <tbody>
                  {rules.data.rules.map((r, i) => <tr key={r.rule_id}><td className="num">{i + 1}</td><td className="mono">{r.rule_id}</td><td className="mono">{r.classes.join(", ")}</td><td className="num">{r.min_score ?? "—"}</td><td><SeverityBadge severity={r.severity} /></td></tr>)}
                  <tr><td className="num">—</td><td className="mono">{rules.data.default.rule_id}</td><td className="muted">otherwise</td><td /><td><SeverityBadge severity={rules.data.default.severity} /></td></tr>
                </tbody>
              </table>
              <p className="muted" style={{ fontSize: 12 }}>Version {rules.data.version}. First matching rule wins; each alert stores the rule and version that set its severity.</p>
            </>
          ) : <Loading />}
        </section>
        {user?.role === "admin" ? <Users /> : null}
      </div>
    </>
  );
}
