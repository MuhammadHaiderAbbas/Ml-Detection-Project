"""SHAP explanations: correctness of the attributions, and that they belong to the stored prediction."""

from __future__ import annotations

import itertools
import math
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select

from adaptive_ids.db import session_scope
from adaptive_ids.db.models import Alert, Prediction, PredictionExplanation
from adaptive_ids.explainability import ADDITIVITY_TOLERANCE, ExplanationError, explain_rows, supports
from adaptive_ids.explainability import tree_shap
from api_support import ADMIN_PW, ANALYST_PW, VIEWER_PW, demo_runs, env, scored_import  # noqa: F401
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.naive_bayes import GaussianNB
from sklearn.tree import DecisionTreeClassifier


def _data(n_classes: int, n: int = 400, n_features: int = 5, seed: int = 0):
    rng = np.random.default_rng(seed)
    X = pd.DataFrame(rng.normal(size=(n, n_features)), columns=[f"f{i}" for i in range(n_features)])
    y = np.where(X.f0 + 0.5 * X.f1 > 0, "dos", "benign")
    if n_classes == 3:
        y = np.where(X.f2 > 1.0, "probe", y)
    return X, y


TREE_MODELS = [
    lambda: RandomForestClassifier(n_estimators=15, random_state=0),
    lambda: ExtraTreesClassifier(n_estimators=15, random_state=0),
    lambda: DecisionTreeClassifier(max_depth=5, random_state=0),
    lambda: HistGradientBoostingClassifier(max_iter=25, random_state=0),
]


@pytest.mark.parametrize("make", TREE_MODELS)
@pytest.mark.parametrize("n_classes", [2, 3])
def test_contributions_add_up_to_the_models_own_output(make, n_classes):
    X, y = _data(n_classes)
    model = make().fit(X, y)
    rows = X.iloc[:8]
    targets = model.predict(rows)
    exps = explain_rows(model, rows, targets)
    if hasattr(model, "decision_function"):
        raw = model.decision_function(rows)
        if raw.ndim == 1:
            raw = np.stack([-raw, raw], axis=1)
        reference = raw
    else:
        reference = model.predict_proba(rows)
    classes = [str(c) for c in model.classes_]
    for i, e in enumerate(exps):
        k = classes.index(str(targets[i]))
        assert e.target_class == str(targets[i])
        assert e.model_output == pytest.approx(reference[i, k], abs=1e-12)
        total = e.base_value + sum(c.contribution for c in e.contributions)
        assert abs(total - e.model_output) <= ADDITIVITY_TOLERANCE
        assert [c.feature for c in e.contributions] != [] and len(e.contributions) == X.shape[1]
        mags = [abs(c.contribution) for c in e.contributions]
        assert mags == sorted(mags, reverse=True)
        assert {c.feature: c.model_input for c in e.contributions} == pytest.approx(rows.iloc[i].to_dict())
        assert e.limitations and e.output_space in ("probability", "log_odds", "class_logit")


def _path_dependent_value(tree, x: np.ndarray, known: set[int], node: int = 0) -> np.ndarray:
    """E[f(x) | x_S] under the tree-path-dependent assumption: unknown splits follow training cover."""
    left, right = tree.children_left[node], tree.children_right[node]
    if left == -1:
        v = tree.value[node][0]
        return v / v.sum()
    f = tree.feature[node]
    if f in known:
        nxt = left if x[f] <= tree.threshold[node] else right
        return _path_dependent_value(tree, x, known, nxt)
    n = tree.weighted_n_node_samples
    return (n[left] * _path_dependent_value(tree, x, known, left)
            + n[right] * _path_dependent_value(tree, x, known, right)) / n[node]


def test_values_match_brute_force_shapley_values():
    """Independent check: enumerate every feature subset and compute the exact Shapley values."""
    X, y = _data(3, n_features=4, seed=3)
    model = DecisionTreeClassifier(max_depth=4, random_state=0).fit(X, y)
    rows = X.iloc[:5]
    targets = model.predict(rows)
    exps = explain_rows(model, rows, targets)
    p = X.shape[1]
    classes = list(model.classes_)
    for i, e in enumerate(exps):
        x = rows.iloc[i].to_numpy()
        k = classes.index(targets[i])
        got = {c.feature: c.contribution for c in e.contributions}
        for j in range(p):
            others = [m for m in range(p) if m != j]
            phi = 0.0
            for r in range(p):
                for S in itertools.combinations(others, r):
                    w = math.factorial(r) * math.factorial(p - r - 1) / math.factorial(p)
                    with_j = _path_dependent_value(model.tree_, x, set(S) | {j})[k]
                    without = _path_dependent_value(model.tree_, x, set(S))[k]
                    phi += w * (with_j - without)
            assert got[f"f{j}"] == pytest.approx(phi, abs=1e-12)


@pytest.mark.parametrize("model", [LogisticRegression(), GaussianNB()])
def test_unsupported_models_get_a_reason_not_an_approximation(model):
    X, y = _data(2)
    model.fit(X, y)
    ok, why = supports(model)
    assert not ok and "not supported" in why and "no approximate" in why
    with pytest.raises(ExplanationError):
        explain_rows(model, X.iloc[:1], [model.predict(X.iloc[:1])[0]])


