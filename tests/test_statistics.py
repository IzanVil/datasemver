"""Tests for the two-sample statistics the differ compares distributions with.

These are the measures that answer what a mean cannot: whether a column's shape moved, and
whether a categorical column's balance moved. Both are computed from a stored summary rather
than from the data, so what is worth pinning is that they still say the right thing when the
summary is all there is -- including when it is missing, malformed, or built from too few
rows to mean anything.
"""

from __future__ import annotations

import math

import pytest

from datasemver.utils.statistics import (
    OTHER_CATEGORY,
    QUANTILE_LEVELS,
    aligned_counts,
    ks_critical_value,
    ks_statistic,
    population_stability_index,
)


def grid(values: list[float]) -> list[float]:
    """A quantile grid of the right length, for tests that do not care about its shape."""
    assert len(values) == len(QUANTILE_LEVELS)
    return values


UNIFORM = grid([0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100])


# --- the KS statistic -----------------------------------------------------------------------


def test_a_distribution_has_not_moved_from_itself():
    assert ks_statistic(UNIFORM, UNIFORM) == 0.0


def test_two_distributions_that_do_not_overlap_are_maximally_apart():
    shifted = grid([value + 1000 for value in UNIFORM])

    assert ks_statistic(UNIFORM, shifted) == 1.0


def test_a_shift_that_keeps_the_range_lands_between_the_extremes():
    """Every value squeezed into the bottom half: the same support, a different shape."""
    squeezed = grid([0, 0.5, 2.5, 5, 12.5, 25, 37.5, 45, 47.5, 49.5, 100])

    statistic = ks_statistic(UNIFORM, squeezed)

    assert 0.0 < statistic < 1.0


def test_the_statistic_is_symmetric():
    other = grid([0, 2, 8, 14, 30, 55, 78, 92, 96, 99, 100])

    assert ks_statistic(UNIFORM, other) == ks_statistic(other, UNIFORM)


@pytest.mark.parametrize(
    ("old", "new"),
    [
        ([], UNIFORM),
        (UNIFORM, [1.0, 2.0]),
        ([], []),
    ],
)
def test_a_grid_of_the_wrong_length_reports_no_movement(old, new):
    """A profile written before quantiles existed has none, and absence is not evidence."""
    assert ks_statistic(old, new) == 0.0


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_a_grid_holding_a_non_finite_value_reports_no_movement(bad):
    """A column of all-nulls or a single infinity would otherwise produce a nonsense gap."""
    broken = grid([bad, *UNIFORM[1:]])

    assert ks_statistic(broken, UNIFORM) == 0.0
    assert ks_statistic(UNIFORM, broken) == 0.0


def test_a_column_with_one_repeated_value_is_handled():
    """Every quantile identical: a flat grid, where interpolation would divide by zero."""
    flat = grid([7.0] * len(QUANTILE_LEVELS))

    assert ks_statistic(flat, flat) == 0.0
    assert ks_statistic(flat, UNIFORM) > 0.0


# --- the critical value ---------------------------------------------------------------------


def test_a_tiny_sample_needs_an_enormous_gap_to_mean_anything():
    """Four rows against five: appending one row moves the distribution by a fifth by itself."""
    assert ks_critical_value(4, 5) > 0.8


def test_the_bar_drops_as_the_samples_grow():
    assert ks_critical_value(20_000, 20_000) < ks_critical_value(100, 100)
    assert ks_critical_value(100, 100) < ks_critical_value(10, 10)


def test_a_large_sample_puts_the_bar_below_a_gap_worth_caring_about():
    """At twenty thousand rows the effect size, not the significance, is what binds."""
    assert ks_critical_value(20_000, 20_000) < 0.1


@pytest.mark.parametrize(("old", "new"), [(0, 10), (10, 0), (0, 0), (-1, 5)])
def test_an_empty_sample_can_never_clear_the_bar(old, new):
    assert ks_critical_value(old, new) == 1.0


# --- the population stability index -----------------------------------------------------------


def test_an_unchanged_balance_is_stable():
    counts = {"fraud": 500, "ok": 9500}

    assert population_stability_index(counts, counts) == 0.0


def test_a_collapsing_class_balance_is_reported_as_unstable():
    """The case the category set cannot see: both values still present, in a new balance."""
    before = {"fraud": 10_000, "ok": 10_000}
    after = {"fraud": 200, "ok": 19_800}

    assert population_stability_index(before, after) > 0.25


def test_a_balance_that_barely_moves_stays_under_the_stable_line():
    before = {"a": 5000, "b": 5000}
    after = {"a": 5100, "b": 4900}

    assert population_stability_index(before, after) < 0.1


def test_scale_does_not_change_the_result():
    """PSI compares proportions, so ten times the rows in the same balance is the same index."""
    before = {"a": 300, "b": 700}
    small = population_stability_index(before, {"a": 500, "b": 500})
    large = population_stability_index(before, {"a": 5000, "b": 5000})

    assert small == pytest.approx(large, abs=1e-6)


def test_a_category_that_stops_appearing_stays_finite():
    """The term would be infinite; the floor is what keeps the number readable and large."""
    index = population_stability_index({"a": 500, "b": 500}, {"a": 1000})

    assert math.isfinite(index)
    assert index > 0.25


def test_a_category_that_appears_for_the_first_time_is_seen():
    index = population_stability_index({"a": 1000}, {"a": 500, "b": 500})

    assert math.isfinite(index)
    assert index > 0.25


@pytest.mark.parametrize(("old", "new"), [({}, {"a": 1}), ({"a": 1}, {}), ({}, {})])
def test_an_empty_side_reports_no_movement(old, new):
    assert population_stability_index(old, new) == 0.0


# --- aligning counts that were truncated differently --------------------------------------------


def test_untruncated_counts_are_compared_as_they_are():
    """Both sides exact: a category appearing or disappearing is a real event, not an artefact."""
    old, new = aligned_counts({"a": 5, "b": 5}, {"a": 5, "c": 5})

    assert old == {"a": 5, "b": 5}
    assert new == {"a": 5, "c": 5}


def test_a_category_one_side_truncated_does_not_read_as_removed():
    """`b` is tracked on the left and fell into the tail on the right, which is not a removal."""
    old, new = aligned_counts(
        {"a": 500, "b": 100},
        {"a": 500, OTHER_CATEGORY: 100},
    )

    assert set(old) == set(new)
    assert population_stability_index(old, new) < 0.1


def test_aligning_keeps_every_row_on_both_sides():
    """Folding must move rows between bins, never lose them: the shares have to stay shares."""
    before = {"a": 500, "b": 100, "c": 50, OTHER_CATEGORY: 350}
    after = {"a": 400, "c": 200, OTHER_CATEGORY: 400}

    old, new = aligned_counts(before, after)

    assert sum(old.values()) == sum(before.values())
    assert sum(new.values()) == sum(after.values())


def test_a_real_collapse_survives_the_alignment():
    """The folding must not flatten the signal it exists to protect."""
    old, new = aligned_counts(
        {"a": 100, "b": 100, OTHER_CATEGORY: 800},
        {"a": 9_500, "b": 100, OTHER_CATEGORY: 400},
    )

    assert population_stability_index(old, new) > 0.25
