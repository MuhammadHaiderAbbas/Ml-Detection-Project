# Reproducing the original MSc baseline (Windows, step by step)

This is the Milestone 1 procedure. Run it on the laptop that holds the original
project. Nothing here modifies the original folder.

## 0. Set up this repository

```powershell
cd D:\AdaptiveIDS
git clone https://github.com/MuhammadHaiderAbbas/Ml-Detection-Project.git
cd Ml-Detection-Project
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1          # or call .\.venv\Scripts\python.exe directly
python -m pip install --upgrade pip
pip install -r requirements.lock.txt
pip install -e . --no-deps
python -m pytest                      # all tests should pass
```

## 1. Back up the original project (once)

```powershell
adaptive-ids backup D:\AdaptiveIDS\original_backup --source "D:\path\to\MSc_Research_IDS"
adaptive-ids backup D:\AdaptiveIDS\original_backup --verify
```

The backup is a separate copy. Every file is verified by SHA-256 and marked
read-only, and the command refuses to overwrite an existing backup. Keep it
outside this git repository.

## 2. Inventory it (static, safe)

```powershell
adaptive-ids inventory D:\AdaptiveIDS\original_backup --out docs\inventory
```

This produces `docs\inventory\inventory.md` and `inventory.json` (both git-ignored).
They list every file with its hash, plus each notebook's imports, `read_csv`
paths, `joblib.dump` targets, `train_test_split` parameters, SMOTE and scaler
usage, saved error outputs and printed metric lines. Nothing is executed or
unpickled. Review it, then share `inventory.md` if you want help with the next
steps. It contains file paths but no data.

## 3. Pin the original environment

Find the original scikit-learn version (from `requirements.txt`, a `pip freeze`
in the old venv, or the `InconsistentVersionWarning` the runner records). Edit
`requirements.lock.txt` to match and reinstall it. Re-run `python -m pytest`.

## 4. Define the dataset and schema

1. Copy the dataset file(s) the notebooks actually used into `data\raw\` (git-ignored).
2. `adaptive-ids hash data\raw\<file>.csv`, and record the hash.
3. Copy `configs\schemas\cse-cic-ids2018.candidate.json` to a new file and edit
   `features` to **exactly** the columns, in the order, that the final model was
   trained on (check `X.columns` in the notebook). Set `status` to `verified` only
   after checking.
4. `adaptive-ids preview data\raw\<file>.csv --schema configs\schemas\<yours>.json`
   should report no missing columns.

## 5. Register the trusted model

Copy `models\trusted_artifacts.example.json` to `models\trusted_artifacts.json`,
copy the original model file into `models\original\`, and fill in the entry with
the `adaptive-ids hash` output. Only list files you created yourself.

## 6. Run the reproduction

Copy `configs\experiments\baseline-reproduction.template.json`, replace every
`REPLACE` value, and put the dissertation's reported test metrics under
`reported_results.metrics`. Recognised keys are `accuracy`, `macro_f1`,
`weighted_f1`, `attack_recall`, `false_positive_rate` and so on (see
`REPORTABLE_METRICS` in `src/adaptive_ids/experiments/runner.py`).

Choose the split that matches the original:

- `{"method": "all_test"}` if you have the exact held-out test file;
- `{"method": "column", "column": "split"}` if you can recover each row's assignment;
- `{"method": "stratified_random", "test_fraction": 0.3, "seed": 42, "val_fraction": 0}`
  to reproduce `train_test_split(..., test_size=0.3, random_state=42, stratify=y)`.
  This matches only if the row order and the cleaning are identical. A
  `train_test_split` call without `stratify` cannot be reproduced exactly by this
  method, so record that as a discrepancy.

If labels were encoded (for example `0/1`), use `evaluation.label_mapping`. If the
model is binary but the CSV is multi-class, use `evaluation.binary_collapse`.

```powershell
adaptive-ids run configs\experiments\<your-config>.json
```

## 7. Record the outcome

Open `experiments\runs\<id>-<time>\report.md`. Copy the report into `docs/`
with the comparison table. Update `docs/milestone-1-status.md` with every
discrepancy and its likely cause. Only then is Milestone 1 complete.
