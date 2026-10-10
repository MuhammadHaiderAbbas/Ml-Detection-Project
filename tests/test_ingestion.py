import threading

import numpy as np
import pytest
from conftest import make_rows

from adaptive_ids.ingestion import (
    ROW_NUMBER_COLUMN,
    DatasetIntegrityError,
    DatasetNotFoundError,
    ImportCancelledError,
    ImportLimitError,
    ImportLimits,
    SchemaMismatchError,
    import_csv,
    preview_csv,
)
from adaptive_ids.schema import FeatureSchema

KW = dict(dataset_name="t", dataset_version="1", provenance="synthetic_demo")


def test_valid_import_records_metadata(schema, write_csv):
    path = write_csv(make_rows(20))
    res = import_csv(path, schema, **KW)
    r = res.record
    assert r.status == "completed"
    assert (r.total_rows, r.accepted_rows, r.rejected_rows) == (20, 20, 0)
    assert len(r.file_sha256) == 64 and r.schema_id == "test-schema@1.0.0"
    assert r.started_at and r.completed_at
    assert list(res.data.columns[:3]) == ["a", "b", "c"]
    assert res.data[ROW_NUMBER_COLUMN].tolist() == list(range(1, 21))
    assert "Src IP" not in res.data.columns  # excluded columns never pass through
    assert r.label_distribution == {"Benign": 15, "DoS": 5}


def test_invalid_rows_rejected_with_reasons(schema, write_csv):
    rows = make_rows(8)
    rows[1]["a"] = "abc"
    rows[2]["b"] = "1.5"
    rows[3]["c"] = "Infinity"
    rows[4]["a"] = ""
    rows[5]["a"] = "-1"
    rows[6]["c"] = "101"
    rows[7]["Label"] = ""
    res = import_csv(write_csv(rows), schema, **KW)
    assert res.record.accepted_rows == 1
    assert res.record.rejected_rows == 7
    reasons = dict(zip(res.rejected[ROW_NUMBER_COLUMN], res.rejected["reasons"]))
    assert reasons[2] == "a:invalid_type"
    assert reasons[3] == "b:not_integer"
    assert reasons[4] == "c:infinite"
    assert reasons[5] == "a:missing"
    assert reasons[6] == "a:below_min"
    assert reasons[7] == "c:above_max"
    assert reasons[8] == "Label:missing_label"


def test_repeated_header_row_rejected(schema, write_csv):
    rows = make_rows(3)
    rows[1] = {k: k for k in rows[0]}
    res = import_csv(write_csv(rows), schema, **KW)
    assert res.record.rejected_rows == 1
    assert "repeated_header_row" in res.rejected["reasons"].iloc[0]


def test_keep_as_missing_policies(write_csv, schema):
    lenient = FeatureSchema.from_dict(
        {**schema.to_dict(), "missing_value_policy": "keep_as_missing", "infinite_value_policy": "treat_as_missing"}
    )
    rows = make_rows(3)
    rows[0]["a"] = ""
    rows[1]["c"] = "inf"
    res = import_csv(write_csv(rows), lenient, **KW)
    assert res.record.accepted_rows == 3
    assert np.isnan(res.data.loc[0, "a"]) and np.isnan(res.data.loc[1, "c"])


def test_missing_file_is_never_substituted(schema, tmp_path):
    with pytest.raises(DatasetNotFoundError) as exc:
        import_csv(tmp_path / "nope.csv", schema, **KW)
    assert exc.value.record.status == "failed"


def test_missing_columns_fail(schema, write_csv):
    rows = [{k: v for k, v in r.items() if k != "b"} for r in make_rows(3)]
    with pytest.raises(SchemaMismatchError, match="missing=\\['b'\\]"):
        import_csv(write_csv(rows), schema, **KW)


def test_column_mapping_and_header_whitespace(schema, write_csv):
    rows = [{(" A " if k == "a" else k): v for k, v in r.items()} for r in make_rows(3)]
    res = import_csv(write_csv(rows), schema, column_mapping={"A": "a"}, **KW)
    assert res.record.accepted_rows == 3


def test_hash_mismatch_fails(schema, write_csv):
    with pytest.raises(DatasetIntegrityError):
        import_csv(write_csv(make_rows(3)), schema, expected_sha256="0" * 64, **KW)


def test_limits(schema, write_csv):
    path = write_csv(make_rows(30))
    with pytest.raises(ImportLimitError):
        import_csv(path, schema, limits=ImportLimits(max_file_bytes=10), **KW)
    with pytest.raises(ImportLimitError):
        import_csv(path, schema, limits=ImportLimits(max_rows=10, chunk_rows=5), **KW)


def test_chunked_import_matches_single_chunk(schema, write_csv):
    rows = make_rows(50)
    rows[17]["a"] = "bad"
    path = write_csv(rows)
    one = import_csv(path, schema, **KW)
    many = import_csv(path, schema, limits=ImportLimits(chunk_rows=7), **KW)
    assert one.data.equals(many.data)
    assert one.rejected.equals(many.rejected)


def test_duplicates_counted_and_optionally_dropped(schema, write_csv):
    rows = make_rows(5)
    rows.append(dict(rows[0], **{"Flow ID": "dup"}))
    path = write_csv(rows)
    assert import_csv(path, schema, **KW).record.duplicate_rows == 1
    dropped = import_csv(path, schema, duplicate_policy="drop", **KW)
    assert dropped.record.accepted_rows == 5 and dropped.record.duplicates_dropped == 1


def test_cancellation(schema, write_csv):
    ev = threading.Event()
    ev.set()
    with pytest.raises(ImportCancelledError) as exc:
        import_csv(write_csv(make_rows(5)), schema, cancel_event=ev, **KW)
    assert exc.value.record.status == "cancelled"


def test_progress_callback(schema, write_csv):
    seen = []
    import_csv(write_csv(make_rows(10)), schema, limits=ImportLimits(chunk_rows=4), progress=seen.append, **KW)
    assert seen == [4, 8, 10]


def test_preview(schema, write_csv):
    res = preview_csv(write_csv(make_rows(10)), schema, n_rows=3)
    assert len(res["rows"]) == 3
    assert res["compatibility"]["missing"] == []


def test_duplicate_header_columns_fail(schema, tmp_path):
    path = tmp_path / "dup.csv"
    path.write_text("a,a,b,c,Label\n1,2,3,4,Benign\n")
    with pytest.raises(SchemaMismatchError, match="duplicated=\\['a'\\]"):
        import_csv(path, schema, **KW)
