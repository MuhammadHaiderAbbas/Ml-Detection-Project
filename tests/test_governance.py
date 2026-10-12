"""Phase 6: candidate evaluation protocol, gated approval, restorability checks."""

from __future__ import annotations

import json
import shutil

import numpy as np
import pytest
from api_support import ADMIN_PW, ANALYST_PW, REPO, activate_model, approve, demo_runs, env, evaluate, upload  # noqa: F401

from adaptive_ids.db import session_scope
from adaptive_ids.db.models import ModelVersion
from adaptive_ids.governance import EvaluationProtocol, ProtocolError, compare_models, load_protocol

# --------------------------------------------------------------------------- protocol and comparison


def test_protocol_file_is_valid_and_versioned():
    p = load_protocol(REPO / "configs/evaluation-protocol.json")
    assert p == EvaluationProtocol() and p.version == "1.0.0"


@pytest.mark.parametrize("bad", [{"recall_margin": 0.7}, {"min_labelled_events": 5}, {"confidence": 1.0},
                                 {"max_false_positive_rate": 2}, {"surprise": 1}])
def test_protocol_rejects_bad_settings(bad):
    with pytest.raises(ProtocolError):
        EvaluationProtocol.from_dict(bad)


def _labels(n=2000, seed=0, acc_c=0.97, acc_b=0.95):
    rng = np.random.default_rng(seed)
    t = rng.random(n) < 0.5
    return (t, np.where(rng.random(n) < acc_c, t, ~t), np.where(rng.random(n) < acc_b, t, ~t), np.ones(n, bool))


def test_identical_models_pass_with_zero_difference():
    t, c, _, ok = _labels()
    r = compare_models(t, c, ok, EvaluationProtocol(), c, ok)
    assert r.verdict == "pass"
    assert all(d["difference"] == 0 and d["ci_low"] == 0 and d["ci_high"] == 0 for d in r.differences.values())
    assert r.mcnemar["p_value"] == 1.0


def test_worse_candidate_fails_non_inferiority_and_better_one_passes():
    t, good, bad, ok = _labels(acc_c=0.97, acc_b=0.90)
    worse = compare_models(t, bad, ok, EvaluationProtocol(), good, ok)
    failed = {g["id"] for g in worse.gates if g["passed"] is False}
    assert worse.verdict == "fail" and "non_inferior_f1" in failed
    better = compare_models(t, good, ok, EvaluationProtocol(), bad, ok)
    assert better.verdict == "pass" and better.mcnemar["significant"]


def test_confidence_interval_brackets_point_estimate_and_matches_row_bootstrap():
    t, c, b, ok = _labels(n=800, seed=3)
    proto = EvaluationProtocol(bootstrap_iterations=2000)
    r = compare_models(t, c, ok, proto, b, ok)
    d = r.differences["accuracy"]
    assert d["ci_low"] <= d["difference"] <= d["ci_high"]
    # row-level paired bootstrap for comparison (slow path)
    rng = np.random.default_rng(1)
    idx = rng.integers(0, len(t), size=(2000, len(t)))
    diffs = (c[idx] == t[idx]).mean(1) - (b[idx] == t[idx]).mean(1)
    assert abs(np.quantile(diffs, 0.025) - d["ci_low"]) < 0.006
    assert abs(np.quantile(diffs, 0.975) - d["ci_high"]) < 0.006


def test_validity_gates_make_evidence_insufficient():
    t, c, b, ok = _labels(n=100)
    assert compare_models(t, c, ok, EvaluationProtocol(), b, ok).verdict == "insufficient_evidence"
    t, c, b, ok = _labels(n=1000)
    failing = ok.copy()
    failing[:50] = False  # 5 % of events could not be scored by the candidate
    r = compare_models(t, c, failing, EvaluationProtocol(), c, ok)
    assert r.verdict == "insufficient_evidence"
    assert r.counts["compared_events"] == 950
    assert {g["id"] for g in r.gates if g["passed"] is False} == {"candidate_failed_predictions"}


def test_absolute_requirements_without_baseline():
    t, c, _, ok = _labels(acc_c=0.9)
    r = compare_models(t, c, ok, EvaluationProtocol(min_attack_recall=0.99))
    assert r.verdict == "fail" and r.differences == {} and r.mcnemar is None
    assert compare_models(t, c, ok, EvaluationProtocol()).verdict == "pass"


def test_mcnemar_uses_exact_test_for_few_disagreements():
    t = np.array([True] * 300 + [False] * 300)
    c = t.copy()
    b = t.copy()
    b[:5] = ~b[:5]
    ok = np.ones(600, bool)
    r = compare_models(t, c, ok, EvaluationProtocol(), b, ok)
    assert r.mcnemar["method"] == "exact binomial" and r.mcnemar["candidate_only_correct"] == 5


