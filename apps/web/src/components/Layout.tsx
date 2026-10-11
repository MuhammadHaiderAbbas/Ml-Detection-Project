import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import { api } from "../api/client";
import type { Health, Page, Alert } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { Icon, type IconName } from "./Icon";

export const NAV: { to: string; label: string; icon: IconName; phase?: string; adminOnly?: boolean }[] = [
  { to: "/", label: "Dashboard", icon: "dashboard" },
  { to: "/traffic", label: "Live Traffic", icon: "traffic" },
  { to: "/alerts", label: "Alerts", icon: "alert" },
  { to: "/incidents", label: "Incidents", icon: "incident" },
  { to: "/drift", label: "Drift Monitor", icon: "drift", phase: "Phase 5" },
  { to: "/models", label: "Model Management", icon: "model" },
  { to: "/investigations", label: "Investigations", icon: "search" },
  { to: "/reports", label: "Reports", icon: "report" },
  { to: "/data-sources", label: "Data Sources", icon: "database" },
  { to: "/experiments", label: "Experiments", icon: "flask" },
  { to: "/audit", label: "Audit Logs", icon: "audit", adminOnly: true },
  { to: "/settings", label: "Settings", icon: "settings" },
];

type Theme = "system" | "light" | "dark";
function readTheme(): Theme {
  try { return (localStorage.getItem("adaptive-ids.theme") as Theme) || "system"; } catch { return "system"; }
}
function applyTheme(t: Theme) {
  if (t === "system") document.documentElement.removeAttribute("data-theme");
  else document.documentElement.setAttribute("data-theme", t);
  try { localStorage.setItem("adaptive-ids.theme", t); } catch { /* storage unavailable */ }
}

function ConnectionStatus() {
  const { data, error } = useApi(() => api.get<Health>("/health"), [], { pollMs: 15000 });
  const ok = data?.status === "ok" && !error;
  const label = error ? "API unreachable" : !data ? "Connecting…" : ok ? "Connected" : "Database unavailable";
  return (
    <span className="conn" role="status" aria-live="polite" title={data ? `API v${data.version}, database ${data.database}` : undefined}>
      <span className="dot" style={{ background: ok ? "var(--status-good)" : error ? "var(--status-critical)" : "var(--status-warning)" }} />
      <Icon name={ok ? "check" : error ? "x" : "clock"} size={14} />
      {label}
    </span>
  );
}

function Notifications() {
  const { data } = useApi(() => api.get<Page<Alert>>("/alerts", { status: "new", limit: 1 }), [], { pollMs: 30000 });
  const n = data?.total ?? 0;
  return (
    <Link to="/alerts?status=new" className="btn ghost" aria-label={`${n} new alerts awaiting triage`} title="New alerts awaiting triage">
      <Icon name="bell" size={16} />
      <span className="num">{n.toLocaleString()}</span>
      <span className="sr-only">new alerts</span>
    </Link>
  );
}

function AccountMenu() {
  const { user, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const [theme, setTheme] = useState<Theme>(readTheme);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { applyTheme(theme); }, [theme]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", esc); };
  }, [open]);
  if (!user) return null;
  return (
    <div className="account" ref={ref}>
      <button className="btn ghost" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name="user" size={16} /> {user.username}
      </button>
      {open ? (
        <div className="account-menu" role="menu">
          <div className="who"><strong>{user.username}</strong><div className="muted">Role: {user.role}</div></div>
          <div className="row" style={{ padding: "4px 10px" }} role="group" aria-label="Theme">
            <span className="muted">Theme</span>
            <div className="toggle-group">
              {(["system", "light", "dark"] as Theme[]).map((t) => (
                <button key={t} aria-pressed={theme === t} onClick={() => setTheme(t)}>{t[0].toUpperCase() + t.slice(1)}</button>
              ))}
            </div>
          </div>
          <Link role="menuitem" to="/settings" onClick={() => setOpen(false)}>Settings</Link>
          <button role="menuitem" onClick={() => void logout()}>Sign out</button>
        </div>
      ) : null}
    </div>
  );
}

export function Layout() {
  const { user } = useAuth();
  const [navOpen, setNavOpen] = useState(false);
  const location = useLocation();
  useEffect(() => { setNavOpen(false); }, [location.pathname]);
  useEffect(() => { applyTheme(readTheme()); }, []);
  return (
    <div className="shell">
      <a className="skip-link" href="#main">Skip to content</a>
      <aside className={`sidebar${navOpen ? " open" : ""}`} aria-label="Primary">
        <div className="brand"><img src="/favicon.svg" alt="" /> Adaptive IDS</div>
        <nav>
          <ul className="nav">
            {NAV.filter((n) => !n.adminOnly || user?.role === "admin").map((n) => (
              <li key={n.to}>
                <NavLink to={n.to} end={n.to === "/"}>
                  <Icon name={n.icon} className="nav-icon" />
                  {n.label}
                  {n.phase ? <span className="soon">{n.phase}</span> : null}
                </NavLink>
              </li>
            ))}
          </ul>
        </nav>
      </aside>
      <div className="main">
        <header className="topbar">
          <button className="btn ghost menu-toggle" aria-label="Open navigation" aria-expanded={navOpen} onClick={() => setNavOpen((o) => !o)}>
            <Icon name="menu" />
          </button>
          <ConnectionStatus />
          <div className="spacer" />
          <Notifications />
          <AccountMenu />
        </header>
        <main id="main" className="content" tabIndex={-1}>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
