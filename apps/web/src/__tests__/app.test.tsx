import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import { AuthProvider } from "../auth/AuthContext";

const user = { id: 1, username: "alice", role: "analyst", is_active: true, created_at: "2026-01-01T00:00:00Z", last_login_at: null };
const summary = {
  demo_data_present: true, provenances_present: ["synthetic_demo"], events_processed: 10, events_scored: 10,
  events_rejected_at_inference: 0, suspicious_predictions: 2, alerts_by_status: { new: 2, investigating: 0, resolved: 0, false_positive: 0 },
  alerts_by_severity: { high: 2 }, high_priority_open_alerts: 2, incidents_by_disposition: {}, confirmed_attacks: null,
  confirmed_attacks_note: "Unavailable: no incident has an analyst disposition yet.", active_model: null, last_approved_evaluation: null,
  processing_latency: null, ingestion: { recent: [], failed_in_range: 0 }, drift_monitoring: { status: "not_configured", note: "Phase 5" },
  top_sources: [], top_destinations: [], recent_alert_ids: [], definitions: { events_processed: "rule" },
};

function mockApi(routes: Record<string, unknown>) {
  return vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
    const url = new URL(String(input), "http://localhost");
    const key = Object.keys(routes).find((k) => url.pathname === `/api${k}`);
    if (!key) return new Response(JSON.stringify({ items: [], total: 0, limit: 50, offset: 0 }), { status: 200 });
    const body = routes[key];
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

afterEach(() => { vi.restoreAllMocks(); sessionStorage.clear(); });

describe("app", () => {
  it("redirects to sign-in and shows the server's error for bad credentials", async () => {
    mockApi({ "/auth/login": new Response(JSON.stringify({ detail: "invalid username or password" }), { status: 401 }) });
    render(<MemoryRouter initialEntries={["/alerts"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Username"), "alice");
    await userEvent.type(screen.getByLabelText("Password"), "wrong-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid username or password");
  });

  it("signs in and renders dashboard numbers from the API, marking confirmed attacks unavailable", async () => {
    mockApi({
      "/auth/login": { access_token: "t", user },
      "/dashboard/summary": summary,
      "/dashboard/timeline": { bucket: "hour", basis: "UTC", points: [], events_without_timestamp: 0, definitions: {} },
      "/scoring-runs": [], "/health": { status: "ok", version: "0.1.0", database: "ok" }, "/users": [user], "/models": [],
    });
    render(<MemoryRouter initialEntries={["/"]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
    await userEvent.type(await screen.findByLabelText("Username"), "alice");
    await userEvent.type(screen.getByLabelText("Password"), "correct-password");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("link", { name: /Events processed\s*10/ })).toHaveAttribute("href", "/traffic");
    expect(screen.getByText("Unavailable")).toBeInTheDocument();
    expect(screen.getByText(/Demonstration data present/)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("Connected")).toBeInTheDocument());
    expect(sessionStorage.getItem("adaptive-ids.token")).toBe("t");
  });
});
