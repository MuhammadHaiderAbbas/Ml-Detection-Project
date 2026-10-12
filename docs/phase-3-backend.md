# Phase 3 — Backend and persistence

Status: **implemented and tested** (FastAPI + SQLAlchemy + Alembic, tested on SQLite and PostgreSQL 16).

Until the original MSc baseline is reproduced (Milestone 1), the only model
that can run end to end is the **SYNTHETIC demo model**. Everything it produces
is labelled `synthetic_demo`, and the dashboard reports `demo_data_present: true`.

## Run it locally

```powershell
# 1. Configure (SQLite works out of the box; see .env.example for PostgreSQL)
copy .env.example .env
# Optional PostgreSQL:  docker compose up -d postgres   (then set ADAPTIVE_IDS_DATABASE_URL in .env)

# 2. Create the schema and the first admin
adaptive-ids db-upgrade
adaptive-ids create-user admin --role admin        # prompts for a password (min 12 chars)
adaptive-ids create-user alice --role analyst

# 3. Optional: load the repeatable SYNTHETIC demonstration
adaptive-ids demo --admin admin

# 4. Start the API
adaptive-ids serve                                  # http://127.0.0.1:8000/docs
```

Health check: `GET /api/health` (no authentication; it reports only the version and whether the database is reachable).

## Data flow

```
upload CSV ─► dataset_imports (queued) ─► background import: validate, reject rows with reasons
           ─► events (features + context such as src/dst; dataset label kept separately)
POST /imports/{id}/score ─► scoring_runs ─► predictions (model + preprocessing versions, status)
           ─► suspicious predictions ─► alerts (severity from configured rules, status "new")
analyst ─► alert status changes / notes / assignment ─► incidents (grouping, evidence, disposition)
every sensitive action ─► audit_logs
```

## Rules that keep results honest

| Rule | Where it's enforced |
|---|---|
| A prediction is a *suspicion*. Alerts start as `new` and only analysts change them. | `services/scoring.py`, `services/alerts.py` |
| The only confirmed-attack count is incidents with the analyst disposition `confirmed_attack`. The dashboard returns `null` plus an explanation until any disposition exists. | `services/dashboard.py` |
| Labels that came with an imported file (`events.dataset_label`) are used only for label-based metrics on a scoring run, marked "not analyst-confirmed". | `services/scoring.py` |
| Severity is a triage priority from `configs/severity-rules.json` (first match wins; the rule id and version are stored on each alert). It is not a verified severity. | `services/severity.py` |
| Scores are labelled uncalibrated. | `detection/predictor.py` |
| A model needs recorded test-set results and an admin approval with a reason before it can become active. Nothing promotes a model automatically. | `services/registry.py` |
| Rollback = activating a previously approved, archived version. It is recorded as `model.rollback`. | `services/registry.py` |
| The model file is re-hashed before every load. A mismatch fails the scoring run, and no predictions are stored. | `detection/artifacts.py`, `services/scoring.py` |
| The import schema must provide exactly the model's features. | `services/scoring.py` |
| An import + model pair is scored once. | `services/scoring.py` |
| Resolving an alert, marking it a false positive, or changing an incident's disposition requires a note. Closing an incident requires a disposition. | `services/alerts.py`, `services/incidents.py` |

## Alert lifecycle

```
new ──► investigating ──► resolved
 │            │      └──► false_positive
 └────────────┴─────────► false_positive
resolved / false_positive ──► investigating   (re-open, with history kept)
```

## Security (Phase 3 scope)

- Passwords: scrypt (Python stdlib), min 12 characters. Login takes the same time for unknown users, and the error message doesn't say whether the username exists.
- Sessions: random bearer tokens. Only their SHA-256 is stored. They expire (`ADAPTIVE_IDS_SESSION_HOURS`), are revoked on logout, and deactivating a user revokes all their sessions.
- Roles are checked server-side: **admin** (users, model registration/approval/activation, audit log) and **analyst** (imports, scoring, alerts, incidents).
- Uploads: `.csv` only, stored under a generated name (the client file name is never used as a path), with size and row limits and a binary-content check. Rejected uploads are deleted.
- Model registration reads only from the server's `experiments/runs` directory, with path-traversal checks.
- Errors: unexpected exceptions return a reference ID, not internals. Validation errors don't echo the submitted values.
- CSV export guards against spreadsheet formula injection. Exports are audited.
- Audited actions: login and failed login, logout, user create/activate/deactivate, import create/cancel, scoring start, model register/approve/reject/activate/rollback, alert status/assign/export, incident create/update/link/unlink/export.

Deferred to Phase 7: login rate limiting, finer-grained permissions, data-retention jobs, backup/restore tooling, HTTPS deployment guidance.

## Database

PostgreSQL is the target; SQLite is supported for a zero-setup first run. Schema changes go through Alembic
(`migrations/`). CI applies the migrations to PostgreSQL 16, runs `alembic check` (models and
migration must match), and runs the API tests against PostgreSQL.

Main tables: `users`, `session_tokens`, `dataset_imports`, `rejected_rows`, `events`, `model_versions`,
`model_status_changes`, `scoring_runs`, `predictions`, `alerts`, `alert_status_changes`, `alert_notes`,
`incidents`, `incident_notes`, `audit_logs`.

## Known limitations

- Imports and scoring run as in-process background tasks (FastAPI `BackgroundTasks`). A server restart abandons a running job, which stays `running`. A proper job queue is a later improvement.
- Accepted rows are held in memory during import, and events store features as JSON. This is fine for demo and lab-sized files (the default limit is 1,000,000 rows) but not for full multi-day CIC captures.
- Timestamps without a timezone are interpreted as UTC (recorded as an import warning). Day-first formats need `metadata.timestamp_format` in the schema.
- The dashboard summary covers the KPIs in spec §6 except time-series charts, model-performance history and drift trends. Those arrive with Phase 4 (frontend) and Phase 5 (drift).
