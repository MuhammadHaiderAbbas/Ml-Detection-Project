# Adaptive IDS — ML-based network anomaly detection with concept drift

A research-driven network intrusion detection platform that extends an MSc
project. This repository is being built in small, tested milestones.

> **Current state**
> - **Milestone 1 (reproducible ML baseline): supervised baseline reproduced.** All 15 reported supervised metrics from the MSc notebook (Random Forest, XGBoost, LightGBM) reproduce exactly by retraining with the notebook's settings and library versions. The original `.pkl` files were not provided. The review found the notebook actually used **NSL-KDD KDDTest+, not CIC-IDS2018**, and kept NSL-KDD's difficulty column as a feature. On the dataset's official train/test split, accuracy is about 77–79 %. See [`docs/msc-notebook-review.md`](docs/msc-notebook-review.md) and [`docs/milestone-1-status.md`](docs/milestone-1-status.md).
> - **Phase 7 (security and testing): implemented.** Read-only viewer role and a per-route permission model, sign-in throttling, idle sessions, password management, security headers and size limits, configurable data retention, verified backup and restore, and blocking dependency and static-analysis scans. It is mapped to the spec's §17 controls and §20 acceptance checks in [`docs/phase-7-security.md`](docs/phase-7-security.md).
> - **Phase 6 (model registry and governance): implemented.** Candidates are evaluated against the active model on the same labelled data under a versioned non-inferiority protocol. Approval needs a passing evaluation or an audited, justified override. Activation and rollback first prove the artifact can be restored. See [`docs/phase-6-governance.md`](docs/phase-6-governance.md).
> - **Phase 5 (drift monitoring): implemented.** Feature, prediction, performance and suspected concept drift, kept separate, with event review and controlled experiments. See [`docs/phase-5-drift.md`](docs/phase-5-drift.md).
> - **Phase 4 (web dashboard): implemented.** React + TypeScript UI for all twelve sections. See [`docs/phase-4-frontend.md`](docs/phase-4-frontend.md).
> - **Phase 3 (backend and persistence): implemented.** API, database, migrations, alerts and incidents. See [`docs/phase-3-backend.md`](docs/phase-3-backend.md).
>
> Every result in this repository is labelled by provenance (reproduction, controlled experiment or synthetic demo). The dissertation's own numbers are quoted only as "reported".

## What works today

- Versioned **feature schemas** with leakage guards (label, timestamp and IDs can never be features).
- **CSV ingestion** for untrusted files: limits, column mapping, per-row rejection reasons, duplicates, hash checks, cancellation, and a full import record.
- One **preprocessing** interface for training, evaluation and inference. It fits on training data only and saves its state as JSON.
- **Trusted model loading**: joblib/pickle files are loaded only if they are listed in a manifest with a matching SHA-256.
- **Traceable inference**: every prediction records the model and preprocessing versions, the decision rule, the score kind (uncalibrated) and a status.
- **Evaluation**: per-class metrics, confusion matrix, FPR and FNR, chronological, stratified and fixed splits, and a latency benchmark.
- **Experiment runner** that writes `result.json` and a Markdown report with the environment, the methodology and any limitations, labelled by provenance.
- **Research recovery tools**: a hash-verified backup and a static inventory of the original project.
- **Synthetic demo data**, clearly labelled as synthetic everywhere.

**Backend (Phase 3)**

- **FastAPI** service with **SQLAlchemy** models and **Alembic** migrations. PostgreSQL is the target; SQLite works with no setup.
- **Imports**: CSV upload with background validation, rejected-row reports and cancellation.
- **Scoring**: runs the active model and stores traceable predictions.
- **Alerts**: created from suspicious predictions, with severity from configurable rules; lifecycle New → Investigating → Resolved or False Positive; assignment, notes, history, grouping and CSV export.
- **Incidents**: group alerts and keep a timeline, evidence and the analyst's disposition; Markdown export.
- **Model registry**: explicit approval and activation, plus rollback.
- **Dashboard summary**: every number comes with its counting rule.
- **Security**: scrypt password hashing, expiring bearer sessions, server-side admin/analyst roles and an audit log.

