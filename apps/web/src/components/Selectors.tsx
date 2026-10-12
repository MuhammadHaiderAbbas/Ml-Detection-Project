import { api } from "../api/client";
import type { ImportRecord, ModelVersion, Page } from "../api/types";
import { useApi } from "../api/useApi";

export function ImportSelect({ value, onChange, label = "Data source (import)" }: { value: string; onChange: (v: string) => void; label?: string }) {
  const { data } = useApi(() => api.get<Page<ImportRecord>>("/imports", { limit: 200 }), []);
  return (
    <label className="field">{label}
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All imports</option>
        {data?.items.map((i) => <option key={i.id} value={i.id}>#{i.id} {i.dataset_name}@{i.dataset_version}</option>)}
      </select>
    </label>
  );
}

export function ModelSelect({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { data } = useApi(() => api.get<ModelVersion[]>("/models"), []);
  return (
    <label className="field">Model version
      <select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">All versions</option>
        {data?.map((m) => <option key={m.id} value={m.id}>{m.version_id} ({m.status})</option>)}
      </select>
    </label>
  );
}
