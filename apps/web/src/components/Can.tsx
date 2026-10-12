import type { ReactNode } from "react";
import { useAuth } from "../auth/AuthContext";

/**
 * Renders children only when the signed-in user's role grants `perm`. This is a usability
 * hint: the API enforces every permission itself (src/adaptive_ids/permissions.py).
 */
export function Can({ perm, children, fallback = null }: { perm: string; children: ReactNode; fallback?: ReactNode }) {
  const { can } = useAuth();
  return <>{can(perm) ? children : fallback}</>;
}

export const ReadOnlyNote = ({ what }: { what: string }) => <p className="muted" style={{ margin: "8px 0 0", fontSize: 12.5 }}>Read-only access: your role cannot {what}.</p>;
