import pandas as pd
import pytest

from datasemver.core.differ import diff_schemas
from datasemver.formats.loader import (
    DatasetReadError,
    UnsupportedFormatError,
    load_frame,
    load_parquet,
    load_schema,
)
from datasemver.formats.utils import canonical_dtype, infer_types


def test_load_csv_columns_and_types(old_csv):
    frame = load_frame(old_csv)

    assert list(frame.columns) == [
        "id",
        "name",
        "email",
        "phone",
        "age",
        "score",
        "legacy_code",
    ]
    assert canonical_dtype(frame["id"]) == "int64"
    assert canonical_dtype(frame["score"]) == "float64"
    assert canonical_dtype(frame["name"]) == "string"


def test_load_json_array_flattens_nested_objects(old_json):
    frame = load_frame(old_json)

    assert "user.name" in frame.columns
    assert "user.city" in frame.columns
    assert len(frame) == 4


def test_load_json_lines(new_json):
    frame = load_frame(new_json)

    assert len(frame) == 5
    assert frame["plan"].tolist() == ["pro", "free", "pro", "free", "pro"]


def test_schema_profiles_nulls_and_cardinality(old_csv):
    schema = load_schema(old_csv)

    assert schema.row_count == 8
    assert schema.columns["email"].null_ratio == pytest.approx(0.25)
    assert schema.columns["email"].cardinality == 6
    assert schema.columns["score"].mean == pytest.approx(72.46875)


def test_boolean_and_datetime_inference():
    frame = pd.DataFrame(
        {
            "flag": ["true", "false", "true"],
            "created_at": ["2024-01-01", "2024-02-15", "2024-03-30"],
            "label": ["a", "b", "c"],
        }
    )

    inferred = infer_types(frame)

    assert canonical_dtype(inferred["flag"]) == "bool"
    assert canonical_dtype(inferred["created_at"]) == "datetime64"
    assert canonical_dtype(inferred["label"]) == "string"


def test_numeric_strings_are_not_parsed_as_dates():
    frame = pd.DataFrame({"code": ["001", "002", "003"]})

    assert canonical_dtype(infer_types(frame)["code"]) == "int64"


def test_load_parquet_columns_and_types(old_parquet):
    frame = load_parquet(old_parquet)

    assert list(frame.columns) == [
        "id",
        "name",
        "email",
        "phone",
        "age",
        "score",
        "legacy_code",
    ]
    assert canonical_dtype(frame["phone"]) == "int64"
    assert canonical_dtype(frame["score"]) == "float64"
    assert canonical_dtype(frame["legacy_code"]) == "string"


def test_parquet_is_loaded_through_the_shared_entry_point(new_parquet):
    frame = load_frame(new_parquet)

    assert len(frame) == 10
    assert canonical_dtype(frame["phone"]) == "string"


def test_parquet_schema_matches_the_csv_profile(old_csv, old_parquet):
    from_csv = load_schema(old_csv)
    from_parquet = load_schema(old_parquet)

    assert from_parquet.row_count == from_csv.row_count
    assert from_parquet.column_names == from_csv.column_names
    for name, stats in from_parquet.columns.items():
        assert stats.dtype == from_csv.columns[name].dtype
        assert stats.null_ratio == from_csv.columns[name].null_ratio
        assert stats.cardinality == from_csv.columns[name].cardinality


def test_parquet_and_csv_produce_the_same_changes(old_csv, new_csv, old_parquet, new_parquet):
    from_csv = diff_schemas(load_schema(old_csv), load_schema(new_csv))
    from_parquet = diff_schemas(load_schema(old_parquet), load_schema(new_parquet))

    assert [change.description for change in from_parquet.changes] == [
        change.description for change in from_csv.changes
    ]


def test_parquet_schema_is_authoritative(tmp_path):
    path = tmp_path / "codes.parquet"
    pd.DataFrame({"zip_code": pd.Series(["08001", "28004"], dtype="string")}).to_parquet(path)

    assert canonical_dtype(load_frame(path)["zip_code"]) == "string"


def test_parquet_struct_columns_are_flattened(tmp_path):
    path = tmp_path / "nested.parquet"
    frame = pd.DataFrame(
        {
            "id": [1, 2],
            "user": [{"name": "ana", "city": "Madrid"}, {"name": "bruno", "city": "Sevilla"}],
        }
    )
    frame.to_parquet(path)

    loaded = load_frame(path)

    assert sorted(loaded.columns) == ["id", "user.city", "user.name"]
    assert loaded["user.name"].tolist() == ["ana", "bruno"]


def test_pq_extension_is_recognised(tmp_path, old_parquet):
    path = tmp_path / "dataset.pq"
    path.write_bytes(old_parquet.read_bytes())

    assert len(load_frame(path)) == 8


def test_corrupt_parquet_file(tmp_path):
    path = tmp_path / "broken.parquet"
    path.write_bytes(b"this is not a parquet file")

    with pytest.raises(DatasetReadError):
        load_frame(path)


def test_missing_parquet_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_parquet(tmp_path / "absent.parquet")


def test_unsupported_extension(tmp_path):
    path = tmp_path / "data.avro"
    path.write_text("noop", encoding="utf-8")

    with pytest.raises(UnsupportedFormatError):
        load_frame(path)


def test_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_frame(tmp_path / "absent.csv")
