# Changelog

All notable changes. Dates are UTC. This project follows semantic versioning from 1.0.0. Entries before
1.0.0 are development milestones; they were not released or tagged.

## Unreleased

### Added
- **CSE-CIC-IDS2018 support:**
  - a verified schema (`cse-cic-ids2018@1.0.0`) checked against the real day files;
  - a loader that rejects and counts the files' known defects;
  - `adaptive-ids cic-ids2018-sample`.
- **Chronological study:** `adaptive-ids cic-ids2018-study` compares static, retrain-always and governed models
  on later, unseen days, with drift measurements. Results and write-up are in
  `docs/cic-ids2018-evaluation.md`.
- **Benchmark tool:** `--max-import-rows` option, for full day files of more than a million rows.

## 1.0.0 — 2026-10-12 — first complete release

Completes the spec's definition of done: local start, import or replay of authorised data, validation,
predictions, alert investigation, **model explanations**, drift monitoring, reproducible model comparison,
gated approval, safe rollback, exports and audit records.

### Added
- **Model explanations (SHAP).** Exact TreeExplainer attributions on every alert, computed from the hash-
  verified artifact and recorded preprocessing. They are shown only after the stored prediction is reproduced
  and the contributions add up to the model output. Explanations are stored for later review.
  `adaptive-ids explain-summary` produces per-group summaries. See `docs/model-explanations.md`.
- **Release files.** `LICENSE` (all rights reserved), `THIRD_PARTY_NOTICES.md`, `SECURITY.md`, `CITATION.cff`
  and this changelog.
- **Portfolio material.** A recorded demo walkthrough script, a technical case study, a release checklist and
  a public-release audit.
- **Phase 9 preparation.** A measured deployment benchmark, deployment requirements, a user-interview guide
  and a pilot plan.

### Changed
- `shap` 0.49.1 is a pinned dependency (with `numba` and `llvmlite`).
- The Reports page lists the evaluation and explanation outputs that now exist.

## 0.7 — 2026-10-12 — Phase 7: security and testing
- Per-route permission model with a read-only viewer role.
- **Accounts:** sign-in throttling, idle sessions, password policy, password change and reset, role changes.
- **HTTP:** security headers and CSP, request size limits, spreadsheet-formula escaping in exports, safe errors.
- **Data:** configurable retention with evidence protection; verified backup and restore.
- **Dependencies:** upgrades that clear all pip-audit findings.
- **CI:** blocking `pip-audit` and `bandit`, plus a fresh-setup job.

## 0.6 — 2026-10-11 — Phase 6: model registry and governance
- Versioned evaluation protocol: candidate and baseline on the same labelled events, paired-bootstrap
  confidence intervals and non-inferiority gates.
- Gated approval with audited overrides; restorability checks before approval, activation and rollback.
- MSc notebook reproduction: all 15 reported supervised metrics reproduced, with controlled variants that
  show the effect of the difficulty column and of the split.

## 0.5 — 2026-10-11 — Phase 5: drift monitoring
- Feature, prediction, performance and suspected concept drift, kept separate.
- Drift events with a review workflow, reports, and controlled drift experiments.

## 0.4 — 2026-10-11 — Phase 4: web dashboard
- React + TypeScript dashboard for all twelve sections, with light and dark themes and a phone-width layout.

## 0.3 — 2026-10-10 — Phase 3: backend and persistence
- FastAPI, SQLAlchemy and Alembic (PostgreSQL target).
- Imports, scoring, alerts, incidents, the model registry, authentication and the audit log.

## 0.1 — 2026-10-10 — Milestone 1: reproducible ML baseline
- Feature schemas with leakage guards, CSV ingestion, preprocessing, trusted model loading, traceable
  inference, evaluation, an experiment runner, and research backup and inventory tools.