**Web dashboard (Phase 4)**

- React + TypeScript + Vite UI in `apps/web/` with dashboard, live traffic (recorded replay), alerts, the investigation view, incidents, model management, data sources, experiments, reports, audit logs and settings.
- Light and dark themes, a phone-width layout and keyboard accessibility.
- Every number comes from the API, and every synthetic record is labelled.

**Drift monitoring (Phase 5)**

- **Four signals, kept separate:** feature drift (PSI with Bonferroni-corrected KS tests), prediction drift (class mix, plus ADWIN on the suspicious rate), performance degradation and suspected concept drift (both need labels).
- **Analyses:** configurable reference and current windows, versioned thresholds, and time-series and distribution views.
- **Drift events:** reviewed through acknowledge → investigate → close, with a required closing note, investigation notes and Markdown/CSV reports.
- **Controlled experiments:** `adaptive-ids drift-experiment` measures detection delay, false alarms and overhead on SYNTHETIC data.
- **Never automatic:** drift never retrains or promotes a model.

**Model governance (Phase 6)**

- **Candidate evaluation:** the candidate and the active baseline are scored on the same labelled import. Paired-bootstrap CIs of the differences are judged against non-inferiority margins (recall, F1, false-positive rate); McNemar is reported for context. The training file is refused.
- **Gated approval:** `pass` approves; `fail` needs an override with a written justification (audited separately); insufficient evidence can't be overridden. Evaluations go stale when the protocol or the active model changes.
- **Restorability:** approval, activation and rollback re-hash, re-load and replay 25 recorded predictions before acting.
- **NSL-KDD support:** schema (difficulty excluded), `adaptive-ids prepare-nsl-kdd`, and `adaptive-ids msc-reproduce` for the notebook reproduction.

**Security and operations (Phase 7)**

- **Roles:** admin, analyst and a read-only viewer. Every API route declares one named permission, and a test fails if a route is added without one.
- **Accounts:** scrypt passwords with a policy, sign-in throttling (HTTP 429), 60-minute idle sessions, password change and reset, role changes. All are audited, and every change signs the user out.
- **HTTP:** strict Content Security Policy and security headers, request-size limits, spreadsheet-formula escaping in exports, and generic error responses.
- **Data:** `adaptive-ids retention` (dry run or `--apply`; evidence is kept), and `adaptive-ids data-backup` / `data-restore` with SHA-256 manifests and post-restore model checks.
- **CI:** blocking `pip-audit` and `bandit`, `npm audit`, PostgreSQL tests, and a fresh-setup job that follows this README.

Not built yet: SHAP explanations. See [`docs/architecture.md`](docs/architecture.md).

