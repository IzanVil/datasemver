"""Type inference and profiling helpers built on top of pandas."""

from __future__ import annotations

import re

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
    """Refine object columns into booleans, numbers or timestamps when unambiguous."""
    refined = frame.copy()
    for name in refined.columns:
        series = refined[name]
        if canonical_dtype(series) != "string":
            continue
        for converter in (_as_bool, _as_numeric, _as_datetime):
            converted = converter(series)
            if converted is not None:
                refined[name] = converted
                break
    return refined


def _non_null_strings(series: pd.Series) -> pd.Series:
    return series.dropna().astype("string").str.strip()


def _as_bool(series: pd.Series) -> pd.Series | None:
    values = _non_null_strings(series)
    if values.empty:
        return None
    lowered = values.str.lower()
    if not lowered.isin(_BOOL_VALUES).all():
        return None
    truthy = lowered.isin({"true", "yes", "t", "y"})
    result = pd.Series(pd.NA, index=series.index, dtype="boolean")
    result.loc[truthy.index] = truthy
    return result


def _as_numeric(series: pd.Series) -> pd.Series | None:
    values = _non_null_strings(series)
    if values.empty:
        return None
    converted = pd.to_numeric(values, errors="coerce")
    if converted.isna().any():
        return None
    result = pd.Series(pd.NA, index=series.index, dtype=converted.dtype)
    result.loc[converted.index] = converted
    return pd.to_numeric(result, errors="coerce")


def _as_datetime(series: pd.Series) -> pd.Series | None:
    values = _non_null_strings(series)
    if values.empty:
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
    total = int(len(series))
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
