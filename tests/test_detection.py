import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from adaptive_ids.detection import (
    PREDICTION_COLUMNS,
    ArtifactEntry,
    ArtifactTrustError,
    InferenceError,
    Predictor,
    TrustedArtifactManifest,
    write_manifest,
)
from adaptive_ids.preprocessing import Preprocessor
from adaptive_ids.provenance import sha256_file


@pytest.fixture
def train_frame():
    rng = np.random.default_rng(0)
    n = 200
    y = np.where(np.arange(n) % 4 == 0, "DoS", "Benign")
    X = pd.DataFrame({
        "a": np.where(y == "DoS", 50.0, 5.0) + rng.normal(0, 1, n),
        "b": rng.integers(0, 3, n).astype(float),
        "c": rng.uniform(0, 10, n),
    })
    return X, y


@pytest.fixture
def model(train_frame):
    X, y = train_frame
    return RandomForestClassifier(n_estimators=10, random_state=0).fit(X, y)


@pytest.fixture
def manifest(tmp_path, model):
    path = tmp_path / "m.joblib"
    joblib.dump(model, path)
    entry = ArtifactEntry(artifact_id="rf", path="m.joblib", sha256=sha256_file(path))
    write_manifest([entry], tmp_path / "trusted.json")
    return tmp_path / "trusted.json"


def test_trusted_artifact_loads(manifest):
    loaded = TrustedArtifactManifest.load(manifest).load_model("rf")
    assert loaded.model_version.startswith("rf@")
    assert hasattr(loaded.model, "predict")


def test_unlisted_artifact_refused(manifest):
    with pytest.raises(ArtifactTrustError, match="not listed"):
        TrustedArtifactManifest.load(manifest).load_model("other")


def test_tampered_artifact_refused_before_deserialising(manifest, tmp_path):
    (tmp_path / "m.joblib").write_bytes(b"not the trusted file")
    with pytest.raises(ArtifactTrustError, match="hash mismatch"):
        TrustedArtifactManifest.load(manifest).load_model("rf")


def test_missing_manifest(tmp_path):
    with pytest.raises(ArtifactTrustError):
        TrustedArtifactManifest.load(tmp_path / "none.json")


def test_prediction_records_are_traceable(schema, model, train_frame):
    X, _ = train_frame
    pp = Preprocessor(schema)
    out = Predictor(model, "rf@abc", pp).predict(X.iloc[:5], event_ids=list("vwxyz"))
    assert list(out.columns) == PREDICTION_COLUMNS
    assert out["event_id"].tolist() == list("vwxyz")
    assert (out["model_version"] == "rf@abc").all()
    assert (out["preprocessing_version"] == pp.version_id).all()
    assert (out["status"] == "ok").all()
    assert out["score_kind"].iloc[0] == "max_class_score_uncalibrated"
    assert set(out["predicted_class"]) <= {"Benign", "DoS"}
    assert out["inferred_at"].notna().all()


def test_reordered_columns_give_same_predictions(schema, model, train_frame):
    X, _ = train_frame
    p = Predictor(model, "v", Preprocessor(schema))
    a = p.predict(X.iloc[:20])["predicted_class"]
    b = p.predict(X.iloc[:20][["c", "a", "b"]])["predicted_class"]
    assert a.tolist() == b.tolist()


def test_bad_rows_rejected_not_predicted(schema, model, train_frame):
    X, _ = train_frame
    batch = X.iloc[:3].copy()
    batch.iloc[1, 0] = np.nan
    out = Predictor(model, "v", Preprocessor(schema)).predict(batch)
    assert out["status"].tolist() == ["ok", "rejected", "ok"]
    assert out.loc[1, "predicted_class"] is None
    assert np.isnan(out.loc[1, "score"])


def test_threshold_rule(schema, model, train_frame):
    X, _ = train_frame
    pp = Preprocessor(schema)
    always = Predictor(model, "v", pp, positive_class="DoS", threshold=0.0).predict(X.iloc[:10])
    assert (always["predicted_class"] == "DoS").all()
    assert always["decision_rule"].iloc[0] == "score(DoS) >= 0.0"
    assert always["score_kind"].iloc[0] == "positive_class_score_uncalibrated"
    with pytest.raises(InferenceError):
        Predictor(model, "v", pp, positive_class="Nope", threshold=0.5)
    with pytest.raises(InferenceError):
        Predictor(model, "v", pp, threshold=0.5)


def test_incompatible_feature_set_detected(schema, train_frame):
    X, y = train_frame
    other = LogisticRegression().fit(X.rename(columns={"c": "zzz"}), y)
    with pytest.raises(InferenceError, match="different feature set"):
        Predictor(other, "v", Preprocessor(schema))
    numpy_model = LogisticRegression().fit(X[["a", "b"]].to_numpy(), y)
    with pytest.raises(InferenceError, match="expects 2 features"):
        Predictor(numpy_model, "v", Preprocessor(schema))


def test_model_failure_is_raised_not_hidden(schema, train_frame):
    X, _ = train_frame

    class Broken:
        def predict(self, X):
            raise RuntimeError("boom")

    with pytest.raises(InferenceError, match="boom"):
        Predictor(Broken(), "v", Preprocessor(schema)).predict(X.iloc[:2])
