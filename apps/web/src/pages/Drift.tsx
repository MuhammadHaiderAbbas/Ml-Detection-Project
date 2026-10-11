import { PageHeader } from "../components/PageHeader";
import { Empty } from "../components/States";

export function DriftPage() {
  return (
    <>
      <PageHeader title="Drift Monitor" description="Feature drift, prediction drift, concept drift and performance degradation will be tracked separately here." />
      <section className="card">
        <Empty title="Drift monitoring is not configured yet">
          It arrives in Phase 5. No drift figures are shown until they are computed from real reference and current windows.
          A drift signal will never promote or replace a model automatically.
        </Empty>
      </section>
    </>
  );
}
