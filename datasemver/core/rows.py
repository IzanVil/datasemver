"""Comparing two datasets row by row, matched on a key.

Everything else in this library compares profiles: shapes, types, distributions. That answers
"is this still the same kind of data?" and deliberately not "which rows changed?", because a
profile cannot know -- a version where a third of the rows were rewritten with values drawn
the same way has the same profile as the one before it, and is a different dataset to anyone
joining against it.

This needs both datasets in memory at once and a key that identifies a row, which is why it
sits behind `--key` rather than running always.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datasemver.core.models import Change, ChangeType

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

# Naming a handful of them is what makes the count actionable; the rest would be a data dump.
MAX_REPORTED_COLUMNS = 10

# Stands in for a missing value while comparing, so that two of them read as equal to
# each other. It holds a NUL byte, which no dataset this library reads can produce.
_ABSENT = "\x00<absent>"


class KeyError_(ValueError):
    """Raised when a key cannot identify the rows of a dataset."""


def compare_rows(
    old: pd.DataFrame,
    new: pd.DataFrame,
    key: list[str],
    old_source: str,
    new_source: str,
) -> list[Change]:
    """Match the two datasets on `key` and report what happened to the rows."""
    _check_key(old, key, old_source)
    _check_key(new, key, new_source)

    old_keyed = old.set_index(key)
    new_keyed = new.set_index(key)

    old_index, new_index = old_keyed.index, new_keyed.index
    kept = old_index.intersection(new_index)
    added = len(new_index.difference(old_index))
    removed = len(old_index.difference(new_index))

    modified, per_column = _modified(old_keyed, new_keyed, kept)

    changes: list[Change] = []
    if added or removed:
        changes.append(_membership_change(added, removed, len(new_index)))
    if modified:
        changes.append(_modified_change(modified, len(kept), per_column))
    return changes


def _check_key(frame: pd.DataFrame, key: list[str], source: str) -> None:
    """A key that is missing or repeated cannot match rows, and guessing would be worse.

    A duplicated key would make the comparison silently arbitrary -- which of the rows sharing
    a key is the one that changed? -- so it is refused with the count, which is usually enough
    to recognise what went wrong.
    """
    missing = [column for column in key if column not in frame.columns]
    if missing:
        raise KeyError_(f"{source} has no column {missing[0]!r} to key on")

    duplicated = int(frame.duplicated(subset=key).sum())
    if duplicated:
        joined = ", ".join(key)
        raise KeyError_(
            f"{source} does not have one row per {joined}: "
            f"{duplicated} row(s) repeat a key already used"
        )


def _modified(old: pd.DataFrame, new: pd.DataFrame, kept: pd.Index) -> tuple[int, dict[str, int]]:
    """Count the rows present in both whose values differ, and where they differ.

    Only the columns both versions share are compared: a column that was added or removed is
    a schema change, already reported as one, and counting every row as modified because of it
    would drown the rows that actually changed.
    """

    import pandas as pd

    shared = [column for column in old.columns if column in new.columns]
    if kept.empty or not shared:
        return 0, {}

    before = old.loc[kept, shared]
    after = new.loc[kept, shared]
    differs = pd.DataFrame(
        {column: _column_differs(before[column], after[column]) for column in shared},
        index=kept,
    )
    per_column = {str(column): int(count) for column, count in differs.sum().items() if int(count)}
    return int(differs.any(axis=1).sum()), per_column


def _column_differs(before: pd.Series, after: pd.Series) -> Any:
    """Whether each row's value changed, for one column.

    Two rules, both of which exist because the obvious comparison gets them backwards. A row
    missing a value on both sides has not changed, but `==` says a null equals nothing at all,
    itself included, so every such row would be reported as modified. And a column whose type
    widened from `int64` to `float64` holds the same numbers written differently, so comparing
    the text would call every row modified on top of the type change already reported; numbers
    are compared as numbers.
    """
    from pandas.api import types as ptypes

    if ptypes.is_numeric_dtype(before) and ptypes.is_numeric_dtype(after):
        absent = (before.isna() & after.isna()).to_numpy()
        left = before.to_numpy(dtype="float64", na_value=float("nan"))
        right = after.to_numpy(dtype="float64", na_value=float("nan"))
        return ~(absent | (left == right))

    # The missing values are replaced before the comparison rather than after it. A pandas
    # NA does not survive `==` as a boolean -- the result is NA, and asking whether that is
    # true raises -- so letting one reach the comparison at all is what breaks.
    left = before.astype("string").to_numpy(dtype=object, na_value=_ABSENT)
    right = after.astype("string").to_numpy(dtype=object, na_value=_ABSENT)
    return left != right


def _membership_change(added: int, removed: int, total: int) -> Change:
    share = added + removed if total == 0 else (added + removed) / total * 100
    return Change(
        type=ChangeType.ROWS_REPLACED,
        description=f"{added} row(s) added and {removed} removed, matched on the key",
        metrics={
            "rows_added": float(added),
            "rows_removed": float(removed),
            "replaced_pct": round(float(share), 4),
        },
    )


def _modified_change(modified: int, kept: int, per_column: dict[str, int]) -> Change:
    share = 0.0 if kept == 0 else modified / kept * 100
    ranked = sorted(per_column.items(), key=lambda item: -item[1])
    named = ", ".join(f"{column} ({count})" for column, count in ranked[:MAX_REPORTED_COLUMNS])
    return Change(
        type=ChangeType.ROWS_MODIFIED,
        description=(
            f"{modified} of {kept} row(s) present in both changed value ({share:.1f}%): {named}"
        ),
        metrics={"rows_modified": float(modified), "modified_pct": round(share, 4)},
        details={"columns": dict(ranked[:MAX_REPORTED_COLUMNS])},
    )
