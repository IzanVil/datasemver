"""Tests for the row-level comparison, which is the one that needs the data itself.

A profile cannot answer "which rows changed?": a version where a third of the rows were
rewritten with values drawn the same way has the same profile as the one before it. So this
is the part of the library that loads both datasets, and the tests are about what it says
when it does -- and about refusing, loudly, the keys that cannot identify a row.
"""

from __future__ import annotations

import pandas as pd
import pytest

from datasemver import analyze
from datasemver.core.models import ChangeType
from datasemver.core.rows import KeyError_, compare_rows


def frame(**columns: list) -> pd.DataFrame:
    return pd.DataFrame(columns)


def compare(old: pd.DataFrame, new: pd.DataFrame, key: list[str] | None = None):
    return compare_rows(old, new, key or ["id"], "old.csv", "new.csv")


def of_type(changes, wanted: ChangeType):
    return next(change for change in changes if change.type is wanted)


# --- what it reports ------------------------------------------------------------------------


def test_rows_that_changed_value_are_counted():
    old = frame(id=[1, 2, 3], v=["a", "b", "c"])
    new = frame(id=[1, 2, 3], v=["a", "B", "C"])

    change = of_type(compare(old, new), ChangeType.ROWS_MODIFIED)

    assert change.metrics["rows_modified"] == 2
    assert change.metrics["modified_pct"] == pytest.approx(66.6667, abs=0.01)


def test_the_columns_that_changed_are_named_with_their_counts():
    """A count alone says something happened; the columns say where to look."""
    old = frame(id=[1, 2, 3], name=["a", "b", "c"], score=[1, 2, 3])
    new = frame(id=[1, 2, 3], name=["a", "b", "Z"], score=[9, 9, 9])

    change = of_type(compare(old, new), ChangeType.ROWS_MODIFIED)

    assert change.details["columns"] == {"score": 3, "name": 1}
    assert "score (3)" in change.description


def test_rows_added_and_removed_are_counted_separately_from_changes():
    old = frame(id=[1, 2, 3], v=["a", "b", "c"])
    new = frame(id=[2, 3, 4], v=["b", "c", "d"])

    change = of_type(compare(old, new), ChangeType.ROWS_REPLACED)

    assert change.metrics["rows_added"] == 1
    assert change.metrics["rows_removed"] == 1


def test_identical_datasets_report_nothing():
    rows = frame(id=[1, 2, 3], v=["a", "b", "c"])

    assert compare(rows, rows.copy()) == []


def test_a_reordered_dataset_is_not_a_change():
    """Rows are matched by key, so the order they arrive in carries no meaning."""
    old = frame(id=[1, 2, 3], v=["a", "b", "c"])
    new = frame(id=[3, 1, 2], v=["c", "a", "b"])

    assert compare(old, new) == []


def test_a_composite_key_matches_on_every_part():
    old = frame(a=[1, 1, 2], b=[1, 2, 1], v=["x", "y", "z"])
    new = frame(a=[1, 1, 2], b=[1, 2, 1], v=["x", "Y", "z"])

    change = of_type(compare(old, new, ["a", "b"]), ChangeType.ROWS_MODIFIED)

    assert change.metrics["rows_modified"] == 1


def test_a_value_that_only_changed_representation_is_not_a_change():
    """`1` read on one side and `1.0` on the other is the same number in two spellings."""
    old = frame(id=[1, 2], v=[1, 2])
    new = frame(id=[1, 2], v=[1.0, 2.0])

    assert compare(old, new) == []


def test_two_nulls_are_the_same_value():
    """Compared with `==` a null equals nothing, itself included, so every row would differ."""
    old = frame(id=[1, 2], v=[None, "b"])
    new = frame(id=[1, 2], v=[None, "b"])

    assert compare(old, new) == []


def test_a_column_only_one_version_has_is_left_to_the_schema_comparison():
    """Counting every row as modified for an added column would bury the rows that changed."""
    old = frame(id=[1, 2], v=["a", "b"])
    new = frame(id=[1, 2], v=["a", "b"], extra=["x", "y"])

    assert compare(old, new) == []


def test_a_dataset_sharing_no_keys_reports_only_the_replacement():
    old = frame(id=[1, 2], v=["a", "b"])
    new = frame(id=[3, 4], v=["c", "d"])

    changes = compare(old, new)

    assert of_type(changes, ChangeType.ROWS_REPLACED).metrics["rows_added"] == 2
    assert ChangeType.ROWS_MODIFIED not in {change.type for change in changes}


# --- keys that cannot identify a row ----------------------------------------------------------


def test_a_key_that_is_not_a_column_is_refused_by_name():
    rows = frame(id=[1, 2], v=["a", "b"])

    with pytest.raises(KeyError_, match="no column 'nope' to key on"):
        compare(rows, rows.copy(), ["nope"])


def test_a_repeated_key_is_refused_with_its_count():
    """Which of the rows sharing a key is the one that changed? There is no answer to guess."""
    old = frame(id=[1, 1, 2], v=["a", "a", "b"])
    new = frame(id=[1, 2], v=["a", "b"])

    with pytest.raises(KeyError_, match=r"1 row\(s\) repeat a key"):
        compare(old, new)


def test_a_repeated_key_on_the_new_side_is_refused_too():
    old = frame(id=[1, 2], v=["a", "b"])
    new = frame(id=[1, 1, 2], v=["a", "a", "b"])

    with pytest.raises(KeyError_, match=r"new\.csv does not have one row per id"):
        compare(old, new)


# --- through the analysis -----------------------------------------------------------------------


def test_the_row_changes_are_classified_like_any_other(tmp_path):
    """They go through the same rules and the same versioning, not a separate result."""
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    frame(id=[1, 2, 3, 4], v=["a", "b", "c", "d"]).to_csv(old, index=False)
    frame(id=[1, 2, 3, 4], v=["a", "b", "Z", "W"]).to_csv(new, index=False)

    report = analyze(old, new, current_version="1.0.0", key=["id"])

    modified = next(
        item for item in report.classified if item.change.type is ChangeType.ROWS_MODIFIED
    )
    assert modified.severity is not None
    assert modified.rule == "rows_modified"


def test_without_a_key_the_rows_are_not_compared(tmp_path):
    """It needs both datasets in memory, so it stays opt-in rather than becoming the default."""
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    frame(id=[1, 2, 3, 4], v=["a", "b", "c", "d"]).to_csv(old, index=False)
    frame(id=[1, 2, 3, 4], v=["a", "b", "Z", "W"]).to_csv(new, index=False)

    report = analyze(old, new, current_version="1.0.0")

    assert ChangeType.ROWS_MODIFIED not in {c.type for c in report.diff.changes}
