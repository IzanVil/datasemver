"""Type inference and profiling helpers built on top of pandas."""

from __future__ import annotations

import re
from collections.abc import Callable

import pandas as pd
from pandas.api import types as ptypes

from datasemver.core.models import ColumnStats

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
    stats = ColumnStats(
        name=name,
        dtype=canonical_dtype(series),
        row_count=total,
        null_ratio=0.0 if total == 0 else round(1 - len(non_null) / total, 6),
        cardinality=int(non_null.nunique()),
    )
    if non_null.empty:
        return stats

    if stats.dtype in {"int64", "float64"}:
        numeric = pd.to_numeric(non_null, errors="coerce").dropna()
        if not numeric.empty:
            stats.mean = float(numeric.mean())
            stats.std = float(numeric.std(ddof=0))
            stats.minimum = float(numeric.min())
            stats.maximum = float(numeric.max())
    else:
        modes = non_null.mode()
        if not modes.empty:
            stats.mode = str(modes.iloc[0])
        looks_categorical = (
            stats.cardinality <= MAX_TRACKED_CATEGORIES
            and stats.cardinality / len(non_null) <= MAX_CATEGORY_UNIQUENESS
        )
        if looks_categorical:
            stats.categories = sorted(str(value) for value in non_null.unique())
    return stats


def profile_frame(frame: pd.DataFrame) -> dict[str, ColumnStats]:
    """Profile every column of a dataframe."""
    return {str(name): profile_column(frame[name], str(name)) for name in frame.columns}
