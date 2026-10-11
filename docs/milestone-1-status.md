# Milestone 1 — Reproducible ML baseline: status

_Last updated: 2026-10-11_

**The supervised baseline has been reproduced.** On 2026-10-11 the original research
notebook (`MSc_Project_Research.ipynb`) was provided. A static review and a
re-implementation of its protocol reproduced all 15 reported supervised metrics
(Random Forest, XGBoost and LightGBM × accuracy, precision, recall, F1 and ROC-AUC)
exactly, using the notebook's library versions. The full write-up is in
[`docs/msc-notebook-review.md`](msc-notebook-review.md).

Two caveats:

- **Retrained, not the original artifacts.** The notebook's saved `.pkl` models were
  not provided, so the models were retrained with the notebook's settings and seeds.
- **The data was NSL-KDD, not CIC-IDS2018.** The CIC-IDS2018 download failed and the
  notebook fell back to NSL-KDD `KDDTest+`. It also kept NSL-KDD's difficulty column as
  a feature and evaluated on a random split of a single file. Without the difficulty
  column, accuracy drops by about 1 point. On the dataset's official train/test split,
  accuracy is about 77–79 % and recall 62–64 %.

The unsupervised, deep-learning and drift results in the notebook are recorded as
*reported, not reproduced*.

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
| One verified dataset and its schema | **Done** for the data actually used: NSL-KDD (hashes recorded) | `docs/msc-notebook-review.md`; platform schema `configs/schemas/nsl-kdd.json` (difficulty excluded) |
| One trusted model and compatible preprocessing | **Retrained** — original `.pkl` files not provided | `adaptive_ids.research.msc_reproduction` (notebook preprocessing re-implemented step by step) |
| Reproduced predictions and metrics | **Done** — 15 of 15 supervised metrics match exactly | `adaptive-ids msc-reproduce`; `docs/results/msc-reproduction-nsl-kdd.json` |
| Baseline report | **Done** | `docs/msc-notebook-review.md` (reported vs reproduced, plus controlled variants) |
| Pinned dependency environment | **Done** for the reproduction: scikit-learn 1.3.2, xgboost 2.0.2, lightgbm 4.1.0 (the notebook's versions) | `docs/msc-notebook-review.md` §6; platform lock stays `requirements.lock.txt` |
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

1. **Original model artifacts not available.** The `.pkl` files saved by the notebook were not
   provided. If they turn up, register them in a trusted manifest (hash first, never unpickle
   unknown files) and evaluate them with `adaptive-ids run`.
2. **CIC-IDS2018 never used.** The notebook's CIC-IDS2018 path failed. The candidate schema
   `configs/schemas/cse-cic-ids2018.candidate.json` stays `unverified` until a CIC-IDS2018 run exists.
3. **Dissertation label.** The dissertation's tables say "CIC-IDS". They should say NSL-KDD
   KDDTest+ (random split, difficulty column included). This is for the author to correct. The
   repository does not edit the original work.
4. **Unsupervised and deep models not reproduced.** The autoencoders, Transformer, Isolation Forest,
   bootstrap CIs, McNemar tests and drift-scenario numbers are recorded as reported only.
5. **CIC timestamp format** (for future CIC-IDS2018 work): timestamps are day-first. Set
   `split.timestamp_format` to `"%d/%m/%Y %H:%M:%S"`.
6. **Windows target laptop** not exercised directly. CI covers `windows-latest` with Python 3.10.

## 5. Work beyond Milestone 1

At the user's request, Phase 3 (backend and persistence, `docs/phase-3-backend.md`), Phase 4
(web dashboard, `docs/phase-4-frontend.md`) and Phase 5 (drift monitoring, `docs/phase-5-drift.md`) have been
built on top of the engine, followed by Phase 6 (model registry and governance,
`docs/phase-6-governance.md`). The §22 rule ("do not begin major model improvements until this
milestone is complete") was respected: the baseline was reproduced first. The only real-data models
in the platform are NSL-KDD controlled experiments, which use the leak-free official split and are
labelled as such.

## 6. Not started (deliberately)

Not started yet:
SHAP explanations and model improvements of any kind. Model improvements are now
unblocked for NSL-KDD, but must be measured with the leak-free protocol. Phase 6
(model registry and governance, `docs/phase-6-governance.md`) provides that workflow.
`docs/architecture.md` shows where each one fits on top of the modules above.
