import { useCallback } from "react";
import { useSearchParams } from "react-router-dom";

/** Filter state kept in the URL so views are shareable and survive reloads. */
export function useUrlFilters() {
  const [params, setParams] = useSearchParams();
  const get = useCallback((k: string) => params.get(k) ?? "", [params]);
  const getAll = useCallback((k: string) => params.getAll(k), [params]);
  const set = useCallback((updates: Record<string, string | string[] | null>) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      for (const [k, v] of Object.entries(updates)) {
        next.delete(k);
        if (Array.isArray(v)) v.forEach((x) => next.append(k, x));
        else if (v) next.set(k, v);
      }
      if (!("offset" in updates)) next.delete("offset");
      return next;
    }, { replace: true });
  }, [setParams]);
  return { params, get, getAll, set };
}

export const RANGE_PRESETS: { value: string; label: string; hours: number | null }[] = [
  { value: "", label: "All time", hours: null },
  { value: "24h", label: "Last 24 hours", hours: 24 },
  { value: "7d", label: "Last 7 days", hours: 24 * 7 },
  { value: "30d", label: "Last 30 days", hours: 24 * 30 },
];

export function sinceFromPreset(preset: string): string | undefined {
  const p = RANGE_PRESETS.find((r) => r.value === preset);
  if (!p?.hours) return undefined;
  return new Date(Date.now() - p.hours * 3600_000).toISOString();
}
