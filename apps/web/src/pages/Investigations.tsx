import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { Alert, Page } from "../api/types";
import { useApi } from "../api/useApi";
import { useAuth } from "../auth/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { Empty, ErrorState, Loading } from "../components/States";
import { AlertsTable, useUserMap } from "./Alerts";

export function InvestigationsPage() {
  const { user } = useAuth();
  const users = useUserMap();
  const mine = useApi(() => api.get<Page<Alert>>("/alerts", { status: "investigating", assignee_id: user?.id, limit: 100 }), [user?.id]);
  const all = useApi(() => api.get<Page<Alert>>("/alerts", { status: "investigating", limit: 100 }), []);
  return (
    <>
      <PageHeader title="Investigations" description="Alerts currently under investigation. Open one for the event, model prediction, input features, notes and history." />
      <section className="card" aria-labelledby="mine-h">
        <div className="card-header"><h2 id="mine-h">Assigned to me</h2></div>
        {mine.error ? <ErrorState error={mine.error} /> : mine.data ? (mine.data.items.length ? <AlertsTable alerts={mine.data.items} users={users} />
          : <Empty title="Nothing assigned to you">Start investigating an alert from the <Link to="/alerts?status=new">new alerts</Link>.</Empty>) : <Loading />}
      </section>
      <section className="card" aria-labelledby="all-h">
        <div className="card-header"><h2 id="all-h">All investigations</h2><span className="hint">{all.data ? `${all.data.total} in progress` : ""}</span></div>
        {all.data ? (all.data.items.length ? <AlertsTable alerts={all.data.items} users={users} /> : <Empty title="No open investigations" />) : <Loading />}
      </section>
    </>
  );
}
