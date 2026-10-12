import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { Alert } from "../api/types";
import { AlertStatusBadge, ProvenanceBadge, SeverityBadge } from "../components/Badges";
import { ConfirmDialog } from "../components/ConfirmDialog";
import { AlertsTable } from "../pages/Alerts";

const alert: Alert = {
  id: 7, prediction_id: 1, event_id: 1, model_version_id: 1, import_id: 1, predicted_class: "SYNTH_DoS", score: 0.97,
  severity: "high", severity_rule: "1.0.0:x", group_key: "g", status: "new", assignee_id: null, incident_id: null,
  created_at: "2026-01-05T09:00:00Z", updated_at: "2026-01-05T09:00:00Z",
};

describe("badges", () => {
  it("never relies on colour alone: severity and status carry text labels", () => {
    render(<><SeverityBadge severity="critical" /><AlertStatusBadge status="false_positive" /></>);
    expect(screen.getByText("Critical")).toBeInTheDocument();
    expect(screen.getByText("False positive")).toBeInTheDocument();
    expect(screen.getByTitle(/not a verified severity/)).toBeInTheDocument();
  });

  it("labels synthetic data clearly", () => {
    render(<ProvenanceBadge provenance="synthetic_demo" />);
    expect(screen.getByText("Synthetic demo")).toBeInTheDocument();
  });
});

describe("AlertsTable", () => {
  it("shows the uncalibrated-score caveat and links each alert", () => {
    render(<MemoryRouter><AlertsTable alerts={[alert]} /></MemoryRouter>);
    expect(screen.getByRole("link", { name: "#7" })).toHaveAttribute("href", "/alerts/7");
    expect(screen.getByText("0.970")).toBeInTheDocument();
    expect(screen.getByText(/Uncalibrated model score/)).toBeInTheDocument();
  });

  it("disables selection of alerts that already belong to an incident", () => {
    render(<MemoryRouter><AlertsTable alerts={[{ ...alert, incident_id: 3 }]} selectable selected={new Set()} onToggle={() => {}} /></MemoryRouter>);
    expect(screen.getByLabelText("Select alert 7")).toBeDisabled();
  });
});

describe("ConfirmDialog", () => {
  it("requires a reason before confirming a sensitive action", async () => {
    const onConfirm = vi.fn();
    render(<ConfirmDialog title="Activate" confirmLabel="Activate" reasonLabel="Reason" reasonRequired onConfirm={onConfirm} onCancel={() => {}} />);
    await userEvent.click(screen.getByRole("button", { name: "Activate" }));
    expect(screen.getByRole("alert")).toHaveTextContent("A reason is required");
    expect(onConfirm).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText(/Reason/), "reviewed test metrics");
    await userEvent.click(screen.getByRole("button", { name: "Activate" }));
    await waitFor(() => expect(onConfirm).toHaveBeenCalledWith("reviewed test metrics"));
  });
});
