import { Navigate, Route, Routes, useLocation } from "react-router-dom";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { Loading } from "./components/States";
import { AlertDetailPage } from "./pages/AlertDetail";
import { AlertsPage } from "./pages/Alerts";
import { AuditPage } from "./pages/Audit";
import { DashboardPage } from "./pages/Dashboard";
import { DataSourcesPage } from "./pages/DataSources";
import { DriftPage } from "./pages/Drift";
import { DriftAnalysisPage } from "./pages/DriftAnalysis";
import { DriftEventPage } from "./pages/DriftEvent";
import { ExperimentsPage } from "./pages/Experiments";
import { ImportDetailPage } from "./pages/ImportDetail";
import { IncidentDetailPage } from "./pages/IncidentDetail";
import { IncidentsPage } from "./pages/Incidents";
import { InvestigationsPage } from "./pages/Investigations";
import { LoginPage } from "./pages/Login";
import { ModelDetailPage } from "./pages/ModelDetail";
import { ModelsPage } from "./pages/Models";
import { NotFoundPage } from "./pages/NotFound";
import { ReportsPage } from "./pages/Reports";
import { SettingsPage } from "./pages/Settings";
import { TrafficPage } from "./pages/Traffic";

function RequireAuth({ children }: { children: JSX.Element }) {
  const { user, checking } = useAuth();
  const location = useLocation();
  if (checking) return <div className="content"><Loading label="Checking session…" /></div>;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return children;
}

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<RequireAuth><Layout /></RequireAuth>}>
        <Route index element={<DashboardPage />} />
        <Route path="traffic" element={<TrafficPage />} />
        <Route path="alerts" element={<AlertsPage />} />
        <Route path="alerts/:id" element={<AlertDetailPage />} />
        <Route path="incidents" element={<IncidentsPage />} />
        <Route path="incidents/:id" element={<IncidentDetailPage />} />
        <Route path="drift" element={<DriftPage />} />
        <Route path="drift/analyses/:id" element={<DriftAnalysisPage />} />
        <Route path="drift/events/:id" element={<DriftEventPage />} />
        <Route path="models" element={<ModelsPage />} />
        <Route path="models/:id" element={<ModelDetailPage />} />
        <Route path="investigations" element={<InvestigationsPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="data-sources" element={<DataSourcesPage />} />
        <Route path="data-sources/:id" element={<ImportDetailPage />} />
        <Route path="experiments" element={<ExperimentsPage />} />
        <Route path="audit" element={<AuditPage />} />
        <Route path="settings" element={<SettingsPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}
