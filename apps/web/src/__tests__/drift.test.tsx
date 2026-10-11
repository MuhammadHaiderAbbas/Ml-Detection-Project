import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DriftSeverityBadge, VerdictBadge } from "../components/Badges";
import { DriftAnalysisPage } from "../pages/DriftAnalysis";

afterEach(() => vi.restoreAllMocks());

const analysis = {
  id: 3, name: "No-label check", model_version_id: null, status: "completed", n_reference: 500, n_current: 400, error: null,
  reference_spec: { import_id: 1, since: null, until: null, dataset: "a@1", provenance: "controlled_experiment", schema_id: "s@1" },
  current_spec: { import_id: 2, since: null, until: null, dataset: "b@1", provenance: "controlled_experiment", schema_id: "s@1" },
  window_spec: { mode: "events", size: 200 }, features: ["x"], timings: { total_ms: 12 },
  config: { psi_moderate: 0.1, psi_major: 0.25, alpha: 0.01, psi_bins: 10, min_window_events: 200, perf_min_labels: 100, perf_moderate: 0.02, perf_major: 0.05, adwin_delta: 0.002 },
  summary: { feature: { status: "not_detected" }, prediction: { status: "not_assessable" }, performance: { status: "not_assessable", reason: "needs labelled events in both samples" },
    concept: { status: "not_assessable" }, n_reference: 500, n_current: 400, n_windows: 2, features_tested: 1, features_drifted: [],
    interpretation: "Drift signals describe change in data or model behaviour. They are not evidence of an attack." },
  overall: { features: { x: { n_ref: 500, n_cur: 400, psi: 0.02, ks_d: 0.04, ks_p: 0.5, ks_p_adj: 0.5, ref_median: 1, cur_median: 1, severity: "none", bins: { edges: [0, 1], ref: [0.3, 0.4, 0.3], cur: [0.31, 0.39, 0.3] } } },
    prediction: null, performance: { reference: { n_labelled: 0, error_rate: null }, current: { n_labelled: 0, error_rate: null }, severity: "insufficient_data", error_rate_change: null }, streaming: {} },
  created_at: "2026-01-01T00:00:00Z", completed_at: "2026-01-01T00:00:01Z",
};

describe("drift", () => {
  it("labels severities and verdicts in words, not colour alone", () => {
    render(<><DriftSeverityBadge severity="insufficient_data" /><VerdictBadge status="not_assessable" /></>);
    expect(screen.getByText("Insufficient data")).toBeInTheDocument();
    expect(screen.getByText("Not assessable")).toBeInTheDocument();
  });

  it("shows unassessable signals honestly instead of inventing values", async () => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const path = new URL(String(input), "http://x").pathname;
      const body = path.endsWith("/windows") ? [] : path.startsWith("/api/drift/events") ? { items: [], total: 0, limit: 200, offset: 0 } : analysis;
      return new Response(JSON.stringify(body), { status: 200 });
    });
    render(<MemoryRouter initialEntries={["/drift/analyses/3"]}><Routes><Route path="/drift/analyses/:id" element={<DriftAnalysisPage />} /></Routes></MemoryRouter>);
    expect(await screen.findByText("No-label check")).toBeInTheDocument();
    expect(screen.getAllByText("Not assessable")).toHaveLength(3);
    expect(screen.getByText("needs labelled events in both samples")).toBeInTheDocument();
    expect(screen.getByText(/no labels, performance not assessable/)).toBeInTheDocument();
    expect(await screen.findByText("No drift events were raised.")).toBeInTheDocument();
  });
});
