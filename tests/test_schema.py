import pytest

from adaptive_ids.schema import FeatureSchema, SchemaError

BASE = {"name": "s", "version": "1", "label_column": "Label", "features": [{"name": "x"}]}


def test_roundtrip_and_stable_hash(schema, tmp_path):
    p = tmp_path / "s.json"
    schema.save(p)
    loaded = FeatureSchema.load(p)
    assert loaded == schema
    assert loaded.schema_hash == schema.schema_hash
    assert loaded.feature_names == ["a", "b", "c"]


@pytest.mark.parametrize(
    "patch",
    [
        {"features": [{"name": "Label"}]},  # label used as a feature
        {"features": [{"name": "ts"}], "timestamp_column": "ts"},
        {"features": [{"name": "ip"}], "excluded_columns": ["ip"]},
        {"features": [{"name": "x"}, {"name": "x"}]},
        {"features": []},
        {"features": [{"name": "x", "dtype": "string"}]},
        {"features": [{"name": "x", "min": 5, "max": 1}]},
        {"missing_value_policy": "guess"},
    ],
)
def test_invalid_schemas_rejected(patch):
    with pytest.raises(SchemaError):
        FeatureSchema.from_dict({**BASE, **patch})


def test_hash_changes_with_feature_order():
    a = FeatureSchema.from_dict({**BASE, "features": [{"name": "x"}, {"name": "y"}]})
    b = FeatureSchema.from_dict({**BASE, "features": [{"name": "y"}, {"name": "x"}]})
    assert a.schema_hash != b.schema_hash


def test_shipped_schemas_load():
    from conftest import REPO_ROOT

    for p in (REPO_ROOT / "configs" / "schemas").glob("*.json"):
        s = FeatureSchema.load(p)
        assert s.label_column == "Label"
    cand = FeatureSchema.load(REPO_ROOT / "configs/schemas/cse-cic-ids2018.candidate.json")
    assert cand.status == "unverified"
