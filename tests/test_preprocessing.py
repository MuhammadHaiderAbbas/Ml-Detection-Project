import numpy as np
import pandas as pd
import pytest

from adaptive_ids.preprocessing import PreprocessingConfig, PreprocessingError, Preprocessor


def frame(**cols):
    return pd.DataFrame(cols)


def test_default_is_identity_and_orders_features(schema):
    df = frame(c=[1.0, 2.0], b=[3.0, 4.0], a=[5.0, 6.0], Label=["x", "y"])
    out = Preprocessor(schema).transform(df)
    assert list(out.X.columns) == ["a", "b", "c"]
    assert out.X["a"].tolist() == [5.0, 6.0]
    assert "Label" not in out.X.columns  # the target never enters model inputs


def test_missing_feature_is_an_error(schema):
    with pytest.raises(PreprocessingError, match="missing required features"):
        Preprocessor(schema).transform(frame(a=[1.0], b=[1.0]))


def test_non_numeric_is_an_error(schema):
    with pytest.raises(PreprocessingError, match="non-numeric"):
        Preprocessor(schema).transform(frame(a=["x"], b=[1.0], c=[1.0]))


def test_nonfinite_rows_rejected_without_imputation(schema):
    df = frame(a=[1.0, np.nan, 3.0], b=[1.0, 1.0, np.inf], c=[0.0, 0.0, 0.0])
    out = Preprocessor(schema).transform(df)
    assert out.X.index.tolist() == [0]
    assert out.rejected_index.tolist() == [1, 2]


def test_transform_requires_fit_when_stateful(schema):
    pp = Preprocessor(schema, PreprocessingConfig(scaling="standard"))
    with pytest.raises(PreprocessingError, match="fitted"):
        pp.transform(frame(a=[1.0], b=[1.0], c=[1.0]))


def test_statistics_come_from_training_data_only(schema):
    train = frame(a=[0.0, 2.0, np.nan], b=[1.0, 1.0, 1.0], c=[10.0, 20.0, 30.0])
    test = frame(a=[np.nan, 1000.0], b=[1.0, 1.0], c=[1000.0, 2000.0])
    pp = Preprocessor(schema, PreprocessingConfig(imputation="median", scaling="standard")).fit(train)
    out = pp.transform(test).X
    # imputed with the TRAIN median (1.0) and scaled by TRAIN mean/std, unaffected by test values
    train_a = pd.Series([0.0, 2.0, 1.0])
    expected = (1.0 - train_a.mean()) / train_a.std(ddof=0)
    assert out.loc[0, "a"] == pytest.approx(expected)
    v1 = pp.version_id
    pp.transform(test)
    assert pp.version_id == v1  # transform never refits


def test_cannot_refit(schema):
    pp = Preprocessor(schema, PreprocessingConfig(scaling="minmax")).fit(frame(a=[0.0, 1.0], b=[0.0, 1.0], c=[0.0, 1.0]))
    with pytest.raises(PreprocessingError, match="already fitted"):
        pp.fit(frame(a=[0.0], b=[0.0], c=[0.0]))


def test_json_roundtrip_preserves_behaviour(schema, tmp_path):
    train = frame(a=[0.0, 4.0], b=[1.0, 3.0], c=[5.0, 7.0])
    pp = Preprocessor(schema, PreprocessingConfig(imputation="median", scaling="standard")).fit(train)
    path = tmp_path / "pp.json"
    pp.save(path)
    assert path.read_text().lstrip().startswith("{")  # JSON, not a pickle
    pp2 = Preprocessor.load(path)
    assert pp2.version_id == pp.version_id
    test = frame(a=[1.0, np.nan], b=[2.0, 2.0], c=[6.0, 6.0])
    pd.testing.assert_frame_equal(pp.transform(test).X, pp2.transform(test).X)


def test_tampered_state_detected(schema, tmp_path):
    pp = Preprocessor(schema, PreprocessingConfig(imputation="median")).fit(frame(a=[1.0], b=[1.0], c=[1.0]))
    d = pp.to_dict()
    d["state"]["medians"]["a"] = 99.0
    with pytest.raises(PreprocessingError, match="version_id"):
        Preprocessor.from_dict(d)


def test_invalid_config():
    with pytest.raises(PreprocessingError):
        PreprocessingConfig(scaling="smote")
