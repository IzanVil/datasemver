"""Two-sample statistics computed from a stored profile rather than from the data.

Both measures here answer the same question the rest of the library asks about schemas: did
this change enough to matter? The point is that they answer it from a few hundred bytes of
summary, so a comparison never needs both datasets in memory at once.

`ks_statistic` works on a quantile grid, which is what makes it possible: a column's shape
travels as eleven numbers. `population_stability_index` works on category counts. Between
them they cover the two cases the mean alone could not see -- a spread that changes while the
mean holds, and a class balance that collapses while the category set stays the same.
"""

from __future__ import annotations

import math

# Denser in the tails than a plain decile grid, because that is where a distribution usually
# changes first and where the mean is least likely to notice.
QUANTILE_LEVELS: tuple[float, ...] = (
    0.0,
    0.01,
    0.05,
    0.10,
    0.25,
    0.50,
    0.75,
    0.90,
    0.95,
    0.99,
    1.0,
)

# A category present in one version and absent from the other gives an infinite term. The
# floor is what every implementation of PSI uses instead; it keeps the result finite and
# large, which is the honest reading of "this value stopped appearing".
_PSI_FLOOR = 1e-4

# Where the categories a profile does not track individually are summed. A column with more
# distinct values than the profile keeps is still worth comparing on balance -- binning the
# tail is how PSI is computed on a high-cardinality feature anyway -- and without a bucket
# for it such a column was compared on nothing at all. A real category by this name merges
# into the bucket, which costs a little accuracy in one bin and nothing else.
OTHER_CATEGORY = "__other__"

# Coefficient of the Kolmogorov distribution at the 5% level. The two-sample critical value
# is this over the square root of the harmonic-ish sample size; see `ks_critical_value`.
_KS_ALPHA_05 = 1.358


def ks_statistic(old: list[float], new: list[float]) -> float:
    """Approximate the two-sample Kolmogorov-Smirnov statistic from two quantile grids.

    KS is the largest vertical gap between two cumulative distributions, a single number in
    [0, 1] that answers "how differently are these two columns distributed?" without assuming
    either is normal. It is approximate here because the grids hold `QUANTILE_LEVELS` points
    rather than every observation: the true maximum can fall between two grid points, so this
    is a lower bound on the real statistic and understates rather than invents a shift.

    Each grid is read as a quantile function, and the gap is measured from both directions --
    the old level against the new distribution and the reverse -- because either side can be
    the one holding the largest gap.
    """
    if len(old) != len(QUANTILE_LEVELS) or len(new) != len(QUANTILE_LEVELS):
        return 0.0
    if not _is_finite(old) or not _is_finite(new):
        return 0.0

    # Both distributions are read at the same point, rather than one level being compared
    # against the other's distribution. The shortcut is wrong wherever a distribution has a
    # step in it: a column holding one value repeated has a quantile at every level and a
    # cumulative distribution that jumps straight to 1, so comparing levels reported it as
    # maximally different from itself.
    points = list(old) + list(new)
    return round(max(abs(_cdf_at(point, old) - _cdf_at(point, new)) for point in points), 6)


def ks_critical_value(old_rows: int, new_rows: int) -> float:
    """The smallest KS statistic that means anything at all for these two sample sizes.

    A KS statistic has no fixed reading: on four rows against five, appending a single row
    moves the empirical distribution by a fifth on its own, so a gap of 0.125 is what two
    identical distributions look like. On twenty thousand rows the same 0.125 could not
    happen by chance. This is the standard critical value at the 5% level,
    `c * sqrt((n + m) / (n * m))`, and comparing against it is what keeps a small sample from
    reporting noise as a breaking change.

    It is a floor, not the whole test: a shift also has to be large enough to care about,
    which is what the configured threshold is for. Both have to be cleared.
    """
    if old_rows <= 0 or new_rows <= 0:
        return 1.0
    return _KS_ALPHA_05 * math.sqrt((old_rows + new_rows) / (old_rows * new_rows))


def _cdf_at(value: float, grid: list[float]) -> float:
    """The share of `grid`'s distribution at or below `value`, by linear interpolation.

    `grid` holds the values at `QUANTILE_LEVELS`, so it is a quantile function sampled at
    known levels; reading it backwards gives the cumulative distribution.
    """
    if value < grid[0]:
        return 0.0
    if value >= grid[-1]:
        return 1.0

    # The highest level whose value is still at or below this one. Where several levels share
    # a value -- a repeated value, which is a step in the distribution -- this lands on the
    # top of that step, which is what "the share at or below" means there.
    below = 0
    for index, point in enumerate(grid):
        if point > value:
            break
        below = index

    level = QUANTILE_LEVELS[below]
    lower, upper = grid[below], grid[below + 1]
    if upper > lower:
        share = (value - lower) / (upper - lower)
        level += share * (QUANTILE_LEVELS[below + 1] - QUANTILE_LEVELS[below])
    return level


def aligned_counts(
    old: dict[str, int], new: dict[str, int]
) -> tuple[dict[str, int], dict[str, int]]:
    """Put two category-count maps where their shares mean the same thing.

    A profile keeps the most frequent categories and sums the rest into `OTHER_CATEGORY`, so
    two versions of a column can track different sets: a category sitting near the cut can be
    tracked in one and folded into the tail of the other. Reading that as the category having
    disappeared would report a shift that is really an artefact of where the cut fell.

    So where either side is truncated, only the categories both of them tracked are compared,
    and everything else on each side joins that side's own tail. Where neither is truncated
    the counts are exact and are compared as they are, which keeps a category genuinely
    appearing or disappearing visible.
    """
    if OTHER_CATEGORY not in old and OTHER_CATEGORY not in new:
        return dict(old), dict(new)

    shared = (set(old) & set(new)) - {OTHER_CATEGORY}
    return _folded(old, shared), _folded(new, shared)


def _folded(counts: dict[str, int], shared: set[str]) -> dict[str, int]:
    kept = {name: counts[name] for name in shared}
    tail = sum(counts.values()) - sum(kept.values())
    if tail:
        kept[OTHER_CATEGORY] = tail
    return kept


def population_stability_index(old: dict[str, int], new: dict[str, int]) -> float:
    """How far a categorical column's balance moved, over the union of both category sets.

    The industry reading of the result is fixed enough to put in a rules file: below 0.1 the
    population is stable, 0.1 to 0.25 is a shift worth knowing about, and above 0.25 it has
    moved enough that anything fitted on the old version no longer describes the new one.

    Unlike comparing the category *sets*, this sees a column whose values are all still
    present in the proportions they arrive in, which is the case that matters for a label.
    """
    old_total, new_total = sum(old.values()), sum(new.values())
    if old_total <= 0 or new_total <= 0:
        return 0.0

    index = 0.0
    for category in set(old) | set(new):
        old_share = max(old.get(category, 0) / old_total, _PSI_FLOOR)
        new_share = max(new.get(category, 0) / new_total, _PSI_FLOOR)
        index += (new_share - old_share) * math.log(new_share / old_share)
    return round(index, 6)


def _is_finite(values: list[float]) -> bool:
    return all(math.isfinite(value) for value in values)
