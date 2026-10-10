# Adaptive IDS — ML-based network anomaly detection with concept drift

A research-driven network intrusion detection platform that extends an MSc
project. This repository is being built in small, tested milestones.

> **Current state: Milestone 1 (reproducible ML baseline) in progress.**
> The ML engine and the reproduction tooling are implemented and tested. The
> original dissertation baseline has **not yet been reproduced**, because the
> original notebooks, data and model files are not in this repository yet.
> See [`docs/milestone-1-status.md`](docs/milestone-1-status.md).
> No original research results are claimed here.

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

The API, database, dashboard, drift monitoring, explanations and model registry
are later phases. See [`docs/architecture.md`](docs/architecture.md).

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

## Demo on synthetic data

```powershell
adaptive-ids make-synthetic                       # data/sample/flows_SYNTHETIC_demo.csv
adaptive-ids run configs/experiments/synthetic-demo.json
# -> experiments/runs/synthetic-demo-rf-<time>/report.md
```

The synthetic classes are easy to separate, so near-perfect scores are expected.
They show that the software works, **not** how well it detects intrusions.

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

## Layout

```
src/adaptive_ids/   schema, provenance, ingestion/, preprocessing/, detection/,
                    evaluation/, experiments/, research/, cli.py
configs/            schemas/ and experiments/ (JSON)
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
