import json
import os
import stat

import pytest

from adaptive_ids.cli import main
from adaptive_ids.research import (
    BackupError,
    build_inventory,
    create_backup,
    generate_synthetic_flows,
    render_inventory_markdown,
    verify_backup,
)

NOTEBOOK = {
    "metadata": {"kernelspec": {"display_name": "Python 3"}, "language_info": {"version": "3.10.11"}},
    "cells": [
        {"cell_type": "code", "execution_count": 1, "outputs": [], "source": [
            "import pandas as pd\n", "from sklearn.ensemble import RandomForestClassifier\n",
            "from imblearn.over_sampling import SMOTE\n",
            "df = pd.read_csv('data/02-14-2018.csv')\n",
        ]},
        {"cell_type": "code", "execution_count": 2, "source": [
            "X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.3, random_state=42)\n",
            "clf = RandomForestClassifier(class_weight='balanced').fit(X_tr, y_tr)\n",
            "joblib.dump(clf, 'models/rf.joblib')\n",
        ], "outputs": [{"output_type": "stream", "text": ["accuracy 0.97\n", "unrelated\n"]},
                       {"output_type": "error", "ename": "MemoryError", "evalue": "x"}]},
        {"cell_type": "markdown", "source": "# notes"},
    ],
}


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "MSc"
    (root / "notebooks").mkdir(parents=True)
    (root / "notebooks" / "01_audit.ipynb").write_text(json.dumps(NOTEBOOK))
    (root / "requirements.txt").write_text("scikit-learn==1.2.2\n")
    (root / "models").mkdir()
    (root / "models" / "rf.joblib").write_bytes(b"opaque bytes - never loaded")
    return root


def test_inventory_static_findings(project):
    inv = build_inventory(project)
    cats = inv["counts_by_category"]
    assert cats["notebook"] == 1 and cats["model_artifact"] == 1 and cats["dependency"] == 1
    nb = inv["notebooks"]["notebooks/01_audit.ipynb"]
    f = nb["static_findings"]
    assert f["read_data"] == ["data/02-14-2018.csv"]
    assert f["model_save"] == ["models/rf.joblib"]
    assert f["smote"] == ["SMOTE"] and f["random_state"] == ["42"] and f["test_size"] == ["0.3"]
    assert "RandomForestClassifier" in f["estimators"]
    assert nb["metric_output_lines"] == ["accuracy 0.97"]
    assert nb["error_outputs"] == ["MemoryError: x"]
    assert nb["python_version"] == "3.10.11"
    refs = {r["reference"]: r["present_by_filename"] for r in inv["referenced_data_files"]}
    assert refs == {"data/02-14-2018.csv": False}
    assert {r["reference"]: r["present_by_filename"] for r in inv["referenced_model_files"]} == {"models/rf.joblib": True}
    assert "Research project inventory" in render_inventory_markdown(inv)


def test_backup_verified_and_never_overwrites(project, tmp_path):
    dest = tmp_path / "backup"
    m = create_backup(project, dest)
    assert m["file_count"] == 3
    assert verify_backup(dest)["ok"]
    mode = os.stat(dest / "requirements.txt").st_mode
    assert not mode & stat.S_IWUSR
    with pytest.raises(BackupError, match="already exists"):
        create_backup(project, dest)
    with pytest.raises(BackupError, match="outside"):
        create_backup(project, project / "inner")
    os.chmod(dest / "requirements.txt", stat.S_IWUSR | stat.S_IRUSR)
    (dest / "requirements.txt").write_text("changed")
    assert not verify_backup(dest)["ok"]
    assert (project / "requirements.txt").read_text() == "scikit-learn==1.2.2\n"  # source untouched


def test_synthetic_data_is_labelled_and_deterministic(tmp_path):
    a = generate_synthetic_flows(500, seed=3)
    b = generate_synthetic_flows(500, seed=3)
    assert a.equals(b)
    labels = set(a["Label"]) - {"", "Label"}
    assert all(l == "Benign" or l.startswith("SYNTH_") for l in labels)
    with pytest.raises(ValueError, match="SYNTHETIC"):
        main(["make-synthetic", "--out", str(tmp_path / "flows.csv")])


def test_cli_inventory_and_hash(project, tmp_path, capsys):
    assert main(["inventory", str(project), "--out", str(tmp_path / "inv")]) == 0
    assert (tmp_path / "inv" / "inventory.md").exists()
    assert main(["hash", str(project / "requirements.txt")]) == 0
    assert len(capsys.readouterr().out.strip().split("\n")[-1].split()[0]) == 64
