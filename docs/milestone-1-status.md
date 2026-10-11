# Milestone 1 — Reproducible ML baseline: status

_Last updated: 2026-10-10_

Milestone 1 (spec §22) is **not complete**. The software needed to reproduce the
baseline exists and is tested. The baseline itself has **not** been reproduced,
because the original research files (notebooks, datasets, trained models and
results) have not been provided to this repository yet.

No accuracy, detection rate or other result from the original dissertation is
claimed anywhere in this repository.

## 1. What was received and inspected

| Item | What it contains | Usable for reproduction? |
|---|---|---|
| Repository at start | `README.md` only (one line) | No |
| `final_project.docx` (uploaded 2026-10-10) | Transcripts of earlier planning chats ("Chat 01"–"Chat 04"), not the dissertation. Includes: candidate datasets (CIC-IDS2018, UNSW-NB15, CIC-IDS2017); a recalled 10-stage notebook workflow (audit, cleaning/leakage, feature engineering, splitting, class weighting, SMOTE, evaluation, SHAP, drift, reporting); the original environment (Python 3.10.11, PyCharm, GTX 1050); the original folder path; a mention of "86%" (apparently the dissertation grade). | No. It says itself that the datasets, training runs, saved models and metrics were **unverified**. |

Facts I'm treating as **unverified context** (not evidence) until the original files are inspected:

- which dataset(s) and which day files were actually used;
- the feature list, label encoding, cleaning rules and split;
- whether SMOTE was applied, and whether it was applied only to training data;
- which model was final, and how it was saved (`joblib.dump` was reported);
- every metric value.

The "86%" mentioned in the transcripts appears to be the dissertation **grade**. It is not treated as a model accuracy.

## 2. Deliverables checklist (spec §22)

| Deliverable | Status | Where |
|---|---|---|
| Separate backup of the original project | **Tool ready, not run** (needs your PC) | `adaptive-ids backup` — hash-verified, read-only copy, refuses to overwrite |
| Inventory of available files | **Tool ready, not run** on the original | `adaptive-ids inventory` — static, never executes code or unpickles |
| One verified dataset and its schema | **Blocked** — dataset not provided | Candidate schema: `configs/schemas/cse-cic-ids2018.candidate.json` (status `unverified`) |
| One trusted model and compatible preprocessing | **Blocked** — model not provided | Trusted loader: `adaptive_ids.detection`; manifest example in `models/` |
| Reproduced predictions and metrics | **Blocked** | Runner ready: `adaptive-ids run configs/experiments/baseline-reproduction.template.json` |
| Baseline report | **Blocked** (generator ready and tested) | Written to `experiments/runs/<id>/report.md` and `result.json` |
| Pinned dependency environment | **Provisional** | `requirements.lock.txt` (Python 3.10). Must be re-pinned to the original scikit-learn version before the original model is loaded |
| Automated tests for validation and inference | **Done** — 70 engine tests passing (89 including the Phase 3 API tests) | `tests/`, CI in `.github/workflows/ci.yml` |
| Documented list of unresolved issues | **Done** (below) | This file |

## 3. What is implemented and tested

