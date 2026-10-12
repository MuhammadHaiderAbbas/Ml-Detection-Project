# Architecture

Adaptive IDS is a **modular monolith**: one Python package with clear module
boundaries, a FastAPI layer over it, and a React frontend served by the same
process. Every displayed number must trace back to an import record, a model
version, a preprocessing version and an experiment or database record.

## Runtime view (1.0)

```
 Browser (React + TypeScript, served by the API)
        │  HTTPS via your reverse proxy, or http://127.0.0.1
        ▼
 FastAPI ── security headers, size limits, per-route permission (admin / analyst / viewer)
        │
        ├─ services: imports · scoring · alerts · incidents · drift · governance · registry
        │            explanations · dashboard · auth · audit · retention · backup
        │
        ├─ engine:   schema · ingestion · preprocessing · detection (trusted artifacts) · evaluation
        │            drift · governance (paired comparison) · explainability (exact SHAP)
        │
        ├─ PostgreSQL 16 (or SQLite): users, events, predictions, alerts, incidents, drift,
        │            model versions and evaluations, explanations, audit log (Alembic migrations 0001–0005)
        └─ local files: uploaded CSVs (retention policy), experiment runs and model artifacts (SHA-256 allowlist)
```

No component makes outbound network calls. Background work (imports, scoring, evaluations, drift analyses)
runs in the API process. A scoring run either completes or fails as a whole, so it never leaves partial
predictions.

## Data and model flow

```
CSV / replay / (later) Zeek, NetFlow
        │
        ▼
ingestion.import_csv ──► ImportRecord (hash, counts, rejected rows, schema id)
        │ accepted rows
        ▼
preprocessing.Preprocessor (fit on train only, JSON state, version_id)
        │
        ▼
detection.TrustedArtifactManifest ──► detection.Predictor
        │                                   │ prediction rows (model + pp versions, status)
        ▼                                   ▼
evaluation (metrics, splits, benchmark)    services.scoring ─► alerts ─► incidents  (API + PostgreSQL)
        │
        ▼
experiments.run_experiment ──► result.json + report.md (provenance-labelled)
```

## Module map

| Module | Responsibility | Spec | Status |
|---|---|---|---|
| `adaptive_ids.schema` | Versioned feature schemas, leakage guards | §8 | Implemented |
| `adaptive_ids.ingestion` | CSV validation, import records, rejected rows | §7 | Implemented (CSV) |
| `adaptive_ids.preprocessing` | Shared transform interface | §8 | Implemented |
| `adaptive_ids.detection` | Trusted artifact loading, traceable inference | §9, §17 | Implemented |
| `adaptive_ids.evaluation` | Metrics, splits, benchmark | §9, §15 | Implemented |
| `adaptive_ids.experiments` | Reproducible runs and reports | §15, §16 | Implemented |
| `adaptive_ids.research` | Backup, inventory, synthetic demo data | §2, §22 | Implemented |
| `adaptive_ids.drift` | Feature, prediction, performance and suspected concept drift; ADWIN on bounded signals; controlled experiments | §10, §15 | Implemented (Phase 5) |
| `adaptive_ids.explainability`, `services.explanations` | Exact SHAP (TreeExplainer) for tree models, verified against the stored prediction and the model output; per-alert and summary views | §11 | Implemented ([model-explanations.md](model-explanations.md)) |
| `adaptive_ids.services.registry` | Model lifecycle: register from run, gated approve, activate, rollback | §14 | Implemented (Phases 3 and 6) |
| `adaptive_ids.governance`, `services.governance` | Versioned evaluation protocol; paired candidate-vs-baseline comparison; restorability checks; comparison reports | §11, §14 | Implemented (Phase 6) |
| `adaptive_ids.permissions`, `api.deps.allow`, `api.hardening` | Role → permission map, per-route enforcement, security headers, body-size limits | §17 | Implemented (Phase 7) |
| `adaptive_ids.services.retention`, `services.backup` | Configurable retention with evidence protection; verified backup and restore | §17 | Implemented (Phase 7) |
| `adaptive_ids.research.msc_reproduction` | Re-implementation of the MSc notebook's supervised protocol with controlled variants | §22 | Implemented (Milestone 1) |
| `adaptive_ids.db` + `migrations/` | SQLAlchemy models, Alembic migrations (PostgreSQL target) | §4 | Implemented (Phase 3) |
| `adaptive_ids.services` | Imports, scoring, alerts, incidents, dashboard, auth, audit | §6, §7, §12, §13, §17 | Implemented (Phase 3) |
| `adaptive_ids.api` (FastAPI) | HTTP API, roles, safe errors | §4, §17, §18 | Implemented (Phase 3) |
| `apps/web` (React, TypeScript, Vite, Recharts) | Dashboard and the 12 sidebar pages, including the alert explanation view | §5, §6, §11, §19 | Implemented (Phases 4–7, 1.0) |

## Provenance

`adaptive_ids.provenance.Provenance` labels all data and results as one of:
`original_dissertation`, `baseline_reproduction`, `controlled_experiment`,
`live_observation` or `synthetic_demo`. Reports print the label as a banner. The
experiment config refuses combinations that would blur these categories, for
example a new run claiming `original_dissertation`, or a retrained model labelled
as a baseline reproduction.

## Security decisions

- Model pickles are loaded only after a SHA-256 allowlist check. Preprocessor state is JSON.
- Imported CSVs are read as text and validated before numeric conversion, with size and row limits.
- Data, captures and model binaries are git-ignored by default, and a CI test checks the tracked files.
- No network calls, no external AI services, no API keys.
- Every API route declares one permission. The threat model, the full controls matrix and the operations
  runbook are in [`phase-7-security.md`](phase-7-security.md).

## Key decisions

| Decision | Why |
|---|---|
| Modular monolith, single process | Easy to install and audit for a local-first tool; the module boundaries allow splitting later if a pilot needs it |
| Provenance label on every dataset and result | Synthetic, reproduced and experimental numbers must never be confused |
| Predictions and analyst decisions in separate tables | A model output can never be mistaken for a confirmed attack |
| Four separate drift signals; no automatic retraining | They have different causes and need different responses; promotion stays a human decision |
| Non-inferiority gates on paired data | "Better on average" can hide a regression that matters operationally, such as false positives |
| Exact SHAP only, verified before display | An approximate or mismatched explanation is worse than none in an investigation |
| Batch import, not live capture (1.0) | It covers authorised offline analysis and pilots; live ingestion waits for evidence that it is needed |
