import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";
import type { EvaluationDetail, Gate } from "../api/types";
import { EvaluationVerdictBadge, RestoreBadge } from "../components/Badges";
import { DifferenceChart } from "../components/GovernanceCharts";
import { GateList } from "../pages/EvaluationDetail";

const gates: Gate[] = [
  { id: "labelled_events", kind: "validity", passed: true, value: 22544, threshold: 200, detail: "labelled events scored by every compared model" },
  { id: "non_inferior_false_positive_rate", kind: "performance", passed: false, value: 0.0193, threshold: 0.005, detail: "upper 95% bound of candidate - baseline false-positive rate" },
];

const ev = {
  id: 2, protocol: { recall_margin: 0.01, f1_margin: 0.01, fpr_margin: 0.005, confidence: 0.95, bootstrap_iterations: 1000 },
  gates: [...gates, { id: "non_inferior_attack_recall", kind: "performance", passed: true, value: 0.0297, threshold: -0.01, detail: "recall" }],
  results: {
    differences: {
      attack_recall: { difference: 0.033, ci_low: 0.0297, ci_high: 0.0367, better_when: "higher" },
      false_positive_rate: { difference: 0.0166, ci_low: 0.014, ci_high: 0.0193, better_when: "lower" },
    },
  },
} as unknown as EvaluationDetail;

describe("governance UI", () => {
  it("labels verdicts in words, not colour alone", () => {
    render(<><EvaluationVerdictBadge verdict="fail" /><EvaluationVerdictBadge verdict="insufficient_evidence" /><EvaluationVerdictBadge verdict={null} status="running" /></>);
    expect(screen.getByText("Failed gates")).toBeTruthy();
    expect(screen.getByText("Insufficient evidence")).toBeTruthy();
    expect(screen.getByText("Running")).toBeTruthy();
  });

  it("shows restorability state", () => {
    render(<><RestoreBadge ok={null} /><RestoreBadge ok={false} /><RestoreBadge ok partial /></>);
    expect(screen.getByText("Not checked")).toBeTruthy();
    expect(screen.getByText("Not restorable")).toBeTruthy();
    expect(screen.getByText("Restorable (no sample)")).toBeTruthy();
  });

  it("lists gates with values against thresholds", () => {
    render(<GateList gates={gates} />);
    expect(screen.getByText("22,544 ≥ 200")).toBeTruthy();
    expect(screen.getByText("+1.93 pp ≤ +0.50 pp")).toBeTruthy();
    expect(screen.getByTitle("Failed")).toBeTruthy();
  });

  it("difference chart has a table twin with signed percentage points", async () => {
    render(<MemoryRouter><DifferenceChart ev={ev} /></MemoryRouter>);
    expect(screen.getByRole("img").getAttribute("aria-label")).toMatch(/non-inferiority margins/);
    await userEvent.click(screen.getByRole("button", { name: "Table" }));
    const rows = screen.getAllByRole("row");
    expect(rows[1].textContent).toContain("Attack recall");
    expect(rows[1].textContent).toContain("+3.30 pp");
    expect(rows[2].textContent).toContain("+1.66 pp");
    expect(rows[2].textContent).toContain("Fail");
  });
});
