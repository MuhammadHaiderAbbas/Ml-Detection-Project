import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Explanation } from "../api/types";
import { ExplanationChart } from "../components/ExplanationChart";

const contributions = Array.from({ length: 13 }, (_, i) => ({
  feature: `f${i}`, raw_value: i * 10, model_input: i * 10, contribution: (i % 2 ? -1 : 1) * (0.2 - i * 0.01),
}));
const x: Explanation = {
  available: true, reason: null, prediction_id: 1, method: "shap.TreeExplainer (exact, tree_path_dependent)", library: "shap 0.49.1",
  output_space: "probability", target_class: "dos", base_value: 0.3,
  model_output: 0.3 + contributions.reduce((s, c) => s + c.contribution, 0), additivity_error: 1e-16,
  artifact_sha256: "a".repeat(64), preprocessing_version: "pp-1", contributions, limitations: ["l1"], computed_at: "2026-10-12T00:00:00Z",
};

describe("ExplanationChart", () => {
  it("shows the top ten features and sums the rest so the bars still add up", () => {
    render(<ExplanationChart x={x} />);
    expect(screen.getByText("f0")).toBeTruthy();
    expect(screen.getByText("f9")).toBeTruthy();
    expect(screen.queryByText("f10")).toBeNull();
    expect(screen.getByText("3 other features")).toBeTruthy();
    const rest = contributions.slice(10).reduce((s, c) => s + c.contribution, 0);
    expect(screen.getByText(`+${rest.toFixed(4)}`)).toBeTruthy();
    expect(screen.getByText(/Raises the score for “dos”/)).toBeTruthy();
  });

  it("table view lists every feature with exact values", () => {
    render(<ExplanationChart x={x} />);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getAllByRole("row")).toHaveLength(14);
    expect(screen.getByText("f12")).toBeTruthy();
  });
});
