# Case study: from an MSc notebook to a governed, explainable intrusion-detection platform

*Muhammad Haider Abbas · Adaptive IDS 1.0.0 · October 2026*

## Summary

An MSc dissertation reported near-perfect intrusion-detection accuracy (99.6–99.7 %). Before building a
product on it, I reproduced the result exactly. The reproduction showed the result came from an annotation
column leaking into the features and from a random split of a single file. On the dataset's official
protocol, the same models detect about 62 % of attacks. Detection includes attack types the model never saw
in training.

Adaptive IDS is built around that lesson. It never invents a result. It never treats a prediction as a
confirmed attack. It never promotes a model without paired evidence and an explicit, audited approval. It
runs entirely on one machine.

**Status:**

- **Scope:** version 1.0.0 meets the specification's definition of done: local operation, validated import,
  predictions, alert investigation with explanations, drift monitoring, reproducible model comparison, gated
  approval, rollback, exports and audit.
- **Tests:** 206 automated Python tests and 18 web tests. CI runs on Ubuntu, Windows and PostgreSQL, with
  blocking security scans.
- **What it doesn't have:** no customer pilot has run yet. The plan for one is in
  [Phase 9](phase-9-commercial-validation.md).

## 1. The problem

Machine-learning intrusion detection has a credibility problem in practice:

- **Opaque scores.** An analyst gets a score but not a reason, so they either ignore the tool or trust it
  blindly.
- **Silent decay.** Networks change, and detection quality degrades without anyone noticing.
- **Ungoverned model changes.** A retrained model is swapped in because it looks better on some test, with no
  paired comparison and no way back.
- **Unreliable headline numbers.** Leakage, convenient splits, synthetic data presented as real, and models
  loaded from untrusted pickle files.

## 2. Starting point: reproduce before improving

The dissertation notebook was reviewed statically, then its supervised protocol was re-implemented and run
with the notebook's own library versions ([full review](msc-notebook-review.md)).

| Finding | Evidence |
|---|---|
| **All 15 reported supervised metrics reproduced exactly** (Random Forest, XGBoost, LightGBM; 4 decimal places) | `results/msc-reproduction-nsl-kdd.json` |
| The data was **NSL-KDD `KDDTest+`, not CIC-IDS2018** as the results table said: the CIC download had failed silently | Saved cell outputs |
| Column 42, NSL-KDD's **per-record difficulty level** (annotation metadata, not traffic), was used as a feature | Reproduced feature list |
| Preprocessing was fitted on all rows before splitting | Notebook code |

Controlled variants, each changing one factor (Random Forest):

| Variant | Accuracy | Attack recall | False-positive rate |
|---|---|---|---|
| As the notebook ran | 99.60 % | 99.84 % | 0.72 % |
| Without the difficulty column | 98.67 % | 98.79 % | 1.49 % |
| Leak-free (fit on training rows only) | 98.67 % | 98.83 % | 1.54 % |
| **Official split** (train on KDDTrain+, test on KDDTest+) | **77.15 %** | **61.86 %** | 2.64 % |

The difficulty column multiplied missed attacks by about 8 (4 → 31). Preprocessing leakage barely mattered
here. The random split of one file hid the real difficulty: KDDTest+ contains attack types that never appear
in training. The platform therefore uses the leak-free official protocol as its baseline, enforces it in
the NSL-KDD schema (the difficulty column is excluded), and refuses to evaluate a model on its own training
file.

## 3. What was built

A modular monolith: a Python engine with a FastAPI API (SQLAlchemy, Alembic, PostgreSQL or SQLite) and a
React/TypeScript dashboard. Everything runs locally, with no cloud services and no external AI APIs.
([Architecture](architecture.md).)

```
CSV flows ──► validated import ──► versioned preprocessing ──► hash-verified model ──► predictions
   (schema, limits,                  (fit on train only,           (SHA-256 allowlist;         │
    per-row rejection)                JSON state)                   never untrusted pickles)   ▼
                                                                      alerts ─► investigation ─► incidents
                                                                        │         (SHAP explanation,
                                                                        │          analyst decisions)
                          drift monitoring ◄── predictions + labels     │
                          (4 separate signals) ──► review, never auto-retrain
                          candidate model ──► paired evaluation ──► gated approval ──► restore check ──► activate / rollback
```

### Design decisions that matter

1. **Provenance on every number.**
   - Each result is labelled `baseline_reproduction`, `controlled_experiment`, `synthetic_demo` (and so on).
   - Synthetic data is bannered everywhere it appears.
   - The dashboard shows "confirmed attacks: unavailable" until an analyst decides.
2. **Predictions and decisions are stored apart.** Model output and analyst decisions live in separate
   tables. Severity comes from documented rules, not from the uncalibrated score.
3. **Trusted artifacts only.** A pickle or joblib file is deserialised only if a person listed it in a
   manifest with its SHA-256.
4. **Drift is four signals, not one.** Feature, prediction, performance and suspected concept drift are kept
   apart:
   - **Controlled experiments:** feature drift was detected in 5 of 5 trials within one window. Concept
     drift (labels flipping while inputs stay the same) was invisible to every input-based detector, and
     was found by ADWIN on the error rate in 5 of 5 trials, after a mean of 109 events.
   - **False alarms:** none in the no-drift runs.
   - **Never automatic:** drift doesn't retrain or promote a model.
   ([Phase 5](phase-5-drift.md).)