def test_an_explanation_that_does_not_add_up_is_refused(monkeypatch):
    X, y = _data(2)
    model = RandomForestClassifier(n_estimators=5, random_state=0).fit(X, y)
    real = tree_shap._shap()

    class Skewed:
        def __init__(self, m):
            self._e = real.TreeExplainer(m)
            self.expected_value = self._e.expected_value

        def shap_values(self, data, check_additivity=False):
            return np.asarray(self._e.shap_values(data, check_additivity=False)) + 0.01

    monkeypatch.setattr(tree_shap, "_shap", lambda: SimpleNamespace(TreeExplainer=Skewed, __version__="x"))
    with pytest.raises(ExplanationError, match="does not reproduce"):
        explain_rows(model, X.iloc[:1], [model.predict(X.iloc[:1])[0]])


def test_unknown_target_class_is_rejected():
    X, y = _data(2)
    model = DecisionTreeClassifier(max_depth=2).fit(X, y)
    with pytest.raises(ExplanationError, match="not one of"):
        explain_rows(model, X.iloc[:1], ["probe"])


# --------------------------------------------------------------------------- API


def test_alert_explanation_matches_the_stored_prediction(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    alert = env.client.get("/api/alerts", headers=analyst).json()["items"][0]
    detail = env.client.get(f"/api/alerts/{alert['id']}", headers=analyst).json()
    r = env.client.get(f"/api/alerts/{alert['id']}/explanation", headers=analyst)
    assert r.status_code == 200, r.text
    x = r.json()
    assert x["available"] and x["target_class"] == alert["predicted_class"]
    assert x["output_space"] == "probability" and x["method"].startswith("shap.TreeExplainer")
    # the explained output is the score the analyst sees, and the parts add up to it
    assert x["model_output"] == pytest.approx(alert["score"], abs=1e-9)
    assert x["base_value"] + sum(c["contribution"] for c in x["contributions"]) == pytest.approx(x["model_output"], abs=1e-6)
    assert x["preprocessing_version"] == detail["prediction"]["preprocessing_version"]
    assert x["artifact_sha256"] == detail["model"]["artifact_sha256"]
    features = detail["event"]["features"]
    assert {c["feature"] for c in x["contributions"]} == set(features)
    assert all(c["raw_value"] == features[c["feature"]] for c in x["contributions"])
    # stored: a later view (also by a read-only viewer) gets the same explanation
    again = env.client.get(f"/api/alerts/{alert['id']}/explanation", headers=env.login("viewer", VIEWER_PW)).json()
    assert again["computed_at"] == x["computed_at"] and again["contributions"] == x["contributions"]
    with session_scope(env.factory) as db:
        assert len(list(db.scalars(select(PredictionExplanation)))) == 1


def test_no_explanation_when_the_model_no_longer_reproduces_the_prediction(env):
    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    scored_import(env, admin, analyst)
    with session_scope(env.factory) as db:
        a = db.scalars(select(Alert).order_by(Alert.id)).first()
        pred = db.get(Prediction, a.prediction_id)
        pred.score = (pred.score or 0) - 0.05  # the stored record no longer matches the artifact
        alert_id = a.id
    r = env.client.get(f"/api/alerts/{alert_id}/explanation", headers=analyst)
    assert r.status_code == 409 and "no longer reproduces" in r.json()["detail"]
    with session_scope(env.factory) as db:
        assert db.scalar(select(PredictionExplanation)) is None


def test_explanation_requires_sign_in_and_a_real_alert(env):
    assert env.client.get("/api/alerts/1/explanation").status_code == 401
    analyst = env.login("analyst", ANALYST_PW)
    assert env.client.get("/api/alerts/999999/explanation", headers=analyst).status_code == 404


def test_summary_groups_by_dataset_label_and_is_reproducible(env):
    from adaptive_ids.services import explanations
    from adaptive_ids.services.scoring import ModelCache

    admin, analyst = env.login("admin", ADMIN_PW), env.login("analyst", ANALYST_PW)
    import_id = scored_import(env, admin, analyst)
    with session_scope(env.factory) as db:
        mv_id = db.scalars(select(Alert.model_version_id)).first()
        a = explanations.summarize(db, ModelCache(), import_id, mv_id, sample_per_group=25, seed=3)
        b = explanations.summarize(db, ModelCache(), import_id, mv_id, sample_per_group=25, seed=3)
        n_alerts = len(list(db.scalars(select(Alert).where(Alert.import_id == import_id))))
    assert a == b and a["labelled"] and "not analyst-confirmed" in a["basis"]
    alerts_total = sum(g["predictions"] for k, g in a["groups"].items() if k.startswith("alert_"))
    assert alerts_total == n_alerts
    for g in a["groups"].values():
        assert g["sampled"] == min(25, g["predictions"]) and g["max_additivity_error"] <= 1e-6
        assert 0 < len(g["top_features"]) <= 10
        mags = [f["mean_abs_contribution"] for f in g["top_features"]]
        assert mags == sorted(mags, reverse=True)
