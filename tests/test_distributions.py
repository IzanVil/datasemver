"""Tests for the changes that only a distribution comparison can see.

Each test here is a dataset pair that a previous version reported as identical. They are
written as data rather than as calls to the statistics directly, because what is being pinned
is not the formula but the answer a user gets: the class balance that collapsed, the spread
that exploded, and the column that split in two, all with the mean holding still throughout.

The last group is the other half of the same problem. A statistic computed on a handful of
rows says something loud about nothing, so these also pin that it stays quiet there.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from datasemver.core.analyzer import analyze_schemas
from datasemver.core.models import ChangeType, Severity
from datasemver.formats.loader import schema_from_frame
from datasemver.formats.utils import MAX_TRACKED_CATEGORIES

ROWS = 20_000


@pytest.fixture(scope="module")
def rng():
    return np.random.default_rng(20260907)


def compare(old: pd.DataFrame, new: pd.DataFrame):
    return analyze_schemas(
        schema_from_frame(old, source="old"),
        schema_from_frame(new, source="new"),
        current_version="1.0.0",
    )


def types_of(report) -> set[ChangeType]:
    return {change.type for change in report.diff.changes}


# --- what the mean could not see --------------------------------------------------------------


def test_a_collapsing_class_balance_is_a_breaking_change(rng):
    """Both categories still present, in a balance no model trained on the old one survives."""
    old = pd.DataFrame({"label": rng.choice(["fraud", "ok"], ROWS, p=[0.5, 0.5])})
    new = pd.DataFrame({"label": rng.choice(["fraud", "ok"], ROWS, p=[0.01, 0.99])})

    report = compare(old, new)

    assert ChangeType.CATEGORY_BALANCE_SHIFT in types_of(report)
    assert report.bump is Severity.MAJOR


def test_the_balance_change_names_the_category_that_moved(rng):
    old = pd.DataFrame({"label": rng.choice(["fraud", "ok"], ROWS, p=[0.5, 0.5])})
    new = pd.DataFrame({"label": rng.choice(["fraud", "ok"], ROWS, p=[0.01, 0.99])})

    report = compare(old, new)
    change = next(c for c in report.diff.changes if c.type is ChangeType.CATEGORY_BALANCE_SHIFT)

    assert change.details["largest_move"] in {"fraud", "ok"}
    assert change.metrics["psi"] > 0.25


def test_a_spread_that_explodes_under_an_unchanged_mean_is_seen(rng):
    """Every threshold and every alert downstream breaks; the mean does not move at all."""
    old = pd.DataFrame({"amount": rng.normal(100, 1, ROWS)})
    new = pd.DataFrame({"amount": rng.normal(100, 40, ROWS)})

    report = compare(old, new)

    assert ChangeType.DISTRIBUTION_SHIFT in types_of(report)


def test_a_column_that_splits_into_two_modes_is_seen(rng):
    """Unimodal to bimodal around the same centre: the mean is identical by construction."""
    old = pd.DataFrame({"score": rng.normal(50, 10, ROWS)})
    new = pd.DataFrame(
        {"score": np.concatenate([rng.normal(30, 3, ROWS // 2), rng.normal(70, 3, ROWS // 2)])}
    )

    report = compare(old, new)

    assert ChangeType.DISTRIBUTION_SHIFT in types_of(report)


def test_a_dataset_compared_with_itself_reports_nothing(rng):
    """The counterpart of the tests above: sensitivity that fires on no change is not useful."""
    frame = pd.DataFrame(
        {
            "amount": rng.normal(100, 15, ROWS),
            "label": rng.choice(["a", "b", "c"], ROWS),
            "flag": ["same"] * ROWS,
        }
    )

    report = compare(frame, frame.copy())

    assert report.diff.changes == []
    assert report.bump is None


def test_a_constant_column_is_not_a_change(rng):
    """A column holding one value has a quantile at every level and a distribution that jumps."""
    old = pd.DataFrame({"version": [3.0] * ROWS})
    new = pd.DataFrame({"version": [3.0] * ROWS})

    assert compare(old, new).diff.changes == []


# --- and what too few rows cannot support -------------------------------------------------------


def test_a_handful_of_rows_does_not_produce_a_breaking_change():
    """Six rows and one outlier: a real version reported this as major before the guard."""
    old = pd.DataFrame({"v": [10, 11, 9, 10, 12, 10]})
    new = pd.DataFrame({"v": [10, 11, 9, 10, 12, 25]})

    report = compare(old, new)

    assert ChangeType.DISTRIBUTION_SHIFT not in types_of(report)
    assert report.bump is not Severity.MAJOR


def test_appending_one_row_to_a_tiny_column_is_not_a_distribution_shift():
    """Four rows to five moves the empirical distribution by a fifth on its own."""
    old = pd.DataFrame({"score": [71.5, 64.0, 88.25, 55.75]})
    new = pd.DataFrame({"score": [71.5, 64.0, 88.25, 55.75, 79.0]})

    assert ChangeType.DISTRIBUTION_SHIFT not in types_of(compare(old, new))


def test_a_balance_measured_on_too_few_rows_is_not_reported():
    """A proportion over six rows cannot move by a little, so every move looks like a big one."""
    old = pd.DataFrame({"plan": ["pro", "pro", "pro", "free", "free", "free"]})
    new = pd.DataFrame({"plan": ["pro", "free", "free", "free", "free", "free"]})

    assert ChangeType.CATEGORY_BALANCE_SHIFT not in types_of(compare(old, new))


def test_the_same_balance_change_is_reported_once_there_are_rows_behind_it():
    """The guard is about evidence, not about the size of the move: same shift, more rows."""
    old = pd.DataFrame({"plan": ["pro"] * 500 + ["free"] * 500})
    new = pd.DataFrame({"plan": ["pro"] * 100 + ["free"] * 900})

    assert ChangeType.CATEGORY_BALANCE_SHIFT in types_of(compare(old, new))


# --- profiles written before any of this existed ------------------------------------------------


def test_a_profile_with_no_quantiles_still_compares_on_the_mean(rng):
    """An older profile has a mean and a standard deviation, and that path has to keep working."""
    old = schema_from_frame(pd.DataFrame({"amount": rng.normal(100, 5, 400)}), source="old")
    new = schema_from_frame(pd.DataFrame({"amount": rng.normal(140, 5, 400)}), source="new")
    for schema in (old, new):
        schema.columns["amount"].quantiles = None

    report = analyze_schemas(old, new, current_version="1.0.0")

    shift = next(c for c in report.diff.changes if c.type is ChangeType.DISTRIBUTION_SHIFT)
    assert "sigma" in shift.description
    assert "sigma_shift" in shift.metrics


def test_an_older_profile_whose_mean_did_not_move_reports_nothing(rng):
    values = rng.normal(100, 5, 400)
    old = schema_from_frame(pd.DataFrame({"amount": values}), source="old")
    new = schema_from_frame(pd.DataFrame({"amount": values}), source="new")
    for schema in (old, new):
        schema.columns["amount"].quantiles = None

    assert analyze_schemas(old, new, current_version="1.0.0").diff.changes == []


def test_an_older_profile_with_a_small_mean_move_is_only_a_stat_change(rng):
    """Well under half a sigma: the legacy path calls that a patch, and still should."""
    old = schema_from_frame(pd.DataFrame({"amount": rng.normal(100, 20, 400)}), source="old")
    new = schema_from_frame(pd.DataFrame({"amount": rng.normal(103, 20, 400)}), source="new")
    for schema in (old, new):
        schema.columns["amount"].quantiles = None

    types = types_of(analyze_schemas(old, new, current_version="1.0.0"))

    assert ChangeType.MINOR_STAT_CHANGE in types
    assert ChangeType.DISTRIBUTION_SHIFT not in types


def test_an_older_profile_with_categories_but_no_counts_still_compares_the_sets(rng):
    """`categories` predates `category_counts`, so an old profile has one and not the other."""
    old = schema_from_frame(pd.DataFrame({"plan": ["pro", "free"] * 300}), source="old")
    new = schema_from_frame(pd.DataFrame({"plan": ["pro", "free", "trial"] * 200}), source="new")
    for schema in (old, new):
        schema.columns["plan"].category_counts = None

    types = types_of(analyze_schemas(old, new, current_version="1.0.0"))

    assert ChangeType.NEW_CATEGORY_ADDED in types
    assert ChangeType.CATEGORY_BALANCE_SHIFT not in types


# --- when a dataset sits in time ----------------------------------------------------------


def moments(start: str, periods: int = 5000, freq: str = "h") -> pd.DataFrame:
    return pd.DataFrame({"seen_at": pd.date_range(start, periods=periods, freq=freq)})


def test_a_window_that_slides_forward_is_a_change():
    """Six years of drift used to be no change: a date column carried no statistics at all."""
    report = compare(moments("2020-01-01"), moments("2026-01-01"))

    assert ChangeType.DISTRIBUTION_SHIFT in types_of(report)
    assert report.bump is Severity.MAJOR


def test_the_change_is_described_in_dates_rather_than_epoch_seconds():
    report = compare(moments("2020-01-01"), moments("2026-01-01"))
    change = next(c for c in report.diff.changes if c.type is ChangeType.DISTRIBUTION_SHIFT)

    assert "2020-01-01" in change.description
    assert "2026-01-01" in change.description


def test_a_window_that_shrinks_to_part_of_the_period_is_a_change():
    """The export that only covers half of what it used to, with the same start."""
    assert ChangeType.DISTRIBUTION_SHIFT in types_of(
        compare(moments("2026-01-01", periods=5000), moments("2026-01-01", periods=2000))
    )


def test_an_unchanged_window_is_not_a_change():
    assert compare(moments("2026-01-01"), moments("2026-01-01")).diff.changes == []


def test_a_date_column_is_never_described_as_a_percentage():
    """A percentage of an epoch is a percentage since 1970, which says nothing about data."""
    report = compare(moments("2020-01-01"), moments("2026-01-01"))
    change = next(c for c in report.diff.changes if c.type is ChangeType.DISTRIBUTION_SHIFT)

    assert "mean_shift_pct" not in change.metrics
    assert "mean_shift_seconds" in change.metrics


def test_a_date_column_is_profiled_with_a_quantile_grid():
    schema = schema_from_frame(moments("2026-01-01"), source="s")

    assert schema.columns["seen_at"].quantiles
    assert schema.columns["seen_at"].minimum is not None


# --- categories past the tracked limit ------------------------------------------------------


def many(distinct: int, rows: int = 20_000) -> pd.DataFrame:
    return pd.DataFrame({"city": [f"c{index % distinct}" for index in range(rows)]})


def test_a_column_past_the_tracked_limit_still_has_counts():
    """One distinct value more than the limit used to mean no counts and no comparison."""
    schema = schema_from_frame(many(5_000), source="s")

    assert schema.columns["city"].category_counts


def test_a_column_past_the_limit_keeps_no_exact_set():
    """A sample of a set is not a set: a value missing from one is not a value removed."""
    schema = schema_from_frame(many(5_000), source="s")

    assert schema.columns["city"].categories is None


def test_the_counts_stay_bounded_however_many_categories_there_are():
    schema = schema_from_frame(many(50_000, rows=100_000), source="s")

    assert len(schema.columns["city"].category_counts or {}) <= MAX_TRACKED_CATEGORIES + 1


def test_a_high_cardinality_column_collapsing_is_a_change():
    """Three hundred cities, and then almost every row is one of them."""
    old = many(300)
    new = pd.DataFrame({"city": ["c0"] * 19_000 + [f"c{i % 300}" for i in range(1_000)]})

    report = compare(old, new)

    assert ChangeType.CATEGORY_BALANCE_SHIFT in types_of(report)
    assert report.bump is Severity.MAJOR


def test_a_high_cardinality_column_that_did_not_move_is_not_a_change():
    """The counterpart: truncating the tail must not invent a shift out of where it was cut."""
    assert compare(many(5_000), many(5_000)).diff.changes == []


def test_an_identifier_is_still_not_treated_as_a_category():
    """Removing the cardinality cliff must not turn a primary key into a category."""
    schema = schema_from_frame(
        pd.DataFrame({"id": [f"u{index}" for index in range(20_000)]}), source="s"
    )

    assert schema.columns["id"].category_counts is None


@pytest.mark.parametrize("unit", ["s", "ms", "us", "ns"])
def test_a_date_reads_the_same_whatever_resolution_it_was_stored_in(unit):
    """`astype("int64")` counts in the column's own unit, and that unit is not a constant.

    It varies with the pandas version and with where the column was read from, so a fixed
    divisor read the same instant as a different date -- 1970 instead of 2020, in the case
    that found this.
    """
    stamps = pd.date_range("2020-01-01", periods=100, freq="h").astype(f"datetime64[{unit}]")

    schema = schema_from_frame(pd.DataFrame({"t": stamps}), source="s")

    assert schema.columns["t"].minimum == 1_577_836_800.0


def test_a_date_with_a_timezone_is_read_as_the_instant_it_names():
    """Midnight in Madrid is the previous evening in UTC, and the epoch is an instant."""
    stamps = pd.date_range("2020-01-01", periods=10, freq="h", tz="Europe/Madrid")

    schema = schema_from_frame(pd.DataFrame({"t": stamps}), source="s")

    assert schema.columns["t"].minimum == 1_577_833_200.0


def test_a_column_that_became_a_date_is_not_compared_as_a_distribution():
    """One side numeric, the other temporal: there is no shared scale to measure a shift on."""
    old = schema_from_frame(pd.DataFrame({"when": [1, 2, 3, 4, 5] * 200}), source="old")
    new = schema_from_frame(moments("2026-01-01", periods=1000), source="new")
    new.columns["when"] = new.columns.pop("seen_at")
    new.columns["when"].name = "when"

    types = types_of(analyze_schemas(old, new, current_version="1.0.0"))

    assert ChangeType.TYPE_CHANGED_INCOMPATIBLE in types
    assert ChangeType.DISTRIBUTION_SHIFT not in types


def test_an_older_profile_with_a_date_but_no_quantiles_reports_no_shift():
    """Date columns carried no statistics before, so an old profile has none to compare."""
    old = schema_from_frame(moments("2020-01-01"), source="old")
    new = schema_from_frame(moments("2026-01-01"), source="new")
    for schema in (old, new):
        schema.columns["seen_at"].quantiles = None

    types = types_of(analyze_schemas(old, new, current_version="1.0.0"))

    assert ChangeType.DISTRIBUTION_SHIFT not in types


def test_a_date_range_that_is_missing_is_rendered_rather_than_crashing():
    old = schema_from_frame(moments("2020-01-01"), source="old")
    new = schema_from_frame(moments("2026-01-01"), source="new")
    old.columns["seen_at"].minimum = None

    report = analyze_schemas(old, new, current_version="1.0.0")
    change = next(c for c in report.diff.changes if c.type is ChangeType.DISTRIBUTION_SHIFT)

    assert "-.." in change.description