## Quick start (Windows PowerShell)

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.lock.txt
pip install -e . --no-deps
python -m pytest
```

On Linux or macOS, use `python3.10 -m venv .venv` and `source .venv/bin/activate`.
No GPU, cloud account or API key is required.

## Run the API

```powershell
copy .env.example .env                 # SQLite by default; PostgreSQL: docker compose up -d postgres
adaptive-ids db-upgrade
adaptive-ids create-user admin --role admin
adaptive-ids demo --admin admin        # optional: repeatable SYNTHETIC demo data, model and alerts
adaptive-ids serve                     # API docs: http://127.0.0.1:8000/docs
```

Web UI: `cd apps/web && npm ci && npm run build`, then set `ADAPTIVE_IDS_WEB_DIST=apps/web/dist` and start
`adaptive-ids serve` again; the dashboard is at http://127.0.0.1:8000. For hot reload, run `npm run dev` instead
(http://localhost:5173). Requires Node.js 20.19+ or 22.12+.

## Demo on synthetic data (ML engine only)

```powershell
adaptive-ids make-synthetic                       # data/sample/flows_SYNTHETIC_demo.csv
adaptive-ids run configs/experiments/synthetic-demo.json
# -> experiments/runs/synthetic-demo-rf-<time>/report.md
```

The synthetic classes are easy to separate, so near-perfect scores are expected.
They show that the software works, **not** how well it detects intrusions.

## Screenshots

Web dashboard, captured from the running app on 2026-10-11 with the SYNTHETIC demo loaded:

| | |
|---|---|
| [Dashboard](docs/screenshots/ui-01-dashboard.png) | [Dashboard (dark)](docs/screenshots/ui-02-dashboard-dark.png) |
| [Alert investigation](docs/screenshots/ui-03-alert-investigation.png) | [Incident](docs/screenshots/ui-04-incident.png) |
| [Model governance](docs/screenshots/ui-05-model.png) | [Phone width](docs/screenshots/ui-06-mobile.png) |
| [Drift Monitor](docs/screenshots/ui-07-drift-monitor.png) | [Drift analysis](docs/screenshots/ui-08-drift-analysis.png) |
| [Candidate evaluation (NSL-KDD)](docs/screenshots/ui-09-candidate-evaluation.png) | [Approve with override](docs/screenshots/ui-10-approve-override.png) |
| [Model governance and restorability](docs/screenshots/ui-11-model-governance.png) | [Candidate evaluation (dark)](docs/screenshots/ui-12-candidate-evaluation-dark.png) |
| [Read-only viewer](docs/screenshots/ui-13-viewer-read-only.png) | [Account security and user admin](docs/screenshots/ui-14-account-security.png) |
| [Sign-in throttling](docs/screenshots/ui-15-login-throttled.png) | |

Engine output captured on 2026-10-10 (images 2–4 use SYNTHETIC demo data; the scores show the pipeline works, not detection performance):

| | |
|---|---|
| [Test suite](docs/screenshots/01-test-suite.png) | [CLI experiment run](docs/screenshots/02-cli-experiment-run.png) |
| [Experiment report](docs/screenshots/03-experiment-report.png) | [Import validation](docs/screenshots/04-import-validation.png) |
| [Safety checks](docs/screenshots/05-safety-checks.png) | |

## Reproducing the original baseline

Follow [`docs/reproducing-the-baseline.md`](docs/reproducing-the-baseline.md):
back up → inventory → pin environment → verify schema → register the trusted
model → run → record discrepancies.

## Commands

| Command | Purpose |
|---|---|
| `adaptive-ids backup DEST --source SRC` / `--verify` | Hash-verified, read-only copy of the original project |
| `adaptive-ids inventory DIR` | Static inventory of notebooks, data, models and dependencies |
| `adaptive-ids hash FILE...` | SHA-256 for manifests and dataset configs |
| `adaptive-ids preview CSV --schema S` | Column compatibility check and first rows |
| `adaptive-ids make-synthetic` | Labelled synthetic demo dataset |
| `adaptive-ids run CONFIG` | Run an experiment and write its report |
| `adaptive-ids db-upgrade` | Apply database migrations |
| `adaptive-ids create-user NAME --role admin\|analyst` | Create an application user |
| `adaptive-ids demo --admin NAME` | Load the SYNTHETIC end-to-end demonstration into the database |
| `adaptive-ids serve` | Start the API (OpenAPI docs at `/docs`) |
| `adaptive-ids drift-experiment` | Controlled drift experiment on SYNTHETIC data (delay, false alarms, overhead) |

## Layout

```
src/adaptive_ids/   schema, provenance, ingestion/, preprocessing/, detection/,
                    evaluation/, experiments/, research/   (ML engine)
                    db/, services/, api/, settings, security   (backend)
migrations/         Alembic migrations
apps/web/           React + TypeScript dashboard (Vite)
configs/            schemas/, experiments/, severity-rules.json
models/             trusted-artifact manifest (binaries git-ignored)
data/               raw/ processed/ sample/ (git-ignored)
experiments/runs/   run outputs (git-ignored)
docs/               status, architecture, reproduction guide
tests/              pytest suite
```

## Data and safety rules

- Never commit datasets, packet captures, credentials or model binaries (`.gitignore` enforces the common cases).
- Only load model files you produced yourself and have listed in `models/trusted_artifacts.json`.
- Process only network data you are authorised to use.
- An ML prediction is a suspicion, not a confirmed attack.
