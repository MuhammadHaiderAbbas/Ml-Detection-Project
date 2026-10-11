# MSc notebook review and baseline reproduction

_Reviewed: 2026-10-11. Source: `MSc_Project_Research.ipynb` (uploaded; not committed;
SHA-256 prefix `9348e616128a6487`)._

The notebook was **read, not executed**. Its code and saved outputs were inspected
statically. The supervised part of its protocol was then re-implemented in
`src/adaptive_ids/research/msc_reproduction.py` and re-run (`adaptive-ids msc-reproduce`).
Provenance: **`baseline_reproduction`, retrained**. The notebook's saved `.pkl` models
were not provided, so these are new models trained with the notebook's settings, not
the original artifacts.

## 1. What the notebook actually used

| Question | Finding | Evidence |
|---|---|---|
| Dataset | **NSL-KDD `KDDTest+`** (22,544 rows × 43 columns), not CIC-IDS2018 | Saved cell 8 output: the CIC-IDS2018 downloads failed ("Downloaded 0 files"), then `NSL-KDD loaded: (22544, 43)`. The loader searched `data/raw`, while the CIC files were expected in `data/raw/cicids2018`, so it fell back. |
| Report label | The results table is titled "Classification results on **CIC-IDS** dataset" | Saved cell output "TABLE I". This label is wrong: the numbers are NSL-KDD numbers. |
| Split | Stratified random 70 / 10 / 20 (seed 42) of KDDTest+ only: 15,780 / 2,255 / 4,509 | Saved cell 11 output; reproduced exactly. KDDTrain+ was never used. |
| Features | 38 numeric columns, **including column 42, NSL-KDD's per-record difficulty level** | 39 numeric columns minus the constant column 19 = 38. Reproduced feature list ends in `"42"`. The difficulty level is annotation metadata derived from how many reference classifiers got the record right; it is not a traffic feature. |
| Categorical columns | `protocol_type`, `service` and `flag` silently dropped (not numeric) | Cell 11 keeps numeric dtypes only. |
| Preprocessing order | Median imputation, variance filtering, mutual-information selection (k = 40) and scaling were all **fitted on every row before splitting** | Cell 11. |
| Resampling | None applied (attack/benign ratio 1.32 is below the notebook's trigger) | Cell 11 logic. |
| Environment | Colab, Python 3.12, T4 GPU; scikit-learn 1.3.2, xgboost 2.0.2, lightgbm 4.1.0, river 0.21.0, shap 0.44.0 | Install cell and version printout. |

## 2. Reproduction result

The re-implementation was run with the notebook's library versions (scikit-learn 1.3.2,
xgboost 2.0.2, lightgbm 4.1.0, numpy 1.26.4, pandas 2.2.2, scipy 1.11.4) on Python 3.10.

**All 15 reported supervised numbers were reproduced exactly (to 4 decimal places)**,
and so were the split sizes and the 38-feature count.

| Model | Accuracy | Precision | Recall | F1 | ROC-AUC | Reported = reproduced? |
|---|---|---|---|---|---|---|
| Random Forest | 0.9960 | 0.9946 | 0.9984 | 0.9965 | 1.0000 | yes |
| XGBoost | 0.9971 | 0.9961 | 0.9988 | 0.9975 | 0.9999 | yes |
| LightGBM | 0.9967 | 0.9957 | 0.9984 | 0.9971 | 1.0000 | yes |

Full output, including data hashes, the environment and the code commit:
`docs/results/msc-reproduction-nsl-kdd.json`. The run is deterministic (two runs gave
identical results).

Data used (public NSL-KDD; files kept in git-ignored `data/raw/nsl-kdd/`):

- `KDDTest+.txt`: SHA-256 `fa46b0935342616aa83b7c2578db355b6a7aaabbc492248172c7a1e8b7ab8f84`
- `KDDTrain+.txt`: SHA-256 `1b86d2f957b33082081bba410fe129b475efebcc13c9014c3f447c8271aadf95`

## 3. What the reported numbers measure: controlled variants

Each variant changes **one** factor from the notebook protocol. The test set has 4,509
records in the first three rows (2,567 attacks) and 22,544 in the last.

