"""Comparison of two dataset profiles."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from datasemver.core.models import (
    Change,
    ChangeType,
    ColumnComparison,
    ColumnStats,
    ColumnStatus,
    DatasetSchema,
    DiffResult,
)
from datasemver.utils.similarity import column_similarity

COMPATIBLE_WIDENINGS: set[tuple[str, str]] = {
    ("bool", "int64"),
    ("bool", "float64"),
    ("int64", "float64"),
}


@dataclass(frozen=True)
class DiffConfig:
    """Sensitivity thresholds used while comparing two datasets."""

    rename_threshold: float = 0.7
    null_ratio_tolerance: float = 0.01
    distribution_sigma: float = 0.5
    stat_change_tolerance: float = 0.01
    cardinality_tolerance: float = 0.1


def diff_schemas(
    old: DatasetSchema,
    new: DatasetSchema,
    config: DiffConfig | None = None,
) -> DiffResult:
    """Compare two dataset profiles and return every detected change."""
    config = config or DiffConfig()

    removed = [name for name in old.column_names if name not in new.columns]
    added = [name for name in new.column_names if name not in old.columns]
    renames = _detect_renames(old, new, removed, added, config)

    removed = [name for name in removed if name not in renames]
    added = [name for name in added if name not in renames.values()]

    changes: list[Change] = list(_row_count_changes(old, new))
    comparisons: list[ColumnComparison] = []

    for name in removed:
        stats = old.columns[name]
        changes.append(
            Change(
                type=ChangeType.COLUMN_REMOVED,
                column=name,
                description=f"Column '{name}' was removed",
                details={"dtype": stats.dtype},
            )
        )
        comparisons.append(
            ColumnComparison(
                name=name,
                status=ColumnStatus.REMOVED,
                dtype_old=stats.dtype,
                null_ratio_old=stats.null_ratio,
                cardinality_old=stats.cardinality,
            )
        )

    for name in added:
        stats = new.columns[name]
        changes.append(
            Change(
                type=ChangeType.COLUMN_ADDED,
                column=name,
                description=f"Column '{name}' was added",
                metrics={"null_ratio": stats.null_ratio},
                details={"dtype": stats.dtype},
            )
        )
        comparisons.append(
            ColumnComparison(
                name=name,
                status=ColumnStatus.ADDED,
                dtype_new=stats.dtype,
                null_ratio_new=stats.null_ratio,
                cardinality_new=stats.cardinality,
            )
        )

    for old_name, new_name in renames.items():
        changes.append(
            Change(
                type=ChangeType.COLUMN_RENAMED,
                column=new_name,
                description=f"Column '{old_name}' was renamed to '{new_name}'",
                details={"previous_name": old_name},
            )
        )

    paired = [(name, name) for name in old.column_names if name in new.columns]
    paired.extend(renames.items())

    for old_name, new_name in paired:
        old_stats = old.columns[old_name]
        new_stats = new.columns[new_name]
        column_changes = list(_column_changes(old_stats, new_stats, config))
        changes.extend(column_changes)

        if old_name != new_name:
            status = ColumnStatus.RENAMED
        elif column_changes:
            status = ColumnStatus.MODIFIED
        else:
            status = ColumnStatus.UNCHANGED

        comparisons.append(
            ColumnComparison(
                name=new_name,
                status=status,
                renamed_from=old_name if old_name != new_name else None,
                dtype_old=old_stats.dtype,
                dtype_new=new_stats.dtype,
                null_ratio_old=old_stats.null_ratio,
                null_ratio_new=new_stats.null_ratio,
                cardinality_old=old_stats.cardinality,
                cardinality_new=new_stats.cardinality,
            )
        )

    comparisons.sort(key=lambda item: (item.status.value, item.name))
    return DiffResult(old=old, new=new, changes=changes, columns=comparisons)


def _detect_renames(
    old: DatasetSchema,
    new: DatasetSchema,
    removed: list[str],
    added: list[str],
    config: DiffConfig,
) -> dict[str, str]:
    """Pair removed and added columns that look like the same column renamed."""
    candidates: list[tuple[float, str, str]] = []
    for old_name in removed:
        for new_name in added:
            score = column_similarity(
                old_name,
                new_name,
                old.columns[old_name].categories,
                new.columns[new_name].categories,
            )
            if score >= config.rename_threshold:
                candidates.append((score, old_name, new_name))

    candidates.sort(reverse=True)
    renames: dict[str, str] = {}
    taken: set[str] = set()
    for _, old_name, new_name in candidates:
        if old_name in renames or new_name in taken:
            continue
        renames[old_name] = new_name
        taken.add(new_name)
    return renames


def _row_count_changes(old: DatasetSchema, new: DatasetSchema) -> Iterator[Change]:
    if old.row_count == new.row_count:
        return

    delta = new.row_count - old.row_count
    base = old.row_count or 1
    percentage = round(abs(delta) / base * 100, 4)
    metrics = {
        "old_rows": float(old.row_count),
        "new_rows": float(new.row_count),
        "delta": float(delta),
        "change_pct": percentage,
    }

    if delta > 0:
        yield Change(
            type=ChangeType.ROW_COUNT_INCREASED,
            description=(
                f"Row count grew from {old.row_count} to {new.row_count} (+{percentage:.2f}%)"
            ),
            metrics=metrics | {"increase_pct": percentage},
        )
    else:
        yield Change(
            type=ChangeType.ROW_COUNT_DECREASED,
            description=(
                f"Row count fell from {old.row_count} to {new.row_count} (-{percentage:.2f}%)"
            ),
            metrics=metrics | {"decrease_pct": percentage},
        )


def _column_changes(old: ColumnStats, new: ColumnStats, config: DiffConfig) -> Iterator[Change]:
    yield from _type_changes(old, new)
    yield from _null_changes(old, new, config)
    yield from _category_changes(old, new)
    yield from _numeric_changes(old, new, config)
    yield from _cardinality_changes(old, new, config)


def _type_changes(old: ColumnStats, new: ColumnStats) -> Iterator[Change]:
    if old.dtype == new.dtype:
        return

    details = {"dtype_old": old.dtype, "dtype_new": new.dtype}
    if (old.dtype, new.dtype) in COMPATIBLE_WIDENINGS:
        yield Change(
            type=ChangeType.TYPE_CHANGED_COMPATIBLE,
            column=new.name,
            description=f"Column '{new.name}' widened from {old.dtype} to {new.dtype}",
            details=details,
        )
    else:
        yield Change(
            type=ChangeType.TYPE_CHANGED_INCOMPATIBLE,
            column=new.name,
            description=f"Column '{new.name}' changed type from {old.dtype} to {new.dtype}",
            details=details,
        )


def _null_changes(old: ColumnStats, new: ColumnStats, config: DiffConfig) -> Iterator[Change]:
    delta = new.null_ratio - old.null_ratio
    if abs(delta) < config.null_ratio_tolerance:
        return

    metrics = {
        "null_ratio_old": round(old.null_ratio * 100, 4),
        "null_ratio_new": round(new.null_ratio * 100, 4),
        "delta_pct": round(abs(delta) * 100, 4),
    }
    if delta < 0:
        yield Change(
            type=ChangeType.NULLS_FIXED,
            column=new.name,
            description=(
                f"Column '{new.name}' nulls dropped from {old.null_ratio:.1%} "
                f"to {new.null_ratio:.1%}"
            ),
            metrics=metrics,
        )
    else:
        yield Change(
            type=ChangeType.NULLS_INTRODUCED,
            column=new.name,
            description=(
                f"Column '{new.name}' nulls rose from {old.null_ratio:.1%} to {new.null_ratio:.1%}"
            ),
            metrics=metrics,
        )


def _category_changes(old: ColumnStats, new: ColumnStats) -> Iterator[Change]:
    if old.categories is None or new.categories is None:
        return

    old_set, new_set = set(old.categories), set(new.categories)
    gained = sorted(new_set - old_set)
    lost = sorted(old_set - new_set)

    if gained:
        yield Change(
            type=ChangeType.NEW_CATEGORY_ADDED,
            column=new.name,
            description=f"Column '{new.name}' gained {len(gained)} category value(s)",
            metrics={"added_count": float(len(gained))},
            details={"categories": gained[:20]},
        )
    if lost:
        yield Change(
            type=ChangeType.CATEGORY_REMOVED,
            column=new.name,
            description=f"Column '{new.name}' lost {len(lost)} category value(s)",
            metrics={"removed_count": float(len(lost))},
            details={"categories": lost[:20]},
        )


def _numeric_changes(old: ColumnStats, new: ColumnStats, config: DiffConfig) -> Iterator[Change]:
    if not (old.is_numeric and new.is_numeric):
        return
    if old.mean is None or new.mean is None:
        return
    if _is_sequential_key(old) and _is_sequential_key(new):
        return

    shift = abs(new.mean - old.mean)
    if shift == 0:
        return

    base = abs(old.mean) or 1.0
    relative = round(shift / base * 100, 4)
    spread = old.std or 0.0
    sigma = round(shift / spread, 4) if spread else float("inf")
    metrics = {"mean_old": old.mean, "mean_new": new.mean, "mean_shift_pct": relative}

    if spread and sigma >= config.distribution_sigma:
        yield Change(
            type=ChangeType.DISTRIBUTION_SHIFT,
            column=new.name,
            description=(
                f"Column '{new.name}' mean moved from {old.mean:.4g} to {new.mean:.4g} "
                f"({sigma:.2f} sigma)"
            ),
            metrics=metrics | {"sigma_shift": sigma},
        )
    elif relative >= config.stat_change_tolerance * 100:
        yield Change(
            type=ChangeType.MINOR_STAT_CHANGE,
            column=new.name,
            description=(
                f"Column '{new.name}' mean moved from {old.mean:.4g} to {new.mean:.4g} "
                f"({relative:.2f}%)"
            ),
            metrics=metrics,
        )


def _is_sequential_key(stats: ColumnStats) -> bool:
    """Detect contiguous integer keys, whose statistics carry no business meaning."""
    if stats.dtype != "int64" or stats.minimum is None or stats.maximum is None:
        return False
    if stats.uniqueness < 1.0 or stats.null_ratio > 0:
        return False
    return stats.cardinality == int(stats.maximum - stats.minimum) + 1


def _cardinality_changes(
    old: ColumnStats, new: ColumnStats, config: DiffConfig
) -> Iterator[Change]:
    if old.categories is not None and new.categories is not None:
        return
    if abs(new.uniqueness - old.uniqueness) < config.cardinality_tolerance:
        return

    base = old.cardinality or 1
    change = round(abs(new.cardinality - old.cardinality) / base * 100, 4)

    yield Change(
        type=ChangeType.CARDINALITY_CHANGED,
        column=new.name,
        description=(
            f"Column '{new.name}' cardinality moved from {old.cardinality} to {new.cardinality}"
        ),
        metrics={
            "cardinality_old": float(old.cardinality),
            "cardinality_new": float(new.cardinality),
            "change_pct": change,
        },
    )
