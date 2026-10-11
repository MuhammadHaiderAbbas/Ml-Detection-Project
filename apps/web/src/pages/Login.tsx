import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function LoginPage() {
  const { user, login } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  if (user) return <Navigate to={from} replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!username || !password) { setError("Enter your username and password."); return; }
    setBusy(true);
    setError(undefined);
    try { await login(username, password); navigate(from, { replace: true }); }
    catch (err) { setError((err as Error).message); setBusy(false); }
  };

  return (
    <div className="login-wrap">
      <form className="card login-card stack" onSubmit={submit} noValidate>
        <div className="row"><img src="/favicon.svg" alt="" width={28} height={28} /><h1>Adaptive IDS</h1></div>
        <p className="secondary" style={{ margin: 0 }}>Sign in to review network activity, alerts and model health.</p>
        <label className="field">Username
          <input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus />
        </label>
        <label className="field">Password
          <input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error ? <p className="field-error" role="alert">{error}</p> : null}
        <button className="btn primary" type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="muted" style={{ margin: 0, fontSize: 12.5 }}>
          No account yet? An administrator creates one with <code>adaptive-ids create-user</code>.
        </p>
      </form>
    </div>
  );
}
