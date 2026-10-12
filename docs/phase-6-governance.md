# Phase 6 — Model registry and governance

Status: **implemented and tested.** Comparison engine in `src/adaptive_ids/governance/`, persistence and
API in `services/governance.py`, `services/registry.py` and `api/routes/governance.py`, UI under
**Model Management**, migration `0003`.

> Nothing in the system promotes a model on its own: not drift, not a passing evaluation. A candidate
> becomes active only through two explicit, audited admin actions (approve, then activate), and the
> server refuses approval without a valid evaluation.

## What every model version records (spec §11)

| Item | Where |
|---|---|
| Version id, artifact SHA-256, format | `model_versions.version_id`, `artifact_sha256`, `artifact_format` |
| Training dataset, split, config | `training_dataset`, `training_config`, `evaluation.dataset` (file hash), `source_run` |
| Feature schema and preprocessing versions | `feature_schema` (full copy) + `feature_schema_id`, `preprocessor` (fitted JSON state) + `preprocessing_version` |
| Software versions | `software_versions` (from the run's environment capture) |
| Evaluation results | `evaluation.test` (the run's held-out test set) and every candidate evaluation (`model_evaluations`) |
| Lifecycle history | `model_status_changes` (who, when, from → to, reason) and the audit log |
| Approval basis | `approval_evaluation_id`, `approval_override` |
| Restorability | `reference_sample` (25 recorded inputs and outputs) and `restore_check` (latest result) |

## Candidate evaluation protocol (`configs/evaluation-protocol.json`, v1.0.0)

A candidate is scored **side by side with the baseline**, the model active when the evaluation starts, on
the **same labelled import**, event by event, against the same labels. "Attack" means any label other than
the candidate's benign label. Each model "flags" an event under its own decision rule (the rule that
raises alerts in production).

| Gate | Kind | Rule (v1.0.0) |
|---|---|---|
| Labelled events | validity | ≥ 200 events scored by every compared model |
| Each class | validity | ≥ 30 attack and ≥ 30 benign events |
| Failed predictions | validity | each model fails to score ≤ 1 % of events |
| Not the training file | validity (checked before starting) | the import's SHA-256 differs from the training file of the candidate **and** the baseline |
| Attack recall | performance | lower 95 % bound of (candidate − baseline) ≥ −1.0 pp |
| F1 | performance | lower 95 % bound of (candidate − baseline) ≥ −1.0 pp |
| False-positive rate | performance | upper 95 % bound of (candidate − baseline) ≤ +0.5 pp |
| Absolute requirements | performance | optional `min_attack_recall`, `max_false_positive_rate` (off by default) |

- **Intervals.** Paired bootstrap, 1,000 resamples, fixed seed. Every attack/benign metric depends only on
  the 8 (truth × candidate × baseline) cell counts, so the bootstrap resamples those counts from a
  multinomial. That is exactly equivalent to resampling events, and costs the same for any data size. A
  test checks it against a row-level bootstrap.
- **Non-inferiority, not significance.** A gate is judged on the interval against a margin, not on the
  point estimate and not on a p-value. McNemar's test is reported for context only.
- **Verdicts.** `pass` means every gate passed. `fail` means the evidence is valid but a performance gate
  failed. `insufficient_evidence` means a validity gate failed.
- **No baseline** (nothing active yet): only the validity gates and the absolute requirements apply.

## Approval, overrides and staleness

| Situation | Result |
|---|---|
| No completed evaluation | 409, evaluate first |
| `pass` | Approve with a reason |
| `fail` | 409 unless `override: true` **and** a justification of at least 20 characters. Audited as `model.approve_override` with the failed gate ids, and the lifecycle reason is prefixed `[override of failed gates: …]` |
| `insufficient_evidence` | 409, **cannot** be overridden |
| Protocol file changed since the evaluation | 409, re-evaluate under the current version |
| Active model changed since the evaluation | 409, re-evaluate against the current baseline |
| `override` on a passing evaluation | 400 |

## Restorability (spec: "validate that the previous approved model can be restored")

Approval, every activation and every rollback first run `verify_restorable`. It checks that:

1. the artifact file is present;
2. its SHA-256 matches the registry (never the file itself);
3. it loads through the trusted loader, with any version warnings recorded;
4. the stored preprocessing state rebuilds to the recorded `preprocessing_version`;
5. it reproduces the **25 recorded predictions** (class exactly, score within 1e-9) captured from the
   evaluation it was approved on.

If any check fails, the action is refused and the current model stays active. An admin can also run the
check on demand (**Verify now**, `POST /api/models/{id}/verify-restore`), which stores the result and
audits it as `model.restore_check`. The check deliberately bypasses the in-memory model cache, so it
proves the artifact on disk.

## API

| Method | Path | Who |
|---|---|---|
| GET | `/api/governance/protocol` | any user |
| POST | `/api/models/{id}/evaluations` `{import_id}` | admin (runs in the background) |
| GET | `/api/models/{id}/evaluations`, `/api/evaluations`, `/api/evaluations/{id}` | any user |
| GET | `/api/evaluations/{id}/report.md` | any user (export is audited) |
| POST | `/api/models/{id}/approve` `{reason, evaluation_id?, override?}` | admin |
| POST | `/api/models/{id}/activate` `{reason}` (rollback = activating an archived, approved version) | admin |
| POST | `/api/models/{id}/verify-restore` | admin |

## Worked example on real data (NSL-KDD, public)

Both models were trained **only on KDDTrain+** (difficulty column excluded) and evaluated in the
platform on the **KDDTest+** import. That is the dataset's published protocol and the leak-free
counterpart of the dissertation's setup (see `docs/msc-notebook-review.md`). Provenance:
`controlled_experiment`.

1. Random Forest (the notebook's settings) evaluated with no baseline: `pass`. Approved with the
   restore check (25 of 25 recorded predictions reproduced), then activated.
2. An ExtraTrees candidate evaluated against it on the same 22,544 events:

| Metric | ExtraTrees (candidate) | Random Forest (baseline) | Difference [95 % CI] |
|---|---|---|---|
| Attack recall | 61.36 % | 58.05 % | +3.30 pp [+2.97, +3.67] |
| False-positive rate | 4.12 % | 2.46 % | +1.66 pp [+1.40, +1.93] |
| F1 | 74.61 % | 72.61 % | +2.01 pp [+1.71, +2.31] |
| Accuracy | 76.23 % | 75.06 % | +1.17 pp [+0.93, +1.39] |

Verdict: **fail**. The candidate detects more attacks, but its false-positive rate rises by more than
the 0.5 pp margin. Whether that trade-off is acceptable is an operational decision, so the platform
leaves it to an admin's justified override rather than deciding. The full exported report is
`docs/results/nsl-kdd-candidate-evaluation.md`.

An attempt to evaluate on the KDDTrain+ import was refused (the import is the training file).

These Random Forest numbers (75.1 % accuracy, 58.1 % recall) are lower than the `official_split`
reproduction variant (77.2 %, 61.9 %). The platform model trains on 80 % of KDDTrain+ (the rest is its
own held-out test set), uses the multi-class attack labels, and has no feature selection or scaling.
Both runs say the same thing: on unseen attack types, roughly 4 in 10 attacks are missed.

### Repeat it

```bash
adaptive-ids prepare-nsl-kdd data/raw/nsl-kdd/KDDTrain+.txt data/processed/nsl-kdd/KDDTrain+.csv
adaptive-ids prepare-nsl-kdd data/raw/nsl-kdd/KDDTest+.txt  data/processed/nsl-kdd/KDDTest+.csv
adaptive-ids run configs/experiments/nsl-kdd-rf.json
# copy the config with "estimator": "ExtraTreesClassifier" and a new experiment_id for a candidate
adaptive-ids serve   # then: register runs, import KDDTest+.csv with schema nsl-kdd@1.0.0, evaluate, approve, activate
```

## Synthetic demo

`adaptive-ids demo --admin <user>` now:

1. evaluates the first model on the baseline week before approving it;
2. after the drift step, trains a second SYNTHETIC candidate (a depth-3 decision tree);
3. evaluates that candidate against the active forest on the replay week and leaves it as a candidate.

The tree catches one more attack but raises 12 false positives, so the verdict is `fail` (F1 and
false-positive-rate gates).

## Screenshots

| | |
|---|---|
| [Candidate evaluation](screenshots/ui-09-candidate-evaluation.png) | [Candidate evaluation (dark)](screenshots/ui-12-candidate-evaluation-dark.png) |
| [Approve with override](screenshots/ui-10-approve-override.png) | [Model governance and restorability](screenshots/ui-11-model-governance.png) |

## Limitations

- Labels come from the imported file. They are not analyst-confirmed outcomes.
- Gates use the binary attack-vs-benign view; per-class regressions are visible in the run's test metrics
  but not gated.
- The training-data guard compares whole-file hashes. Overlapping rows inside a different file are not
  detected, so keep evaluation data separate from training data at the source.
- A model approved before Phase 6 has no recorded sample. Its restore check reports `partial` (hash, load
  and preprocessing only).