5. **Governance by non-inferiority.**
   - **Same events:** a candidate and the active model are scored on the same labelled events.
   - **Statistics:** paired-bootstrap confidence intervals of the differences are judged against margins
     for recall, F1 and false-positive rate.
   - **Approval:** a failed gate can only be overridden with a written, audited justification.
   - **Restorability:** activation and rollback first prove the artifact still loads and reproduces 25
     recorded predictions.
   ([Phase 6](phase-6-governance.md).)
6. **Explanations that are checked before they are shown.**
   - **Method:** exact TreeExplainer SHAP.
   - **Same prediction:** before showing an explanation, the system re-scores the event with the same
     hash-verified artifact. The result must match the stored prediction.
   - **Additivity:** the contributions must add up to the model's output within 1e-6.
   - **Independent check:** a test compares the values with brute-force Shapley values.
   ([Explanations](model-explanations.md).)
7. **Security by default.** Phase 7 added:
   - **Accounts:** per-route permissions (admin, analyst, viewer), throttled sign-in, idle sessions and
     password policy.
   - **HTTP:** strict CSP and security headers, request size limits, and formula-safe CSV exports.
   - **Data:** retention that keeps evidence, and verified backup and restore.
   - **CI:** blocking dependency and static-analysis scans.

   ([Phase 7](phase-7-security.md).)

## 4. Results on public data (NSL-KDD)

### Governance: a better-looking model that shouldn't be approved

The Random Forest baseline (trained only on KDDTrain+) was compared in the platform with an ExtraTrees
candidate on all 22,544 KDDTest+ events:

| | Candidate | Baseline | Difference [95 % CI] |
|---|---|---|---|
| Attack recall | 61.36 % | 58.05 % | +3.30 pp [+2.97, +3.67] |
| False-positive rate | 4.12 % | 2.46 % | +1.66 pp [+1.40, +1.93] |
| F1 | 74.61 % | 72.61 % | +2.01 pp [+1.71, +2.31] |

The candidate is better on accuracy, recall and F1, and most teams would ship it. But its false-positive rate
rises by more than the 0.5-point margin, so the protocol's verdict is **fail**. Whether that trade-off is
acceptable is an operational decision. The platform makes it an explicit, justified, audited one.

### Explanations: tracing a class of false positives to one learned feature

The baseline raised 7,689 alerts on KDDTest+, 239 of them on records the dataset labels `normal`.

- **One alert:** the explanation of a typical false positive (a UDP record predicted `teardrop` with score
  0.92) shows a single dominant contribution: `wrong_fragment = 3` adds +0.47 to the score.
- **What the training data says:** in KDDTrain+, fragment errors occur in **none** of the 67,343 normal
  records; they occur only in teardrop and pod attacks.
- **The pattern:** KDDTest+ has 52 normal records with fragment errors, and the model flags **all 52**. That
  is 22 % of all false positives, from one learned rule.
- **What it gives people:** an analyst learns what to check in the traffic, and a modeller learns exactly
  what the training data is missing.

Group summaries over seeded samples of 300 events per group show what drives detections, false positives
and misses. The largest additivity error across 839 explanations was 4.7e-14.

### Deployment cost

All measured on a 4-core, 16 GB machine ([benchmark](phase-9-commercial-validation.md#1-deployment-requirements-measured)):

- **Batch scoring:** 2,400–3,800 events per second. **Import:** 7,000–9,600 events per second.
- **Explanation, first view:** about 0.1–0.4 s, depending on model size.
- **Peak memory:** under 1.4 GB.
- **Storage:** about 1 GB per million stored events.

A small site's daily flow volume scores in minutes on commodity hardware.

## 5. Limitations

- **Datasets:** NSL-KDD is old and synthetic in origin. No CIC-IDS2018 result exists yet, and no claim is
  made about modern traffic.
- **Detection performance:** on attack types not seen in training it is modest (about 60 % recall at a
  2–4 % false-positive rate). The platform makes this visible rather than hiding it.
- **Input:** batch import of flow files only, with no live capture.
- **Accounts:** no SSO or MFA, and a single tenant.
- **Explanations:** tree models only. They describe the model, not the network.
- **Validation:** no user interviews or pilot yet. They are planned, with success and exit criteria fixed in
  advance.

## 6. What I'd do next

1. Run the [interviews and an authorised pilot](phase-9-commercial-validation.md) before building anything
   commercial.
2. Add CIC-IDS2018 (or UNSW-NB15) with a time-based split, and repeat the governance comparison.
3. Use the explanation summaries to drive training-data fixes, for example benign fragmentation, and
   measure the effect through the same evaluation gates.
4. Add live flow ingestion (Zeek or NetFlow) only if the pilot shows that batch import is the bottleneck.

## Reproduce everything

```bash
pip install -r requirements.lock.txt && pip install -e . --no-deps && python -m pytest
adaptive-ids msc-reproduce --test data/raw/nsl-kdd/KDDTest+.txt --train data/raw/nsl-kdd/KDDTrain+.txt
adaptive-ids demo --admin admin && adaptive-ids serve
python tools/benchmark_deployment.py --synthetic 100000
```

The public NSL-KDD files are not included. Their SHA-256 hashes are in `msc-notebook-review.md`.
