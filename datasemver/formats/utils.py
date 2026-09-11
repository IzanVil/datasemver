"""Type inference and profiling helpers built on top of pandas."""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd
from pandas.api import types as ptypes

from datasemver.core.models import ColumnStats
from datasemver.utils.statistics import OTHER_CATEGORY, QUANTILE_LEVELS

MAX_TRACKED_CATEGORIES = 200
MAX_CATEGORY_UNIQUENESS = 0.5

_DATE_PATTERN = re.compile(
    r"^\s*\d{4}[-/]\d{1,2}[-/]\d{1,2}([ T]\d{1,2}:\d{2}(:\d{2})?)?\s*$"
    r"|^\s*\d{1,2}[-/]\d{1,2}[-/]\d{4}\s*$"
)
_BOOL_VALUES = {"true", "false", "yes", "no", "t", "f", "y", "n"}
_DATE_PARSE_RATIO = 0.9
# Enough values to disprove a whole-column condition in the common case, cheap enough
# that paying it on a column that does convert costs nothing measurable.
_SAMPLE_SIZE = 1000


def canonical_dtype(series: pd.Series) -> str:
    """Map a pandas dtype to one of the canonical labels used by DataSemver."""
    if ptypes.is_bool_dtype(series):
        return "bool"
    if ptypes.is_datetime64_any_dtype(series):
        return "datetime64"
    if ptypes.is_integer_dtype(series):
        return "int64"
    if ptypes.is_float_dtype(series):
        return "float64"
    return "string"


def infer_types(frame: pd.DataFrame) -> pd.DataFrame:
    """Refine object columns into booleans, numbers or timestamps when unambiguous.

    The stripped values are computed once and handed to each candidate. Deriving them inside
    every converter meant a column of plain text paid for the same copy three times over,
    once per type it was never going to be.
    """
    refined = frame.copy()
    for name in refined.columns:
        series = refined[name]
        if canonical_dtype(series) != "string":
            continue
        values = _non_null_strings(series)
        if values.empty:
            continue
        for converter in (_as_bool, _as_numeric, _as_datetime):
            converted = converter(series, values)
            if converted is not None:
                refined[name] = converted
                break
    return refined


def _rejected_early(values: pd.Series, holds: Callable[[pd.Series], pd.Series]) -> bool:
    """Whether a sample already disproves a condition every value would have to meet.

    This only ever rejects. A sample that passes proves nothing, so the full check still
    runs and the answer stays identical to testing every value. What it saves is the column
    that was never going to convert: a million rows of free text no longer have to be parsed
    as numbers before anyone can say they are not numbers.
    """
    if len(values) <= _SAMPLE_SIZE:
        return False
    return not bool(holds(values.head(_SAMPLE_SIZE)).all())


def _non_null_strings(series: pd.Series) -> pd.Series:
    return series.dropna().astype("string").str.strip()


def _as_bool(series: pd.Series, values: pd.Series) -> pd.Series | None:
    if _rejected_early(values, lambda sample: sample.str.lower().isin(_BOOL_VALUES)):
        return None
    lowered = values.str.lower()
    if not lowered.isin(_BOOL_VALUES).all():
        return None
    truthy = lowered.isin({"true", "yes", "t", "y"})
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result.loc[truthy.index] = truthy
    return result


def _as_numeric(series: pd.Series, values: pd.Series) -> pd.Series | None:
    if _rejected_early(values, lambda sample: pd.to_numeric(sample, errors="coerce").notna()):
        return None
    converted = pd.to_numeric(values, errors="coerce")
    if converted.isna().any():
        return None
    result = pd.Series(pd.NA, index=series.index, dtype=converted.dtype)
    result.loc[converted.index] = converted
    return pd.to_numeric(result, errors="coerce")


def _as_datetime(series: pd.Series, values: pd.Series) -> pd.Series | None:
    if _rejected_early(values, lambda sample: sample.str.match(_DATE_PATTERN)):
        return None
    if not values.str.match(_DATE_PATTERN).all():
        return None
    converted = pd.to_datetime(values, errors="coerce", format="mixed")
    if converted.notna().mean() < _DATE_PARSE_RATIO:
        return None
    result = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    result.loc[converted.index] = converted
    return result


