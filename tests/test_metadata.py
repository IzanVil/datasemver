"""Tests for profiling a Parquet file from its footer instead of its rows.

The footer is a promise about what the file holds, and the point of reading it is to answer
the schema-level questions without decoding anything. So these check both halves of that: it
says the true thing about the schema, and it does not pretend to know the things only the data
could tell it.
"""

from __future__ import annotations

import pandas as pd
import pytest

from datasemver import analyze
from datasemver.core.models import ChangeType, Severity
from datasemver.formats.loader import load_schema
from datasemver.formats.metadata import MetadataError, schema_from_metadata


@pytest.fixture
def sample(tmp_path):
    path = tmp_path / "sample.parquet"
    pd.DataFrame(
        {
            "id": range(100),
            "amount": [float(index) for index in range(100)],
            "label": ["a", "b"] * 50,
            "note": [None] * 100,
        }
    ).to_parquet(path, index=False)
    return path


def test_the_columns_and_their_types_come_out_of_the_footer(sample):
    schema = schema_from_metadata(sample, source="sample.parquet")

    assert schema.row_count == 100
    assert schema.columns["id"].dtype == "int64"
    assert schema.columns["amount"].dtype == "float64"
    assert schema.columns["label"].dtype == "string"


def test_the_null_ratio_comes_out_of_the_footer(sample):
    schema = schema_from_metadata(sample, source="sample.parquet")

    assert schema.columns["note"].null_ratio == 1.0
    assert schema.columns["id"].null_ratio == 0.0


def test_the_range_of_a_numeric_column_comes_out_of_the_footer(sample):
    schema = schema_from_metadata(sample, source="sample.parquet")

    assert schema.columns["id"].minimum == 0.0
    assert schema.columns["id"].maximum == 99.0


def test_a_text_column_has_no_numeric_range(sample):
    """Parquet records the smallest and largest string, which is not a range to compare."""
    schema = schema_from_metadata(sample, source="sample.parquet")

    assert schema.columns["label"].minimum is None


def test_the_footer_carries_nothing_to_compare_distributions_with(sample):
    """The honest half: without reading data there is no shape, and none is invented."""
    schema = schema_from_metadata(sample, source="sample.parquet")

    assert all(column.quantiles is None for column in schema.columns.values())
    assert all(column.category_counts is None for column in schema.columns.values())


def test_a_file_that_is_not_parquet_is_refused(tmp_path):
    broken = tmp_path / "broken.parquet"
    broken.write_text("not a parquet file", encoding="utf-8")

    with pytest.raises(MetadataError, match="could not read the Parquet footer"):
        schema_from_metadata(broken, source="broken.parquet")


# --- through the analysis ---------------------------------------------------------------------


def test_the_footer_answers_the_breaking_questions(tmp_path):
    old = tmp_path / "old.parquet"
    new = tmp_path / "new.parquet"
    pd.DataFrame({"id": range(50), "amount": [1.0] * 50, "legacy": ["x"] * 50}).to_parquet(old)
    pd.DataFrame({"id": range(50), "amount": ["1.0"] * 50}).to_parquet(new)

    report = analyze(old, new, current_version="1.0.0", schema_only=True)

    types = {change.type for change in report.diff.changes}
    assert ChangeType.COLUMN_REMOVED in types
    assert ChangeType.TYPE_CHANGED_INCOMPATIBLE in types
    assert report.bump is Severity.MAJOR


def test_the_footer_is_only_read_when_it_is_asked_for(tmp_path):
    """The default has to stay the full read, or the distribution comparison would vanish."""
    path = tmp_path / "data.parquet"
    pd.DataFrame({"amount": [float(index) for index in range(200)]}).to_parquet(path)

    assert load_schema(path).columns["amount"].quantiles
    assert load_schema(path, schema_only=True).columns["amount"].quantiles is None


def test_a_format_with_no_footer_is_still_read(tmp_path):
    """`--schema-only` is a Parquet shortcut; a CSV has nowhere else to get its schema from."""
    path = tmp_path / "data.csv"
    pd.DataFrame({"amount": [float(index) for index in range(200)]}).to_csv(path, index=False)

    assert load_schema(path, schema_only=True).columns["amount"].quantiles


def test_a_stored_profile_is_still_read_as_one(tmp_path):
    """A profile already holds everything, so the flag must not reach past it."""
    from datasemver.core.profile import write_profile

    source = tmp_path / "data.parquet"
    pd.DataFrame({"amount": [float(index) for index in range(200)]}).to_parquet(source)
    stored = write_profile(load_schema(source), tmp_path / "data.profile.json")

    assert load_schema(stored, schema_only=True).columns["amount"].quantiles


def test_an_all_null_column_is_reported_as_all_null(sample):
    """Its Arrow type is `null`, which carries no statistics; reading that as no nulls is wrong."""
    schema = schema_from_metadata(sample, source="sample.parquet")

    assert schema.columns["note"].null_ratio == 1.0
    assert schema.columns["note"].cardinality == 0


def test_a_footer_without_statistics_is_refused_rather_than_read_as_zero(tmp_path):
    """A partial count presented as a whole one turns a nulls change into no change."""
    import pyarrow as pa
    import pyarrow.parquet as pq

    path = tmp_path / "bare.parquet"
    table = pa.table({"amount": [1.0, 2.0, None]})
    pq.write_table(table, path, write_statistics=False)

    with pytest.raises(MetadataError, match="no statistics for column 'amount'"):
        schema_from_metadata(path, source="bare.parquet")


def test_a_database_url_is_never_mistaken_for_a_parquet_file():
    """A URL ending in `.parquet` is still a connection string, not a file with a footer."""
    from datasemver.formats.loader import _is_parquet_file

    assert not _is_parquet_file("sqlite:///data.parquet#customers")
    assert _is_parquet_file("snapshots/data.parquet")
