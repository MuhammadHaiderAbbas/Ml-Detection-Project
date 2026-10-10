"""Read-only inventory of an existing research project folder.

Scans files, hashes them, and statically inspects notebooks and Python
scripts for dataset paths, model persistence, splitting parameters, imbalance
handling and printed metric outputs. It never executes code, never imports
the project's modules and never unpickles model files.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..provenance import sha256_file

CATEGORIES = {
    "notebook": {".ipynb"},
    "python": {".py"},
    "r": {".r", ".rmd"},
    "data": {".csv", ".parquet", ".feather", ".tsv", ".xlsx", ".xls", ".pcap", ".pcapng", ".log", ".arff", ".zip", ".gz"},
    "model_artifact": {".joblib", ".pkl", ".pickle", ".sav", ".h5", ".keras", ".onnx", ".pt", ".pth", ".json_model", ".skops"},
    "dependency": {".txt", ".yml", ".yaml", ".toml", ".cfg", ".lock"},
    "document": {".docx", ".doc", ".pdf", ".md", ".pptx", ".tex"},
    "image": {".png", ".jpg", ".jpeg", ".svg", ".gif"},
}
DEPENDENCY_NAMES = re.compile(r"^(requirements.*\.txt|environment.*\.ya?ml|pyproject\.toml|setup\.(py|cfg)|Pipfile(\.lock)?|poetry\.lock|conda.*\.ya?ml)$", re.I)
SKIP_DIRS = {".git", "__pycache__", ".ipynb_checkpoints", ".venv", "venv", "env", "node_modules", ".idea"}

PATTERNS = {
    "imports": re.compile(r"^\s*(?:from\s+([\w\.]+)\s+import|import\s+([\w\.]+))", re.M),
    "read_data": re.compile(r"(?:read_csv|read_parquet|read_excel|read_feather|loadtxt|genfromtxt)\(\s*(?:r|f)?['\"]([^'\"]+)['\"]"),
    "model_save": re.compile(r"(?:joblib|pickle|dill|skops\.io)\.dump\(\s*\w+\s*,\s*(?:r|f)?['\"]([^'\"]+)['\"]"),
    "model_load": re.compile(r"(?:joblib|pickle|dill)\.load\(\s*(?:open\()?\s*(?:r|f)?['\"]([^'\"]+)['\"]"),
    "estimators": re.compile(r"\b(\w+(?:Classifier|Regressor|Regression|SVC|NB|IsolationForest|LocalOutlierFactor|OneClassSVM|KMeans|Autoencoder))\s*\("),
    "train_test_split": re.compile(r"train_test_split\(([^)]*)\)"),
    "random_state": re.compile(r"random_state\s*=\s*(\d+)"),
    "test_size": re.compile(r"test_size\s*=\s*([\d.]+)"),
    "smote": re.compile(r"\b(SMOTE\w*|ADASYN|RandomOverSampler|RandomUnderSampler)\b"),
    "class_weight": re.compile(r"class_weight\s*=\s*([^,\)\n]+)"),
    "scalers": re.compile(r"\b(StandardScaler|MinMaxScaler|RobustScaler|Normalizer|LabelEncoder|OneHotEncoder|OrdinalEncoder|SelectKBest|PCA|VarianceThreshold)\b"),
    "drift": re.compile(r"\b(ADWIN|DDM|EDDM|PageHinkley|KSWIN|ks_2samp|river\.drift)\b"),
    "shap": re.compile(r"\bshap\.(\w+)"),
    "synthetic_data": re.compile(r"\b(make_classification|make_blobs|make_moons|np\.random\.(?:rand|randn|normal)\()"),
    "fit_calls": re.compile(r"\.fit(?:_transform|_resample)?\("),
}
METRIC_LINE = re.compile(r"(accuracy|precision|recall|f1|f1-score|roc[_ ]auc|false positive|confusion|macro avg|weighted avg)", re.I)


def _category(path: Path) -> str:
    if DEPENDENCY_NAMES.match(path.name):
        return "dependency"
    ext = path.suffix.lower()
    for cat, exts in CATEGORIES.items():
        if ext in exts and cat != "dependency":
            return cat
    return "other"


def _scan_code(code: str) -> dict[str, Any]:
    found: dict[str, Any] = {}
    for key, pat in PATTERNS.items():
        if key == "imports":
            mods = {(a or b).split(".")[0] for a, b in pat.findall(code)}
            if mods:
                found[key] = sorted(mods)
        elif key == "fit_calls":
            n = len(pat.findall(code))
            if n:
                found[key] = n
        else:
            vals = sorted({v.strip() if isinstance(v, str) else v for v in pat.findall(code)})
            if vals:
                found[key] = vals
    return found


def _merge(into: dict[str, Any], new: dict[str, Any]) -> None:
    for k, v in new.items():
        if isinstance(v, int):
            into[k] = into.get(k, 0) + v
        else:
            into[k] = sorted(set(into.get(k, [])) | set(v))


def inspect_notebook(path: Path, max_metric_lines: int = 60) -> dict[str, Any]:
    try:
        nb = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return {"error": f"could not parse notebook: {exc}"}
    cells = nb.get("cells", [])
    code_cells = [c for c in cells if c.get("cell_type") == "code"]
    summary: dict[str, Any] = {}
    errors, metric_lines = [], []
    executed = 0
    for c in code_cells:
        src = c.get("source", "")
        _merge(summary, _scan_code("".join(src) if isinstance(src, list) else src))
        if c.get("execution_count") is not None:
            executed += 1
        for out in c.get("outputs", []):
            if out.get("output_type") == "error":
                errors.append(f"{out.get('ename')}: {out.get('evalue')}"[:300])
            text = out.get("text") or out.get("data", {}).get("text/plain") or ""
            text = "".join(text) if isinstance(text, list) else text
            for line in text.splitlines():
                if METRIC_LINE.search(line) and len(metric_lines) < max_metric_lines:
                    metric_lines.append(line.rstrip()[:200])
    kernel = nb.get("metadata", {}).get("kernelspec", {}).get("display_name")
    lang = nb.get("metadata", {}).get("language_info", {}).get("version")
    return {
        "kernel": kernel,
        "python_version": lang,
        "n_cells": len(cells),
        "n_code_cells": len(code_cells),
        "n_executed_code_cells": executed,
        "error_outputs": errors[:20],
        "metric_output_lines": metric_lines,
        "static_findings": summary,
    }


def build_inventory(root: str | Path, *, hash_max_bytes: int | None = None) -> dict[str, Any]:
    root = Path(root).resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"project folder not found: {root}")
    files = []
    notebooks: dict[str, Any] = {}
    scripts: dict[str, Any] = {}
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts[:-1]) or not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        size = path.stat().st_size
        cat = _category(path)
        entry = {"path": rel, "category": cat, "bytes": size}
        if hash_max_bytes is None or size <= hash_max_bytes:
            entry["sha256"] = sha256_file(path)
        else:
            entry["sha256"] = None
            entry["note"] = "not hashed (above size threshold)"
        files.append(entry)
        if cat == "notebook":
            notebooks[rel] = inspect_notebook(path)
        elif cat == "python":
            try:
                scripts[rel] = _scan_code(path.read_text(encoding="utf-8", errors="replace"))
            except OSError as exc:
                scripts[rel] = {"error": str(exc)}

    referenced_data = sorted({p for n in list(notebooks.values()) + list(scripts.values())
                              for p in n.get("static_findings", n).get("read_data", [])})
    referenced_models = sorted({p for n in list(notebooks.values()) + list(scripts.values())
                                for p in n.get("static_findings", n).get("model_save", [])})
    present_names = {Path(f["path"]).name for f in files}
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "root": str(root),
        "counts_by_category": dict(Counter(f["category"] for f in files)),
        "total_bytes": sum(f["bytes"] for f in files),
        "files": files,
        "notebooks": notebooks,
        "scripts": scripts,
        "referenced_data_files": [
            {"reference": p, "present_by_filename": Path(p.replace("\\", "/")).name in present_names} for p in referenced_data
        ],
        "referenced_model_files": [
            {"reference": p, "present_by_filename": Path(p.replace("\\", "/")).name in present_names} for p in referenced_models
        ],
        "notes": [
            "Static inspection only: no code was executed and no model file was deserialised.",
            "Metric lines are copied from saved notebook outputs; they are evidence of what was printed, "
            "not verified results.",
        ],
    }


def render_inventory_markdown(inv: dict[str, Any]) -> str:
    lines = [
        "# Research project inventory",
        "",
        f"- Root: `{inv['root']}`",
        f"- Generated: {inv['generated_at']}",
        f"- Files by category: {inv['counts_by_category']}",
        f"- Total size: {inv['total_bytes'] / 1024**2:.1f} MB",
        "",
    ]
    for note in inv["notes"]:
        lines.append(f"> {note}")
    lines += ["", "## Referenced data files", ""]
    for r in inv["referenced_data_files"] or [{"reference": "none found", "present_by_filename": None}]:
        lines.append(f"- `{r['reference']}` — present in folder: {r['present_by_filename']}")
    lines += ["", "## Referenced model files", ""]
    for r in inv["referenced_model_files"] or [{"reference": "none found", "present_by_filename": None}]:
        lines.append(f"- `{r['reference']}` — present in folder: {r['present_by_filename']}")
    lines += ["", "## Notebooks", ""]
    for name, nb in inv["notebooks"].items():
        lines.append(f"### `{name}`")
        if "error" in nb:
            lines += [f"- {nb['error']}", ""]
            continue
        lines.append(
            f"- Cells: {nb['n_cells']} ({nb['n_code_cells']} code, {nb['n_executed_code_cells']} executed); "
            f"kernel: {nb['kernel']}; python: {nb['python_version']}"
        )
        for k, v in nb["static_findings"].items():
            lines.append(f"- {k}: {v}")
        if nb["error_outputs"]:
            lines.append(f"- Saved error outputs: {nb['error_outputs']}")
        if nb["metric_output_lines"]:
            lines += ["- Printed metric lines (unverified):", "", "```"] + nb["metric_output_lines"] + ["```"]
        lines.append("")
    lines += ["## Files", "", "| Path | Category | Bytes | SHA-256 |", "|---|---|---|---|"]
    for f in inv["files"]:
        lines.append(f"| `{f['path']}` | {f['category']} | {f['bytes']} | `{(f['sha256'] or '-')[:16]}` |")
    lines.append("")
    return "\n".join(lines)
