import pandas as pd

from datasemver.core.differ import DiffConfig, diff_schemas
from datasemver.core.models import ChangeType, ColumnStatus
from datasemver.formats.loader import load_schema, schema_from_frame


def diff_frames(old: pd.DataFrame, new: pd.DataFrame, config: DiffConfig | None = None):
    return diff_schemas(
        schema_from_frame(old, "old"),
        schema_from_frame(new, "new"),
        config=config,
    )


def test_column_removed_and_added(old_csv, new_csv):
    diff = diff_frames(pd.read_csv(old_csv), pd.read_csv(new_csv))

    removed = diff.of_type(ChangeType.COLUMN_REMOVED)
    added = diff.of_type(ChangeType.COLUMN_ADDED)

    assert [change.column for change in removed] == ["legacy_code"]
    assert [change.column for change in added] == ["country"]


def test_incompatible_type_change(old_csv, new_csv):
    diff = diff_schemas(load_schema(old_csv), load_schema(new_csv))

    changes = diff.of_type(ChangeType.TYPE_CHANGED_INCOMPATIBLE)

    assert [change.column for change in changes] == ["phone"]
    assert changes[0].details == {"dtype_old": "int64", "dtype_new": "string"}


def test_widening_type_change_is_compatible():
    diff = diff_frames(
        pd.DataFrame({"amount": [1, 2, 3]}),
        pd.DataFrame({"amount": [1.0, 2.0, 3.0]}),
    )

    assert [change.type for change in diff.of_type(ChangeType.TYPE_CHANGED_COMPATIBLE)] == [
        ChangeType.TYPE_CHANGED_COMPATIBLE
    ]


def test_nulls_fixed(old_csv, new_csv):
    diff = diff_schemas(load_schema(old_csv), load_schema(new_csv))

    changes = diff.of_type(ChangeType.NULLS_FIXED)

    assert [change.column for change in changes] == ["email"]
    assert changes[0].metrics["null_ratio_old"] == 25.0
    assert changes[0].metrics["null_ratio_new"] == 0.0


def test_nulls_introduced():
    diff = diff_frames(
        pd.DataFrame({"email": ["a@x.com", "b@x.com", "c@x.com", "d@x.com"]}),
        pd.DataFrame({"email": ["a@x.com", None, "c@x.com", None]}),
    )

    changes = diff.of_type(ChangeType.NULLS_INTRODUCED)

    assert changes[0].metrics["delta_pct"] == 50.0


def test_row_count_changes():
    grew = diff_frames(pd.DataFrame({"a": [1, 2]}), pd.DataFrame({"a": [1, 2, 3]}))
    shrank = diff_frames(pd.DataFrame({"a": [1, 2, 3, 4]}), pd.DataFrame({"a": [1]}))

    assert grew.of_type(ChangeType.ROW_COUNT_INCREASED)[0].metrics["increase_pct"] == 50.0
    assert shrank.of_type(ChangeType.ROW_COUNT_DECREASED)[0].metrics["decrease_pct"] == 75.0


def test_new_category_detected():
    diff = diff_frames(
        pd.DataFrame({"country": ["ES", "ES", "FR", "FR", "ES", "FR"]}),
        pd.DataFrame({"country": ["ES", "FR", "IT", "IT", "ES", "FR"]}),
    )

    change = diff.of_type(ChangeType.NEW_CATEGORY_ADDED)[0]

    assert change.details["categories"] == ["IT"]
    assert change.metrics["added_count"] == 1.0


def test_distribution_shift_beats_minor_stat_change():
    old = pd.DataFrame({"score": [10.0, 11.0, 9.0, 10.5, 9.5]})
    new = pd.DataFrame({"score": [40.0, 41.0, 39.0, 40.5, 39.5]})

    diff = diff_frames(old, new)

    assert diff.of_type(ChangeType.DISTRIBUTION_SHIFT)
    assert not diff.of_type(ChangeType.MINOR_STAT_CHANGE)


def test_small_stat_move_is_minor():
    old = pd.DataFrame({"score": [10.0, 20.0, 30.0, 40.0]})
    new = pd.DataFrame({"score": [10.0, 20.0, 30.0, 41.0]})

    diff = diff_frames(old, new)

    assert diff.of_type(ChangeType.MINOR_STAT_CHANGE)
    assert not diff.of_type(ChangeType.DISTRIBUTION_SHIFT)


def test_rename_detected_from_name_and_content():
    old = pd.DataFrame({"user_name": ["ana", "ana", "bruno", "bruno"], "score": [1, 2, 3, 4]})
    new = pd.DataFrame({"username": ["ana", "ana", "bruno", "bruno"], "score": [1, 2, 3, 4]})

    diff = diff_frames(old, new)

    rename = diff.of_type(ChangeType.COLUMN_RENAMED)[0]

    assert rename.column == "username"
    assert rename.details["previous_name"] == "user_name"
    assert not diff.of_type(ChangeType.COLUMN_ADDED)
    assert not diff.of_type(ChangeType.COLUMN_REMOVED)


def test_unrelated_columns_are_not_treated_as_renames():
    old = pd.DataFrame({"legacy_code": ["LG-1", "LG-2", "LG-1", "LG-2"]})
    new = pd.DataFrame({"country": ["ES", "FR", "ES", "FR"]})

    diff = diff_frames(old, new)

    assert not diff.of_type(ChangeType.COLUMN_RENAMED)
    assert diff.of_type(ChangeType.COLUMN_REMOVED)
    assert diff.of_type(ChangeType.COLUMN_ADDED)


def test_identical_datasets_produce_no_changes(old_csv):
    diff = diff_schemas(load_schema(old_csv), load_schema(old_csv))

    assert diff.changes == []
    assert {column.status for column in diff.columns} == {ColumnStatus.UNCHANGED}


def test_column_statuses(old_csv, new_csv):
    diff = diff_schemas(load_schema(old_csv), load_schema(new_csv))
    statuses = {column.name: column.status for column in diff.columns}

    assert statuses["legacy_code"] is ColumnStatus.REMOVED
    assert statuses["country"] is ColumnStatus.ADDED
    assert statuses["phone"] is ColumnStatus.MODIFIED
    assert statuses["name"] is ColumnStatus.UNCHANGED


def test_rename_threshold_is_configurable():
    old = pd.DataFrame({"legacy_code": ["a", "b", "a", "b"]})
    new = pd.DataFrame({"tag": ["a", "b", "a", "b"]})

    default = diff_frames(old, new)
    permissive = diff_frames(old, new, config=DiffConfig(rename_threshold=0.5))

    assert not default.of_type(ChangeType.COLUMN_RENAMED)
    assert permissive.of_type(ChangeType.COLUMN_RENAMED)[0].column == "tag"
