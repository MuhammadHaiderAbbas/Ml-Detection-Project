# Architecture

Adaptive IDS is a **modular monolith**: one Python package with clear module
boundaries, and later a FastAPI layer and a React frontend on top. Every
displayed number must trace back to an import record, a model version, a
preprocessing version and an experiment or database record.

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
evaluation (metrics, splits, benchmark)    (Phase 3+) alerts ─► incidents
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
| `adaptive_ids.drift` | Feature/prediction drift, ADWIN on suitable signals | §10 | Phase 5 |
| `adaptive_ids.explainability` | SHAP for supported models | §11 | Phase 2–4 |
| `adaptive_ids.registry` | Model lifecycle, approval, rollback | §14 | Phase 6 |
| `apps/api` (FastAPI, SQLAlchemy, Alembic, PostgreSQL) | Persistence, alerts, incidents, auth, audit | §3, §12, §13, §17 | Phase 3 |
| `apps/web` (React, TypeScript, Vite, Recharts) | Dashboard and the 12 sidebar pages | §5, §6, §19 | Phase 4 |

## Provenance

`adaptive_ids.provenance.Provenance` labels all data and results as one of:
`original_dissertation`, `baseline_reproduction`, `controlled_experiment`,
`live_observation` or `synthetic_demo`. Reports print the label as a banner. The
experiment config refuses combinations that would blur these categories, for
example a new run claiming `original_dissertation`, or a retrained model labelled
as a baseline reproduction.

## Security decisions so far

- Model pickles are loaded only after a SHA-256 allowlist check. Preprocessor state is JSON.
- Imported CSVs are read as text and validated before numeric conversion, with size and row limits.
- Data, captures and model binaries are git-ignored by default.
- No network calls, no external AI services, no API keys.
