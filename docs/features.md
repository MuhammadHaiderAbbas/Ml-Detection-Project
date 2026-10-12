# Features by phase

What each development phase added. For the overview, see the [README](../README.md).

## Milestone 1: ML engine

- Versioned **feature schemas** with leakage guards (label, timestamp and IDs can never be features).
- **CSV ingestion** for untrusted files: limits, column mapping, per-row rejection reasons, duplicates, hash checks, cancellation, and a full import record.
- One **preprocessing** interface for training, evaluation and inference. It fits on training data only and saves its state as JSON.
- **Trusted model loading**: joblib/pickle files are loaded only if they are listed in a manifest with a matching SHA-256.
- **Traceable inference**: every prediction records the model and preprocessing versions, the decision rule, the score kind (uncalibrated) and a status.
- **Evaluation**: per-class metrics, confusion matrix, FPR and FNR, chronological, stratified and fixed splits, and a latency benchmark.
- **Experiment runner** that writes `result.json` and a Markdown report with the environment, the methodology and any limitations, labelled by provenance.
- **Research recovery tools**: a hash-verified backup and a static inventory of the original project.
- **Synthetic demo data**, clearly labelled as synthetic everywhere.

## Backend (Phase 3)

- **FastAPI** service with **SQLAlchemy** models and **Alembic** migrations. PostgreSQL is the target; SQLite works with no setup.
- **Imports**: CSV upload with background validation, rejected-row reports and cancellation.
- **Scoring**: runs the active model and stores traceable predictions.
- **Alerts**: created from suspicious predictions, with severity from configurable rules; lifecycle New → Investigating → Resolved or False Positive; assignment, notes, history, grouping and CSV export.
- **Incidents**: group alerts and keep a timeline, evidence and the analyst's disposition; Markdown export.
- **Model registry**: explicit approval and activation, plus rollback.
- **Dashboard summary**: every number comes with its counting rule.
- **Security**: scrypt password hashing, expiring bearer sessions, server-side admin/analyst roles and an audit log.

## Web dashboard (Phase 4)

- React + TypeScript + Vite UI in `apps/web/` with dashboard, live traffic (recorded replay), alerts, the investigation view, incidents, model management, data sources, experiments, reports, audit logs and settings.
- Light and dark themes, a phone-width layout and keyboard accessibility.
- Every number comes from the API, and every synthetic record is labelled.

## Drift monitoring (Phase 5)

- **Four signals, kept separate:** feature drift (PSI with Bonferroni-corrected KS tests), prediction drift (class mix, plus ADWIN on the suspicious rate), performance degradation and suspected concept drift (both need labels).
- **Analyses:** configurable reference and current windows, versioned thresholds, and time-series and distribution views.
- **Drift events:** reviewed through acknowledge → investigate → close, with a required closing note, investigation notes and Markdown/CSV reports.
- **Controlled experiments:** `adaptive-ids drift-experiment` measures detection delay, false alarms and overhead on SYNTHETIC data.
- **Never automatic:** drift never retrains or promotes a model.

## Model governance (Phase 6)

- **Candidate evaluation:** the candidate and the active baseline are scored on the same labelled import. Paired-bootstrap CIs of the differences are judged against non-inferiority margins (recall, F1, false-positive rate); McNemar is reported for context. The training file is refused.
- **Gated approval:** `pass` approves; `fail` needs an override with a written justification (audited separately); insufficient evidence can't be overridden. Evaluations go stale when the protocol or the active model changes.
- **Restorability:** approval, activation and rollback re-hash, re-load and replay 25 recorded predictions before acting.
- **NSL-KDD support:** schema (difficulty excluded), `adaptive-ids prepare-nsl-kdd`, and `adaptive-ids msc-reproduce` for the notebook reproduction.

## Security and operations (Phase 7)

- **Roles:** admin, analyst and a read-only viewer. Every API route declares one named permission, and a test fails if a route is added without one.
- **Accounts:** scrypt passwords with a policy, sign-in throttling (HTTP 429), 60-minute idle sessions, password change and reset, role changes. All are audited, and every change signs the user out.
- **HTTP:** strict Content Security Policy and security headers, request-size limits, spreadsheet-formula escaping in exports, and generic error responses.
- **Data:** `adaptive-ids retention` (dry run or `--apply`; evidence is kept), and `adaptive-ids data-backup` / `data-restore` with SHA-256 manifests and post-restore model checks.
- **CI:** blocking `pip-audit` and `bandit`, `npm audit`, PostgreSQL tests, and a fresh-setup job that follows this README.

## Model explanations (1.0)

- Every alert shows exact SHAP feature contributions (TreeExplainer) for the model and preprocessing that made it. They are only shown after the prediction is reproduced and the contributions add up to the model output. See [`model-explanations.md`](model-explanations.md), including a real NSL-KDD false positive traced to one feature.
