import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { tokenStore } from "../api/client";
import { AuthProvider } from "../auth/AuthContext";
import { Can, ReadOnlyNote } from "../components/Can";

const viewer = { id: 3, username: "viv", role: "viewer", is_active: true, created_at: "2026-01-01T00:00:00Z", last_login_at: null,
  permissions: ["alerts.read", "dashboard.read"] };

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("permission gating", () => {
  it("hides controls the server says the role cannot use", async () => {
    tokenStore.set("t");
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify(viewer), { status: 200, headers: { "Content-Type": "application/json" } }));
    render(<AuthProvider>
      <Can perm="alerts.read"><span>visible list</span></Can>
      <Can perm="alerts.write" fallback={<ReadOnlyNote what="change alerts" />}><button>Resolve</button></Can>
    </AuthProvider>);
    expect(await screen.findByText("visible list")).toBeTruthy();
    expect(screen.getByText(/Read-only access: your role cannot change alerts/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Resolve" })).toBeNull();
  });
});