- **Feature schemas** (`schema.py`): versioned and hashed. The label, timestamp, ID and excluded columns can never be features (leakage guard).
- **CSV ingestion** (`ingestion/`): chunked reading of untrusted CSVs; size and row limits; header whitespace stripping and column mapping; per-row rejection with reasons (invalid type, non-integer, missing, infinite, out of range, missing label, repeated header lines as found in CIC exports); duplicate counting or dropping; SHA-256 checking against an expected hash; cancellation; progress callback; an import record covering every field in spec §7. If the file is missing, the import fails. Another dataset is never substituted.
- **Preprocessing** (`preprocessing/`): one interface for training, evaluation and inference. It enforces the schema's feature order. Imputation and scaling are **off by default**. Statistics are fitted on the training partition only and can't be refitted. Rows that are still non-finite are rejected, not guessed. State is saved as JSON with a tamper-evident version ID.
- **Trusted model loading** (`detection/artifacts.py`): an artifact is loaded only if it is listed in a manifest and its SHA-256 matches. Load warnings (for example, a scikit-learn version mismatch) are recorded.
- **Inference** (`detection/predictor.py`): every output row carries the event ID, class, score, a score kind marked *uncalibrated*, the threshold and rule, model and preprocessing versions, a timestamp, a status, the error and an explanation reference. It detects feature-set mismatches between model and schema. Model failures raise an error instead of returning output.
- **Evaluation** (`evaluation/`): per-class and macro/weighted precision, recall and F1; confusion matrix; attack-vs-benign FPR and FNR. There are chronological, seeded stratified, and pre-assigned-column splits, each with an index-hash manifest and an overlap check. A latency and throughput benchmark is documented.
- **Experiments** (`experiments/`): JSON configs with validation. A `baseline_reproduction` run must use the original trusted artifact, and no new run may label itself `original_dissertation`. Each run records the environment (Python, packages, CPU, RAM, GPU if present, git commit) and writes a report that compares the reproduction against the dissertation's reported numbers.
- **Synthetic demo data** (`research/synthetic.py`): the file name must contain `SYNTHETIC`, classes are prefixed `SYNTH_`, a provenance sidecar file is written, and malformed rows are injected on purpose. Its perfect scores only show that the software works. They are not research evidence.

## 4. Unresolved issues

1. **Original project files not available.** Run `adaptive-ids backup` and `adaptive-ids inventory` on the original folder (see `docs/reproducing-the-baseline.md`), then share the generated `inventory.md`. Do not share private data.
2. **Exact dataset unknown.** CIC-IDS2018, CIC-IDS2017 and UNSW-NB15 were all mentioned. The inventory's `referenced_data_files` will show which files the notebooks actually load.
3. **Feature list unknown.** The CIC-IDS2018 schema is a *candidate* built from the public CSV header. Edit a copy to match the notebooks exactly, then mark it `verified`.
4. **Original split unknown.** Recover `test_size` and `random_state` from the inventory. If the held-out test set was saved, evaluate with `split.method = "all_test"`. Note that the same `train_test_split` arguments reproduce the same split only when the row order and the cleaning are identical.
5. **Preprocessing outside a sklearn `Pipeline`.** If a scaler or encoder was fitted separately, its fitted object must also be recovered. Refitting it on test data would invalidate the reproduction.
6. **SMOTE leakage risk.** If SMOTE was applied before the train/test split, the original metrics are optimistic. Record this as a discrepancy. Do not "fix" the original run silently.
7. **Dependency versions.** The original scikit-learn version is unknown. Loading a model under a different version can change predictions, and the runner records any warning. Re-pin `requirements.lock.txt` once known.
8. **CIC timestamp format.** CSE-CIC-IDS2018 timestamps are day-first (`14/02/2018 08:31:01`). Set `split.timestamp_format` to `"%d/%m/%Y %H:%M:%S"` for chronological splits so dates aren't misread.
9. **Python 3.10 environment on Windows** has not been exercised on the target laptop yet. CI covers `windows-latest` with Python 3.10.

## 5. Work beyond Milestone 1

At the user's request, Phase 3 (backend and persistence, `docs/phase-3-backend.md`), Phase 4
(web dashboard, `docs/phase-4-frontend.md`) and Phase 5 (drift monitoring, `docs/phase-5-drift.md`) have been
built on top of the engine. It contains no model improvements, so the §22 rule ("do not begin
major model improvements until this milestone is complete") still holds: the only model that runs
through it is the SYNTHETIC demo model.

## 6. Not started (deliberately)

Not started yet:
SHAP explanations, candidate-vs-baseline comparison workflow (Phase 6), and model
improvements of any kind (blocked on Milestone 1).
`docs/architecture.md` shows where each one fits on top of the modules above.