def profile_column(series: pd.Series, name: str) -> ColumnStats:
    """Compute the statistics DataSemver compares between dataset versions."""
    total = len(series)
    non_null = series.dropna()
    # A column holding arrays -- a JSON list field, a Parquet or Feather LIST column -- is
    # profiled on the text of its values. Everything below needs a hashable one, and `nunique`
    # raises `TypeError: unhashable type` rather than answer, which reached the command line
    # as a traceback on a file nobody would call malformed. Refusing such a dataset was the
    # other option and a column of tags is not a broken dataset: read as text, it still
    # reports the cardinality and the balance that a comparison is about to compare.
    if _holds_arrays(non_null):
        non_null = non_null.astype(str)
    stats = ColumnStats(
        name=name,
        dtype=canonical_dtype(series),
        row_count=total,
        null_ratio=0.0 if total == 0 else round(1 - len(non_null) / total, 6),
        cardinality=int(non_null.nunique()),
    )
    if non_null.empty:
        return stats

    if stats.dtype == "datetime64":
        _profile_moments(stats, non_null)
    elif stats.dtype in {"int64", "float64"}:
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if not numeric.empty:
            stats.mean = float(numeric.mean())
            stats.std = float(numeric.std(ddof=0))
            stats.minimum = float(numeric.min())
            stats.maximum = float(numeric.max())
            # The column's shape, as eleven numbers. This is what lets a later comparison
            # measure how the distribution moved instead of only where its centre went.
            stats.quantiles = [float(value) for value in numeric.quantile(QUANTILE_LEVELS).tolist()]
    else:
        modes = non_null.mode()
        if not modes.empty:
            stats.mode = str(modes.iloc[0])
        # A column where nearly every value is distinct is an identifier, not a category,
        # and nothing useful comes of tracking it. Cardinality alone is not the test: a
        # column with more distinct values than are tracked individually is still a category
        # and is still worth comparing on balance, with its tail summed into one bucket.
        if stats.cardinality / len(non_null) <= MAX_CATEGORY_UNIQUENESS:
            counts = non_null.astype(str).value_counts()
            if stats.cardinality <= MAX_TRACKED_CATEGORIES:
                # The exact set, which is what makes a category appearing or disappearing
                # reportable. Beyond the limit it would be a sample of the set, and a value
                # missing from a sample is not a value that was removed.
                stats.categories = sorted(counts.index)
            stats.category_counts = _bounded_counts(counts)
    return stats


def _holds_arrays(values: pd.Series) -> bool:
    """Whether the values are of a kind `hash` refuses, which is what profiling needs.

    Read from the first one, as `_holds_mappings` does for structs: a column is one type in
    every format this reads, and paying for a scan to confirm it would cost more than the
    question is worth.
    """
    if values.empty:
        return False
    try:
        hash(values.iloc[0])
    except TypeError:
        return True
    return False


def _profile_moments(stats: ColumnStats, non_null: pd.Series) -> None:
    """Profile a datetime column on its epoch, so it is comparable like any other number.

    Without this a date column carried a type, a null ratio and a cardinality and nothing
    else, which left the most common thing that happens to one -- the whole window sliding
    forward, or shrinking to half the period -- reported as no change at all.

    Seconds rather than nanoseconds: a nanosecond epoch is past the range a float64 holds
    exactly, so the quantiles would be rounded on their way into the profile.

    The cast to microseconds is what makes that seconds rather than whatever the column
    happened to be stored in. A datetime column's resolution varies with the pandas version
    and with where it was read from -- `date_range` gives microseconds on pandas 3 and
    nanoseconds before it -- and `astype("int64")` reports the count in the column's own
    unit, so dividing by a fixed number reads the same instant as a different date.
    """
    moments = pd.to_datetime(non_null, errors="coerce").dropna()
    if moments.empty:  # pragma: no cover - the nulls are already gone and the dtype is a date
        return
    if getattr(moments.dtype, "tz", None) is not None:
        moments = moments.dt.tz_convert("UTC").dt.tz_localize(None)

    epoch = moments.astype("datetime64[us]").astype("int64") / 1_000_000
    stats.mean = float(epoch.mean())
    stats.std = float(epoch.std(ddof=0))
    stats.minimum = float(epoch.min())
    stats.maximum = float(epoch.max())
    stats.quantiles = [float(value) for value in epoch.quantile(QUANTILE_LEVELS).tolist()]


def _bounded_counts(counts: pd.Series) -> dict[str, int]:
    """The most frequent categories, with everything below them summed into one bucket.

    The bucket is what removes a cliff: a column with one more distinct value than the limit
    used to be profiled with no counts at all, so a city column collapsing until one value
    held most of the rows was reported as no change.
    """
    head = counts.iloc[:MAX_TRACKED_CATEGORIES]
    bounded = {str(name): int(count) for name, count in head.items()}
    tail = int(counts.iloc[MAX_TRACKED_CATEGORIES:].sum())
    if tail:
        bounded[OTHER_CATEGORY] = bounded.get(OTHER_CATEGORY, 0) + tail
    return bounded


def profile_frame(frame: pd.DataFrame) -> dict[str, ColumnStats]:
    """Profile every column of a dataframe."""
    return {str(name): profile_column(frame[name], str(name)) for name in frame.columns}
