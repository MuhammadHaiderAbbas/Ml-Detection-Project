# Phase 4 — Web dashboard

Status: **implemented and tested.** React 18 + TypeScript + Vite 8 + Recharts 3 + React Router 7, in `apps/web/`.

Until the original MSc baseline is reproduced (Milestone 1), the data you can see in the UI comes from the
**SYNTHETIC demo** (`adaptive-ids demo`). Every page that shows it carries a "Synthetic demo" label or banner.

## Run it

Two ways, both local and with no cloud services.

**Single process (built UI served by the API):**

```powershell
cd apps\web
npm ci
npm run build
cd ..\..
$env:ADAPTIVE_IDS_WEB_DIST = "apps\web\dist"     # or set it in .env
adaptive-ids serve                                  # http://127.0.0.1:8000
```

**Development (hot reload):** run `adaptive-ids serve` in one terminal and `npm run dev` in `apps/web` in another,
then open http://localhost:5173. The Vite dev server proxies `/api` to the backend.

Requires Node.js 20.19+ or 22.12+ (Node 22 LTS recommended). Sign in with a user created by `adaptive-ids create-user`.

## Pages

All twelve sidebar entries from spec §5 exist. Pages for later phases say so, rather than showing invented data.

| Page | What it shows | Backed by |
|---|---|---|
| Dashboard | KPI tiles (each links to its records and shows its counting rule), traffic/suspicious timeline with a table view, recent alerts, alerts by severity, most-flagged sources/destinations, label-based model performance per scoring run. Filters: time range, import, model version, severity | `/dashboard/summary`, `/dashboard/timeline`, `/alerts`, `/scoring-runs` |
| Live Traffic | Recorded events with the latest verdict, suspicious-only filter. Labelled as replayed recorded data, not live capture | `/traffic` |
| Alerts | Filterable, paginated list; grouped view; multi-select → create incident; CSV export | `/alerts`, `/alerts/groups`, `/alerts/export.csv` |
| Alert (investigation view) | Triage actions with required notes, assignment, link to an incident, model prediction (version, preprocessing, rule, uncalibrated score), event context, input features, dataset label (marked as not an analyst decision), notes, status history, related alerts | `/alerts/{id}` |
| Incidents / incident | Linked alerts, owner, timeline, evidence notes, disposition (decision note required), close, Markdown export | `/incidents…` |
| Investigations | Alerts under investigation: mine and everyone's | `/alerts?status=investigating` |
| Model Management / model | Versions, lifecycle history, artifact hash and lineage, recorded test-set metrics and confusion matrix, approve/reject/activate/rollback (admin, reason required), register an experiment run | `/models…`, `/experiment-runs` |
| Data Sources / import | CSV upload with schema choice, provenance, column mapping and preview; import record, validation summary, rejection reasons, rejected rows, scoring runs, "score with active model" | `/imports…`, `/schemas`, `/scoring-runs` |
| Experiments | Experiment runs on the server, with provenance and test accuracy | `/experiment-runs` |
| Reports | The exports available today, and which reports are still planned | — |
| Audit Logs | Admin-only, filterable | `/audit-logs` |
| Settings | Account, time zone, severity rules (read-only), user management (admin) | `/users`, `/severity-rules` |
| Drift Monitor | Analyses, verdicts, PSI-over-time and distribution charts, drift-event review (Phase 5, see `docs/phase-5-drift.md`) | `/drift/…` |

The header shows API/database connection status (polled), the count of new alerts, and an account menu with a
System/Light/Dark theme switch and sign-out.

## Design decisions

- **No invented numbers.** Every metric is read from the API. When a value cannot be known (for example confirmed attacks before any analyst decision, or an active model before one is approved), the tile says "Unavailable" or "None" and explains why.
- **Suspicion ≠ attack.** Alert lists, the investigation view, exports and the timeline caption all state that predictions are suspicions with uncalibrated scores and that severity is a triage priority. Only an incident disposition is shown as a confirmed attack.
- **Analyst vs automated.** The investigation view separates "Model prediction (automated output)" from triage actions, notes and history. The dataset label is marked as supplied with the file.
- **Sensitive actions need confirmation.** Resolving an alert, marking it a false positive, recording a disposition, and approving, rejecting, activating or rolling back a model all go through a confirmation dialog. Reasons are required where the API requires them.
- **Chart.** A stacked bar timeline with two categorical series in a fixed order (blue = not flagged, orange = suspicious). The palette was validated for colour-vision deficiency and contrast in both light and dark mode. There is a 2px gap between segments, a solid hairline grid, a legend and tooltip, and a Table toggle as the accessible equivalent. Bars are grouped by UTC event time; labels use the viewer's local time.
- **Accessibility.** Keyboard navigation with a skip link and visible focus rings. Status and severity badges always pair an icon with a text label. Text/background contrast is at least 4.5:1 in both themes (checked). Dialogs close with Escape and focus their first field.
- **Time.** Times show in the viewer's time zone with the zone name. Hovering any timestamp shows the exact UTC value.
- **Session token.** Kept in `sessionStorage` (cleared when the tab closes) and sent as a bearer header. The UI never renders server data as HTML. Exports download through authenticated requests, so the token never appears in a URL.

## Testing

- `npm test` (Vitest + Testing Library): formatters, query building, badges, the alerts table, required-reason dialogs, the sign-in error path, and dashboard rendering from API data, including "Unavailable" confirmed attacks and the demo banner.
- `npm run typecheck`, `npm run build`, and `npm audit --omit=dev --audit-level=high` run in CI.
- Checked manually with Playwright against the real backend. All pages were rendered in light, dark and 390px mobile widths (no horizontal overflow, no console errors). An end-to-end flow was also run: investigate → blocked resolve without a note → resolve with a note → link to an incident → upload CSV → preview → import → rejected rows shown.

## Known limitations

- Polling (every 4–30 s, depending on the page) rather than push updates.
- No SHAP explanations yet. The investigation view says so instead of estimating feature importance.
- No PDF export.
- The UI does not yet support importing from Zeek or NetFlow; it handles CSV only.