| Variant | What changes | RF acc. | RF recall | RF FPR | RF FP / FN | XGB acc. | LGBM acc. |
|---|---|---|---|---|---|---|---|
| `dissertation` | the notebook protocol as it ran | 0.9960 | 0.9984 | 0.72 % | 14 / 4 | 0.9971 | 0.9967 |
| `no_difficulty` | drop column 42 only | 0.9867 | 0.9879 | 1.49 % | 29 / 31 | 0.9843 | 0.9862 |
| `leak_free` | no column 42; split first, fit every step on training rows only | 0.9867 | 0.9883 | 1.54 % | 30 / 30 | 0.9843 | 0.9869 |
| `official_split` | leak-free; train on KDDTrain+ (125,973 rows), test on all of KDDTest+ | 0.7715 | 0.6186 | 2.64 % | 256 / 4,895 | 0.7857 | 0.7854 |

What this shows:

1. **The difficulty column inflates the result.** Removing it roughly doubles false
   positives and multiplies missed attacks by about 8 for Random Forest (4 → 31). Accuracy
   drops about one percentage point for every model.
2. **Preprocessing leakage has a negligible effect on this data.** Fitting the
   preprocessing on all rows versus on training rows only changes accuracy by at most 0.07
   percentage points. It is still a methodological error, but it does not explain the
   result.
3. **The random split of a single file overstates generalisation.** NSL-KDD's published
   protocol (train on KDDTrain+, test on KDDTest+, whose test set includes attack types
   that never appear in training) gives about 77–79 % accuracy and 62–64 % recall. In
   other words, about 36–38 % of attacks are missed, at a 2.6 % false-positive rate. This
   is the number to compare against when the question is "does it detect attacks it was
   not trained on?".

None of these figures are CIC-IDS2018 results. No CIC-IDS2018 result exists from this
notebook.

## 4. Other reported results (not re-run)

The notebook also reports four unsupervised detectors (deep autoencoder, LSTM autoencoder,
Transformer, Isolation Forest), bootstrap confidence intervals, McNemar tests against
Random Forest, three synthetic drift scenarios (sudden, gradual, prior) and drift-detector
counts (ADWIN 2, DDM 5, EDDM 18, Page-Hinkley 2). All of them use the same NSL-KDD
KDDTest+ data and split. They are recorded here as **reported, not reproduced**. The deep
models also need TensorFlow on a GPU, and their artifacts were not provided. They should
be re-examined with the same corrections as above before any of them is cited.

## 5. Consequences for this project

- The dissertation's headline numbers are **reproducible but should not be cited as
  CIC-IDS results** or as evidence of generalisation. Cite them, if at all, as "NSL-KDD
  KDDTest+, random 70/10/20 split, difficulty column included".
- The platform's baseline for further work should be the **leak-free official-split**
  protocol (or a CIC-IDS2018 protocol once that data is actually used). The spec's rule to
  "reproduce the baseline before improving models" is now satisfied for the supervised
  NSL-KDD models.
- Phase 6 makes the leak-free protocol enforceable for candidates: the difficulty column
  is excluded by the NSL-KDD schema (`configs/schemas/nsl-kdd.json`), and a candidate
  cannot be evaluated on the import it was trained from.

## 6. How to repeat it

```bash
# Data: the public NSL-KDD files, placed in data/raw/nsl-kdd/ (git-ignored)
adaptive-ids hash data/raw/nsl-kdd/KDDTest+.txt data/raw/nsl-kdd/KDDTrain+.txt
# Use the notebook's versions for an exact match:
pip install "scikit-learn==1.3.2" "xgboost==2.0.2" "lightgbm==4.1.0" "numpy==1.26.4" "pandas==2.2.2" "scipy==1.11.4"
adaptive-ids msc-reproduce --test data/raw/nsl-kdd/KDDTest+.txt --train data/raw/nsl-kdd/KDDTrain+.txt
```

XGBoost and LightGBM are optional: without them, only Random Forest runs. With newer
scikit-learn versions, Random Forest still matched exactly in our run (scikit-learn 1.5.2),
but exact equality is only claimed for the pinned versions.
