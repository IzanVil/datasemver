import pandas as pd
import pytest

from datasemver.core.differ import diff_schemas
from datasemver.formats.loader import (
    DatasetReadError,
    UnsupportedFormatError,
    detect_delimiter,
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


def test_tab_separated_file(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("id\tname\tscore\n1\tana\t10.5\n2\tbruno\t11.0\n", encoding="utf-8")

    frame = load_frame(path)

    assert list(frame.columns) == ["id", "name", "score"]
    assert canonical_dtype(frame["score"]) == "float64"


def test_semicolon_delimiter_is_detected(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id;name\n1;ana\n2;bruno\n", encoding="utf-8")

    frame = load_frame(path)

    assert list(frame.columns) == ["id", "name"]
    assert frame["name"].tolist() == ["ana", "bruno"]


def test_pipe_delimiter_is_detected(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id|name|score\n1|ana|10\n2|bruno|11\n", encoding="utf-8")

    assert list(load_frame(path).columns) == ["id", "name", "score"]


def test_tab_delimiter_inside_a_csv_extension(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id\tname\n1\tana\n2\tbruno\n", encoding="utf-8")

    assert list(load_frame(path).columns) == ["id", "name"]


def test_delimiters_inside_quoted_values_do_not_win(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text(
        'id,name\n1,"Ruiz; Ana"\n2,"Diaz; Bruno"\n',
        encoding="utf-8",
    )

    frame = load_frame(path)

    assert list(frame.columns) == ["id", "name"]
    assert frame["name"].tolist() == ["Ruiz; Ana", "Diaz; Bruno"]


def test_a_single_column_file_falls_back_to_the_comma(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id\n1\n2\n", encoding="utf-8")

    assert list(load_frame(path).columns) == ["id"]


def test_an_inconsistent_candidate_is_ignored(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id;name\n1;ana;extra\n2;bruno\n", encoding="utf-8")

    assert detect_delimiter(path) == ","


def test_delimiter_detection_of_an_empty_file(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("", encoding="utf-8")

    assert detect_delimiter(path) == ","


def test_the_comma_wins_a_tie(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b;c\n1,2;3\n", encoding="utf-8")

    assert detect_delimiter(path) == ","


def test_tsv_extension_forces_the_tab(tmp_path):
    path = tmp_path / "data.tsv"
    path.write_text("id,with,commas\tname\n1,2,3\tana\n", encoding="utf-8")

    assert list(load_frame(path).columns) == ["id,with,commas", "name"]


def test_duplicate_headers_are_disambiguated(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id,score,score\n1,10,20\n2,11,21\n", encoding="utf-8")

    schema = load_schema(path)

    assert schema.column_names == ["id", "score", "score.1"]
    assert schema.columns["score"].mean == pytest.approx(10.5)
    assert schema.columns["score.1"].mean == pytest.approx(20.5)


def test_missing_values_are_counted_as_nulls(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id,email,score\n1,,10\n2,b@x.com,\n3,c@x.com,12\n4,,13\n", encoding="utf-8")

    schema = load_schema(path)

    assert schema.columns["email"].null_ratio == pytest.approx(0.5)
    assert schema.columns["score"].null_ratio == pytest.approx(0.25)
    assert schema.columns["score"].dtype == "float64"


def test_column_of_only_nulls(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id,note\n1,\n2,\n", encoding="utf-8")

    stats = load_schema(path).columns["note"]

    assert stats.null_ratio == 1.0
    assert stats.cardinality == 0
    assert stats.mean is None
    assert stats.categories is None


def test_deeply_nested_json(tmp_path):
    path = tmp_path / "data.json"
    path.write_text(
        '[{"id": 1, "user": {"address": {"city": "Madrid", "zip": "28004"}}},'
        ' {"id": 2, "user": {"address": {"city": "Bilbao", "zip": "48001"}}}]',
        encoding="utf-8",
    )

    frame = load_frame(path)

    assert sorted(frame.columns) == ["id", "user.address.city", "user.address.zip"]


def test_json_records_with_missing_keys(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('[{"id": 1, "plan": "pro"}, {"id": 2}]', encoding="utf-8")

    schema = load_schema(path)

    assert schema.columns["plan"].null_ratio == pytest.approx(0.5)


def test_json_object_is_read_as_a_single_row(tmp_path):
    path = tmp_path / "data.json"
    path.write_text('{"id": 1, "score": 10}', encoding="utf-8")

    assert len(load_frame(path)) == 1


def test_empty_json_array(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("[]", encoding="utf-8")

    schema = load_schema(path)

    assert schema.row_count == 0
    assert schema.column_names == []


def test_empty_file_is_rejected(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(ValueError):
        load_frame(path)


def test_header_only_csv(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("id,name\n", encoding="utf-8")

    schema = load_schema(path)

    assert schema.row_count == 0
    assert schema.columns["id"].null_ratio == 0.0


def test_malformed_json_is_rejected(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("{not json at all", encoding="utf-8")

    with pytest.raises(ValueError):
        load_frame(path)


def test_parquet_preserves_datetimes(tmp_path):
    path = tmp_path / "events.parquet"
    frame = pd.DataFrame({"seen_at": pd.to_datetime(["2026-01-01", "2026-02-01"])})
    frame.to_parquet(path)

    assert canonical_dtype(load_frame(path)["seen_at"]) == "datetime64"


def test_parquet_with_nulls(tmp_path):
    path = tmp_path / "scores.parquet"
    pd.DataFrame({"score": [1.0, None, 3.0, None]}).to_parquet(path)

    stats = load_schema(path).columns["score"]

    assert stats.null_ratio == pytest.approx(0.5)
    assert stats.mean == pytest.approx(2.0)


def test_date_like_strings_that_do_not_parse_stay_strings(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("seen_at\n2024-13-45\n2024-99-01\n", encoding="utf-8")

    assert load_schema(path).columns["seen_at"].dtype == "string"


def test_empty_json_file_is_read_as_an_empty_dataset(tmp_path):
    path = tmp_path / "data.json"
    path.write_text("   ", encoding="utf-8")

    schema = load_schema(path)

    assert schema.row_count == 0
    assert schema.column_names == []


def test_parquet_without_pyarrow_explains_itself(tmp_path, monkeypatch):
    path = tmp_path / "data.parquet"
    pd.DataFrame({"id": [1]}).to_parquet(path)

    def raise_import_error(*args, **kwargs):
        raise ImportError("no pyarrow")

    monkeypatch.setattr(pd, "read_parquet", raise_import_error)

    with pytest.raises(DatasetReadError, match="pyarrow"):
        load_parquet(path)


def test_delimiter_detection_only_samples_the_first_lines(tmp_path):
    path = tmp_path / "data.csv"
    header_and_rows = ["id;name"] + [f"{index};name{index}" for index in range(50)]
    path.write_text("\n".join(header_and_rows) + "\n", encoding="utf-8")

    assert detect_delimiter(path) == ";"
    assert len(load_frame(path)) == 50
