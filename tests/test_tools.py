"""Smoke tests for the release tools in tools/."""

from __future__ import annotations

import json
import subprocess  # nosec B404 - runs this repository's own tool with fixed arguments
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def test_benchmark_runs_the_whole_workflow_and_reports_measurements(tmp_path):
    out = tmp_path / "bench.json"
    proc = subprocess.run(  # nosec B603 - fixed arguments, this repository's tool
        [sys.executable, str(REPO / "tools/benchmark_deployment.py"), "--synthetic", "1500", "--explanations", "3",
         "--out", str(out)], capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert proc.returncode == 0, proc.stderr[-2000:]
    r = json.loads(out.read_text())
    assert r["provenance"] == "synthetic_demo" and r["database"] == "sqlite"
    for step in ("import", "evaluate_candidate", "approve_with_restore_check", "activate", "score",
                 "alert_explanation_first_view", "alert_explanation_stored", "drift_analysis", "backup"):
        assert step in r["steps"], step
    assert r["steps"]["score"]["events"] == r["steps"]["import"]["events"] > 1400
    assert r["steps"]["score"]["events_per_second"] > 0 and r["peak_process_memory_mb"] > 0
    assert r["storage"]["database_mb"] > 0 and r["machine"]["logical_cpus"]


def test_third_party_notices_cover_every_locked_package():
    sys.path.insert(0, str(REPO / "tools"))
    try:
        import third_party_notices as tpn
    finally:
        sys.path.pop(0)
    locked = {line.split("==")[0].lower() for line in (REPO / "requirements.lock.txt").read_text().splitlines()
              if line and not line.startswith("#")}
    listed = {name.lower() for name, _, _ in tpn.python_rows()}
    assert listed == locked
    assert all(lic for _, _, lic in tpn.python_rows())
