"""Comparison of two dataset profiles."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timezone

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
from datasemver.utils.statistics import (
    aligned_counts,
    ks_critical_value,
    ks_statistic,
    population_stability_index,
)

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
    # A KS statistic is the largest gap between two cumulative distributions, so 0.1 means
    # the two versions disagree about where a tenth of the column sits.
    ks_threshold: float = 0.1
    # The conventional reading of PSI: below 0.1 the population is stable. The rules file
    # draws the second line, at 0.25, between "worth knowing" and "no longer the same data".
    psi_threshold: float = 0.1
    # PSI has no critical value to compare against, so the guard is a plain row count.
    min_rows_for_balance: int = 30


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
    yield from _balance_changes(old, new, config)
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


def _balance_changes(old: ColumnStats, new: ColumnStats, config: DiffConfig) -> Iterator[Change]:
    """Compare how the values are distributed, not only which values occur.

    Gaining and losing categories are set operations, and a column can keep every value it
    ever had while the proportions between them are rebuilt entirely -- a label going from
    balanced to one-in-a-hundred is the case that breaks a model without changing the set.
    """
    if not old.category_counts or not new.category_counts:
        return
    if min(old.non_null_count, new.non_null_count) < config.min_rows_for_balance:
        # Same reason the KS check has a critical value: on a handful of rows a proportion
        # cannot move by a little, so every move looks like a large one.
        return

    before, after = aligned_counts(old.category_counts, new.category_counts)
    index = population_stability_index(before, after)
    if index < config.psi_threshold:
        return

    moved = _largest_move(before, after)
    yield Change(
        type=ChangeType.CATEGORY_BALANCE_SHIFT,
        column=new.name,
        description=(
            f"Column '{new.name}' balance shifted (PSI {index:.3f}): "
            f"'{moved[0]}' {moved[1]:.1%} -> {moved[2]:.1%}"
        ),
        metrics={"psi": index},
        details={"largest_move": moved[0]},
    )


def _largest_move(old: dict[str, int], new: dict[str, int]) -> tuple[str, float, float]:
    """The category whose share moved most, which is the one worth naming in one sentence."""
    old_total = sum(old.values()) or 1
    new_total = sum(new.values()) or 1
    shares = [
        (name, old.get(name, 0) / old_total, new.get(name, 0) / new_total)
        for name in set(old) | set(new)
    ]
    return max(shares, key=lambda item: abs(item[2] - item[1]))


def _numeric_changes(old: ColumnStats, new: ColumnStats, config: DiffConfig) -> Iterator[Change]:
    if old.mean is None or new.mean is None:
        return
    if _is_sequential_key(old) and _is_sequential_key(new):
        return

    if old.is_temporal and new.is_temporal:
        yield from _moment_changes(old, new, config)
        return
    if not (old.is_numeric and new.is_numeric):
        return

    base = abs(old.mean) or 1.0
    relative = round(abs(new.mean - old.mean) / base * 100, 4)
    metrics = {"mean_old": old.mean, "mean_new": new.mean, "mean_shift_pct": relative}

    if old.quantiles and new.quantiles:
        yield from _shape_changes(old, new, config, metrics, relative)
        return
    yield from _mean_only_changes(old, new, config, metrics, relative)


def _moment_changes(old: ColumnStats, new: ColumnStats, config: DiffConfig) -> Iterator[Change]:
    """Compare two datetime columns on when they actually sit.

    Only on the distribution, never on a relative move of the mean: the mean of a datetime is
    a point on an epoch, so "moved 12%" would mean twelve per cent of the time since 1970,
    which is a number about the epoch rather than about the data.
    """
    before, after = old.mean, new.mean
    if not (old.quantiles and new.quantiles) or before is None or after is None:
        return

    statistic = ks_statistic(old.quantiles, new.quantiles)
    floor = max(config.ks_threshold, ks_critical_value(old.non_null_count, new.non_null_count))
    if statistic < floor:
        return

    yield Change(
        type=ChangeType.DISTRIBUTION_SHIFT,
        column=new.name,
        description=(
            f"Column '{new.name}' moved in time (KS {statistic:.3f}): "
            f"{_moment(old.minimum)}..{_moment(old.maximum)} -> "
            f"{_moment(new.minimum)}..{_moment(new.maximum)}"
        ),
        metrics={
            "mean_old": before,
            "mean_new": after,
            "mean_shift_seconds": round(abs(after - before), 3),
            "ks_statistic": statistic,
        },
    )


def _moment(value: float | None) -> str:
    """An epoch second as the date it is, because that is what the reader recognises."""
    if value is None:
        return "-"
    stamp = datetime.fromtimestamp(value, tz=timezone.utc)
    return stamp.strftime("%Y-%m-%d %H:%M:%S").removesuffix(" 00:00:00")


def _shape_changes(
    old: ColumnStats,
    new: ColumnStats,
    config: DiffConfig,
    metrics: dict[str, float],
    relative: float,
) -> Iterator[Change]:
    """Compare the two columns as distributions, which is what the quantiles are stored for.

    The mean is a single point of a distribution, and a column can be rebuilt around a
    different spread or split into two modes without moving it at all. KS reads the whole
    shape, so those changes are the ones this sees and the mean could not.
    """
    statistic = ks_statistic(old.quantiles or [], new.quantiles or [])
    metrics = metrics | {"ks_statistic": statistic}

    # Two floors, and a shift has to clear both: large enough to care about, and larger than
    # two identical distributions would produce at these sample sizes.
    floor = max(config.ks_threshold, ks_critical_value(old.non_null_count, new.non_null_count))
    if statistic >= floor:
        yield Change(
            type=ChangeType.DISTRIBUTION_SHIFT,
            column=new.name,
            description=(
                f"Column '{new.name}' distribution moved (KS {statistic:.3f}): "
                f"mean {old.mean:.4g} -> {new.mean:.4g}, "
                f"std {_spread(old.std)} -> {_spread(new.std)}"
            ),
            metrics=metrics,
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


def _mean_only_changes(
    old: ColumnStats,
    new: ColumnStats,
    config: DiffConfig,
    metrics: dict[str, float],
    relative: float,
) -> Iterator[Change]:
    """The comparison available when a profile predates the quantile grid.

    A profile written by an older version has a mean and a standard deviation and nothing
    else, so this is what it can be compared with. New profiles never reach here.
    """
    if old.mean is None or new.mean is None:  # pragma: no cover - the caller has checked
        return
    shift = abs(new.mean - old.mean)
    if shift == 0:
        return

    spread = old.std or 0.0
    sigma = round(shift / spread, 4) if spread else float("inf")

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


def _spread(value: float | None) -> str:
    return "-" if value is None else f"{value:.4g}"


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