# --------------------------------------------------------------------------- API workflow


def _register(env, admin, idx=0):
    r = env.client.post("/api/models/register-run", json={"run_name": env.runs["run_names"][idx]}, headers=admin)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_approval_requires_a_completed_evaluation(env):
    admin = env.login("admin", ADMIN_PW)
    mid = _register(env, admin)
    r = env.client.post(f"/api/models/{mid}/approve", json={"reason": "looks fine to me"}, headers=admin)
    assert r.status_code == 409 and "evaluation" in r.json()["detail"]
    ev = evaluate(env, admin, mid)
    assert ev["verdict"] == "pass" and ev["baseline_model_version_id"] is None
    assert ev["results"]["baseline_present"] is False and len(ev["gates"]) == 4
    r = env.client.post(f"/api/models/{mid}/approve", json={"reason": "passed protocol v1.0.0"}, headers=admin)
    assert r.status_code == 200, r.text
    m = r.json()
    assert m["approval_evaluation_id"] == ev["id"] and m["approval_override"] is False
    assert m["has_reference_sample"] and m["restore_check"]["ok"] and not m["restore_check"]["partial"]


def test_only_admins_evaluate_and_analysts_can_read(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    mid = _register(env, admin)
    imp = upload(env, analyst).json()["id"]
    assert env.client.post(f"/api/models/{mid}/evaluations", json={"import_id": imp}, headers=analyst).status_code == 403
    ev = evaluate(env, admin, mid, imp)
    assert env.client.get(f"/api/evaluations/{ev['id']}", headers=analyst).status_code == 200
    assert [e["id"] for e in env.client.get(f"/api/models/{mid}/evaluations", headers=analyst).json()] == [ev["id"]]
    p = env.client.get("/api/governance/protocol", headers=analyst).json()
    assert p["protocol"]["version"] == "1.0.0" and "non-inferiority" in p["rules"]


def test_cannot_evaluate_on_the_training_file(env):
    admin = env.login("admin", ADMIN_PW)
    mid = _register(env, admin)
    imp = upload(env, admin, path=env.runs["train"], dataset_name="training-file").json()["id"]
    r = env.client.post(f"/api/models/{mid}/evaluations", json={"import_id": imp}, headers=admin)
    assert r.status_code == 400 and "trained" in r.json()["detail"]


def test_insufficient_evidence_cannot_be_overridden(env, tmp_path):
    from adaptive_ids.research import write_synthetic_dataset

    admin = env.login("admin", ADMIN_PW)
    mid = _register(env, admin)
    small = tmp_path / "flows_SYNTHETIC_small.csv"
    write_synthetic_dataset(small, n_rows=120, seed=21)
    imp = upload(env, admin, path=small, dataset_name="small").json()["id"]
    ev = evaluate(env, admin, mid, imp)
    assert ev["verdict"] == "insufficient_evidence"
    r = env.client.post(f"/api/models/{mid}/approve",
                        json={"reason": "I accept the small sample size, honestly", "override": True}, headers=admin)
    assert r.status_code == 409 and "cannot be overridden" in r.json()["detail"]


def _strict_protocol(env, tmp_path, **overrides):
    path = tmp_path / "protocol.json"
    data = json.loads((REPO / "configs/evaluation-protocol.json").read_text())
    data.update(overrides)
    path.write_text(json.dumps(data))
    object.__setattr__(env.client.app.state.settings, "evaluation_protocol_path", path)
    return path


def test_failed_gates_need_an_explicit_justified_override(env):
    admin = env.login("admin", ADMIN_PW)
    activate_model(env, admin, 0)
    r = env.client.post("/api/models/register-run", json={"run_name": env.runs["weak_run"]}, headers=admin)
    mid = r.json()["id"]  # a depth-1 decision tree: valid, but clearly worse than the active forest
    ev = evaluate(env, admin, mid)
    assert ev["verdict"] == "fail", ev["gates"]
    assert {g["id"] for g in ev["gates"] if g["passed"] is False} >= {"non_inferior_f1"}
    url = f"/api/models/{mid}/approve"
    assert env.client.post(url, json={"reason": "fine"}, headers=admin).status_code == 409
    assert env.client.post(url, json={"reason": "too short", "override": True}, headers=admin).status_code == 400
    reason = "Accepted: false positives are reviewed manually during the pilot"
    r = env.client.post(url, json={"reason": reason, "override": True}, headers=admin)
    assert r.status_code == 200 and r.json()["approval_override"] is True
    logs = env.client.get("/api/audit-logs", params={"action": "model.approve_override"}, headers=admin).json()
    assert logs["total"] == 1 and logs["items"][0]["details"]["failed_gates"]
    hist = env.client.get(f"/api/models/{mid}/history", headers=admin).json()
    assert hist[-1]["reason"].startswith("[override of failed gates:")


def test_override_is_refused_for_a_passing_evaluation(env):
    admin = env.login("admin", ADMIN_PW)
    mid = _register(env, admin)
    evaluate(env, admin, mid)
    r = env.client.post(f"/api/models/{mid}/approve", json={"reason": "x" * 30, "override": True}, headers=admin)
    assert r.status_code == 400


def test_stale_evaluations_cannot_approve(env, tmp_path):
    admin = env.login("admin", ADMIN_PW)
    path = _strict_protocol(env, tmp_path)
    m1, m2 = _register(env, admin, 0), _register(env, admin, 1)
    evaluate(env, admin, m1)
    # the protocol changes after the evaluation
    data = json.loads(path.read_text())
    path.write_text(json.dumps(dict(data, version="1.1.0", recall_margin=0.005)))
    r = env.client.post(f"/api/models/{m1}/approve", json={"reason": "ok to go"}, headers=admin)
    assert r.status_code == 409 and "protocol" in r.json()["detail"]
    # the baseline changes after the evaluation
    evaluate(env, admin, m1)
    approve(env, admin, m2)
    env.client.post(f"/api/models/{m2}/activate", json={"reason": "m2 live"}, headers=admin)
    r = env.client.post(f"/api/models/{m1}/approve", json={"reason": "ok to go"}, headers=admin)
    assert r.status_code == 409 and "active model changed" in r.json()["detail"]
    ev = evaluate(env, admin, m1)
    assert ev["baseline_model_version_id"] == m2 and ev["results"]["differences"]
    assert ev["results"]["mcnemar"] is not None


def test_activation_and_rollback_require_a_restorable_artifact(env):
    admin = env.login("admin", ADMIN_PW)
    m1 = activate_model(env, admin, 0)["id"]
    m2 = activate_model(env, admin, 1)["id"]
    # rollback to m1 works and records the check
    r = env.client.post(f"/api/models/{m1}/activate", json={"reason": "rollback"}, headers=admin)
    assert r.status_code == 200 and r.json()["restore_check"]["ok"]
    # a recorded output that the artifact no longer reproduces blocks activation
    with session_scope(env.factory) as db:
        mv = db.get(ModelVersion, m2)
        sample = dict(mv.reference_sample)
        sample["expected_class"] = ["not-a-class"] + sample["expected_class"][1:]
        mv.reference_sample = sample
    r = env.client.post(f"/api/models/{m2}/activate", json={"reason": "back to m2"}, headers=admin)
    assert r.status_code == 409 and "recorded predictions reproduced" in r.json()["detail"]
    assert env.client.get("/api/models/active", headers=admin).json()["id"] == m1
    # a registry hash that does not match the file blocks it too, and the check is recorded on request
    with session_scope(env.factory) as db:
        db.get(ModelVersion, m2).artifact_sha256 = "0" * 64
    r = env.client.post(f"/api/models/{m2}/verify-restore", headers=admin)
    chk = r.json()["restore_check"]
    assert r.status_code == 200 and chk["ok"] is False
    assert [c["id"] for c in chk["checks"] if c["passed"] is False][0] == "artifact_hash"
    logs = env.client.get("/api/audit-logs", params={"action": "model.restore_check"}, headers=admin).json()
    assert logs["total"] == 1 and logs["items"][0]["details"]["ok"] is False


def test_missing_artifact_is_reported_not_loaded(env, tmp_path):
    admin = env.login("admin", ADMIN_PW)
    m1 = activate_model(env, admin, 0)["id"]
    with session_scope(env.factory) as db:
        mv = db.get(ModelVersion, m1)
        moved = tmp_path / "moved.joblib"
        shutil.copyfile(mv.artifact_path, moved)
        mv.artifact_path = str(tmp_path / "gone.joblib")
    chk = env.client.post(f"/api/models/{m1}/verify-restore", headers=admin).json()["restore_check"]
    assert chk["ok"] is False and chk["checks"][0]["id"] == "artifact_present"


def test_evaluation_report_export(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    activate_model(env, admin, 1)
    mid = _register(env, admin, 0)
    ev = evaluate(env, admin, mid)
    r = env.client.get(f"/api/evaluations/{ev['id']}/report.md", headers=analyst)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.text
    assert "SYNTHETIC DEMO" in text and "95 % CI of difference" in text and "## Gates" in text
    assert "not analyst-confirmed" in text
