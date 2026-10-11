import { describe, expect, it } from "vitest";
import { buildQuery } from "../api/client";
import { formatBytes, formatNumber, formatPct, formatScore, humanize } from "../lib/format";

describe("formatters", () => {
  it("formats numbers, percentages and scores without inventing values", () => {
    expect(formatPct(0.1234)).toBe("12.3%");
    expect(formatPct(null)).toBe("—");
    expect(formatScore(undefined)).toBe("—");
    expect(formatScore(0.9)).toBe("0.900");
    expect(formatNumber(Number.NaN)).toBe("—");
    expect(formatBytes(2048)).toBe("2.0 KB");
    expect(humanize("false_positive")).toBe("False positive");
  });

  it("builds query strings, repeating array params and skipping empties", () => {
    expect(buildQuery({ status: ["new", "investigating"], import_id: "", limit: 5, x: undefined })).toBe("?status=new&status=investigating&limit=5");
    expect(buildQuery({})).toBe("");
  });
});
