"""Profiling a Parquet file from its footer, without reading a row of it.

Parquet writes a footer holding the schema and, per row group and column, the number of nulls
and the smallest and largest value. That is every input the schema-level changes need -- a
column removed, a type changed, nulls appearing -- and reading it is a seek to the end of the
file rather than a decode of the whole thing.

What the footer cannot give is the shape of the data: no mean, no quantile grid, no counts per
category. So this is what `--schema-only` asks for, never a silent substitution: a comparison
built on it can say whether the contract broke, and cannot say whether the distribution moved.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from datasemver.core.models import ColumnStats, DatasetSchema

# The footer reports a physical type, which is narrower than what pandas infers and is all
# there is to go on without the data. Anything not named here keeps the label Parquet used,
# so an unrecognised type is visible rather than quietly folded into `string`.
_ARROW_DTYPES: dict[str, str] = {
    "bool": "bool",
    "int8": "int64",
    "int16": "int64",
    "int32": "int64",
    "int64": "int64",
    "uint8": "int64",
    "uint16": "int64",
    "uint32": "int64",
    "uint64": "int64",
    "halffloat": "float64",
    "float": "float64",
    "double": "float64",
    "string": "string",
    "large_string": "string",
    "binary": "string",
    "large_binary": "string",
}


class MetadataError(ValueError):
    """Raised when a file's metadata cannot stand in for reading it."""


def schema_from_metadata(path: str | Path, source: str) -> DatasetSchema:
    """Profile a Parquet file from its footer alone."""
    metadata = _read_metadata(path)
    arrow_schema = metadata.schema.to_arrow_schema()
    rows = metadata.num_rows

    columns: dict[str, ColumnStats] = {}
    for index in range(metadata.num_columns):
        field = arrow_schema.field(index)
        nulls, minimum, maximum = _column_statistics(metadata, index, field.name, rows)
        columns[field.name] = ColumnStats(
            name=field.name,
            dtype=_ARROW_DTYPES.get(str(field.type), str(field.type)),
            row_count=rows,
            null_ratio=0.0 if rows == 0 else round(nulls / rows, 6),
            # The footer counts nulls but never distinct values. Setting this to the non-null
            # count makes the uniqueness ratio 1.0 on both sides of any comparison, so the
            # cardinality rules are inert here rather than firing on a number that was never
            # a count of distinct values.
            cardinality=rows - nulls,
            minimum=minimum,
            maximum=maximum,
        )

    return DatasetSchema(source=source, row_count=rows, columns=columns)


def _read_metadata(path: str | Path) -> Any:
    try:
        import pyarrow.parquet as pq
    except ImportError as error:  # pragma: no cover - pyarrow is a hard dependency
        raise MetadataError(
            "reading Parquet metadata requires the 'pyarrow' package: pip install pyarrow"
        ) from error

    try:
        return pq.ParquetFile(str(path)).metadata
    except Exception as error:
        raise MetadataError(f"could not read the Parquet footer of {path}: {error}") from error


def _column_statistics(
    metadata: Any, index: int, name: str, rows: int
) -> tuple[int, float | None, float | None]:
    """Nulls, minimum and maximum for one column, summed across every row group.

    Statistics are per row group and are optional. A group without them contributes no null
    count, and summing what the others reported would be a count over part of the file
    presented as a count over all of it -- a column that is entirely null would come out as
    having none, which is not a missing answer but a wrong one. So the whole read is refused
    and the caller is told to drop the flag, because the file cannot answer without its rows.
    """
    if _is_all_null(metadata, index):
        return rows, None, None

    nulls = 0
    minimum: float | None = None
    maximum: float | None = None

    for group in range(metadata.num_row_groups):
        statistics = metadata.row_group(group).column(index).statistics
        if statistics is None:
            raise MetadataError(
                f"the Parquet footer has no statistics for column {name!r}, so its nulls "
                f"cannot be counted without reading the file. Run without --schema-only."
            )
        nulls += statistics.null_count or 0
        low, high = _as_number(statistics.min), _as_number(statistics.max)
        if low is not None:
            minimum = low if minimum is None else min(minimum, low)
        if high is not None:
            maximum = high if maximum is None else max(maximum, high)

    return nulls, minimum, maximum


def _is_all_null(metadata: Any, index: int) -> bool:
    """A column of Arrow's `null` type holds nothing but nulls, by its type alone.

    Such a column carries no statistics -- there is nothing to summarise -- and reading that
    absence as "no nulls" is exactly backwards.
    """
    return str(metadata.schema.to_arrow_schema().field(index).type) == "null"


def _as_number(value: object) -> float | None:
    """Only the bounds that are numbers: a string column's min and max are not a range."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)
