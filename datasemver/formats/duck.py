"""Profiling a dataset with DuckDB instead of loading it into a dataframe.

Every statistic a profile holds is an aggregate, and an aggregate does not need the dataset in
memory -- only the engine computing it does. Reading a CSV into pandas costs about ten times
the file on disk, which is the ceiling that decides whether this tool works on the datasets
worth versioning: a 1.2 GB CSV cannot be profiled in 6 GB of RAM and is profiled here in
around one.

Two engines live here, and the difference between them is one statistic. Both compute a profile
the dataframe path would recognise; `sketch` takes the quantile grid from a t-digest instead of
computing it, which on 16M rows is the difference between 16 seconds and 5, and between 1.7 GB
and 1.0 GB. Everything else stays exact in both -- row counts, null ratios, cardinality, the
category sets and their counts, the mean and the standard deviation.

The grid is the only thing worth sketching, and the reason is measured. `approx_count_distinct`
answers 616 for 500 distinct values, and the differ reports a cardinality change when a column's
uniqueness moves by a tenth, so that sketch invents changes nobody made. The quantile sketch
costs 0.23% of a column's range at worst, and nothing at the two ends, which come from `min` and
`max` -- exact aggregates already being computed, and precisely where a sketch is at its worst.

What it does cost is exactness where someone can see it. A sketch stops interpolating between
values, so on eight rows it answers 1 where the other path answers 1.35: the grids diverge most
visibly on the datasets small enough to check by hand, which is why it is asked for by name and
never chosen for anyone.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from datasemver.core.models import ColumnStats, DatasetSchema
from datasemver.formats.utils import MAX_CATEGORY_UNIQUENESS, MAX_TRACKED_CATEGORIES
from datasemver.utils.extras import install_hint as _install_hint
from datasemver.utils.statistics import OTHER_CATEGORY, QUANTILE_LEVELS

if TYPE_CHECKING:  # pragma: no cover
    import duckdb

ENGINE_NAME = "duckdb"

# What this engine reads. Narrower than the library on purpose: these are the formats DuckDB
# reads natively and identically, and a source it cannot take is refused by name rather than
# quietly handed to the other engine, which would profile it differently without saying so.
DUCKDB_EXTENSIONS = {".parquet", ".pq", ".csv", ".csv.gz", ".tsv", ".tsv.gz"}

MEMORY_LIMIT_ENV_VAR = "DATASEMVER_DUCKDB_MEMORY_LIMIT"


def install_hint() -> str:
    """Read at call time: the advice differs inside the standalone executable."""
    return _install_hint("duckdb", "the duckdb engine")


# DuckDB reports a physical type; these are the labels the rest of the library compares on,
# and they match what `canonical_dtype` produces for the same data read into pandas.
_DTYPES = {
    "BOOLEAN": "bool",
    "TINYINT": "int64",
    "SMALLINT": "int64",
    "INTEGER": "int64",
    "BIGINT": "int64",
    "HUGEINT": "int64",
    "UTINYINT": "int64",
    "USMALLINT": "int64",
    "UINTEGER": "int64",
    "UBIGINT": "int64",
    "FLOAT": "float64",
    "DOUBLE": "float64",
    "DECIMAL": "float64",
    "DATE": "datetime64",
    "TIMESTAMP": "datetime64",
    "TIMESTAMP_NS": "datetime64",
    "TIMESTAMP_MS": "datetime64",
    "TIMESTAMP_S": "datetime64",
    "TIMESTAMP WITH TIME ZONE": "datetime64",
}

# A column holding a struct, a list or a map is one column here and several after the other
# engine flattens it, so the two would profile the same file differently. Refused by name
# until this engine flattens them too.
_NESTED = ("STRUCT", "LIST", "MAP", "UNION", "ARRAY")

_NUMERIC = {"int64", "float64", "datetime64"}
_LEVELS = list(QUANTILE_LEVELS)


class DuckDBError(ValueError):
    """Raised when the DuckDB engine cannot profile a source."""


def is_duckdb_readable(source: str | Path) -> bool:
    """Whether this engine can read a source, by the suffix the library dispatches on."""
    name = str(source).lower()
    return any(name.endswith(extension) for extension in DUCKDB_EXTENSIONS)


def profile_source(
    path: str | Path, source: str, delimiter: str | None = None, sketch: bool = False
) -> DatasetSchema:
    """Profile a file with DuckDB, returning the schema the rest of the library compares.

    `delimiter` comes from the caller rather than from DuckDB's own sniffer, so a `.tsv` and
    a `DATASEMVER_CSV_DELIMITER` override mean here exactly what they mean everywhere else.

    `sketch` trades the quantile grid for an estimate of it, which is what makes profiling
    cost a fraction of the dataset rather than a multiple of one column.
    """
    connection = _connect()
    try:
        relation = _relation(Path(path), delimiter)
        columns = _columns(connection, relation)
        row_count = int(_one(connection, f"SELECT count(*) FROM {relation}")[0])
        aggregates = _aggregate(connection, relation, columns, sketch)
        stats = {
            name: _column_stats(connection, relation, name, dtype, index, row_count, aggregates)
            for index, (name, dtype) in enumerate(columns)
        }
    finally:
        connection.close()
    return DatasetSchema(source=source, row_count=row_count, columns=stats)


def _connect() -> duckdb.DuckDBPyConnection:
    """An in-process connection, under the memory ceiling the environment asks for."""
    try:
        import duckdb
    except ImportError as error:
        raise DuckDBError(install_hint()) from error

    connection = duckdb.connect()
    # DuckDB draws a progress bar on a long query, which is a fine thing for a shell and a
    # bad thing for a library: it lands in the middle of `--json` output and in whatever a
    # pipeline captures. Off before anything is read.
    connection.execute("SET enable_progress_bar=false")
    # Where DuckDB spills what does not fit. An in-memory database has nowhere to put it by
    # default, so a dataset past the ceiling fails instead of going to disk -- which is the
    # one thing this engine exists not to do.
    connection.execute(f"SET temp_directory='{tempfile.gettempdir()}'")

    limit = os.environ.get(MEMORY_LIMIT_ENV_VAR)
    if limit:
        try:
            connection.execute(f"SET memory_limit='{limit}'")
        except Exception as error:
            connection.close()
            raise DuckDBError(
                f"{MEMORY_LIMIT_ENV_VAR} is not a size DuckDB accepts: {limit!r}"
            ) from error
    return connection


def _relation(path: Path, delimiter: str | None) -> str:
    """The SQL naming the file, with the path escaped rather than interpolated raw."""
    literal = "'" + str(path).replace("'", "''") + "'"
    if path.name.lower().endswith((".parquet", ".pq")):
        return f"read_parquet({literal})"
    if delimiter is None:
        return f"read_csv_auto({literal})"
    return f"read_csv({literal}, delim='{_escaped(delimiter)}', header=true, auto_detect=true)"


def _escaped(delimiter: str) -> str:
    return "\\t" if delimiter == "\t" else delimiter.replace("'", "''")


def _columns(connection: duckdb.DuckDBPyConnection, relation: str) -> list[tuple[str, str]]:
    """The columns and their canonical types, refusing the ones this engine cannot match."""
    described = _all(connection, f"DESCRIBE SELECT * FROM {relation}")
    columns = []
    for name, declared, *_ in described:
        upper = str(declared).upper()
        if upper.startswith(_NESTED):
            raise DuckDBError(
                f"column {name!r} holds a {upper.split('(')[0].lower()}, which this engine does "
                f"not flatten yet; profile it with the default engine"
            )
        columns.append((str(name), _DTYPES.get(upper.split("(")[0], "string")))
    return columns


def _aggregate(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    columns: list[tuple[str, str]],
    sketch: bool,
) -> dict[str, Any]:
    """Every plain aggregate for every column, in one pass over the file."""
    quantile = "approx_quantile" if sketch else "quantile_cont"
    selects: list[str] = []
    aliases: list[str] = []

    def add(alias: str, expression: str) -> None:
        aliases.append(alias)
        selects.append(f"{expression} AS {alias}")

    for index, (name, dtype) in enumerate(columns):
        quoted = _quoted(name)
        add(f"nn_{index}", f"count({quoted})")
        add(f"card_{index}", f"count(DISTINCT {quoted})")
        if dtype in _NUMERIC:
            value = f"epoch({quoted})" if dtype == "datetime64" else quoted
            add(f"mean_{index}", f"avg({value})")
            add(f"std_{index}", f"stddev_pop({value})")
            add(f"min_{index}", f"min({value})")
            add(f"max_{index}", f"max({value})")
            add(f"q_{index}", f"{quantile}({value}, {_LEVELS})")

    row = _one(connection, f"SELECT {', '.join(selects)} FROM {relation}")
    return dict(zip(aliases, row, strict=False))


def _column_stats(
    connection: duckdb.DuckDBPyConnection,
    relation: str,
    name: str,
    dtype: str,
    index: int,
    row_count: int,
    aggregates: dict[str, Any],
) -> ColumnStats:
    non_null = int(aggregates[f"nn_{index}"])
    stats = ColumnStats(
        name=name,
        dtype=dtype,
        row_count=row_count,
        null_ratio=0.0 if row_count == 0 else round(1 - non_null / row_count, 6),
        cardinality=int(aggregates[f"card_{index}"]),
    )
    if not non_null:
        return stats

    if dtype in _NUMERIC:
        stats.mean = float(aggregates[f"mean_{index}"])
        stats.std = float(aggregates[f"std_{index}"] or 0.0)
        stats.minimum = float(aggregates[f"min_{index}"])
        stats.maximum = float(aggregates[f"max_{index}"])
        quantiles = [float(value) for value in aggregates[f"q_{index}"]]
        # Whether or not the grid was sketched, its ends are the exact aggregates: a sketch
        # is at its least accurate precisely there, since an extreme value is the single
        # observation it is most likely to have summarised away.
        quantiles[0], quantiles[-1] = stats.minimum, stats.maximum
        stats.quantiles = quantiles
    else:
        _categories(connection, relation, stats, non_null)
    return stats


def _categories(
    connection: duckdb.DuckDBPyConnection, relation: str, stats: ColumnStats, non_null: int
) -> None:
    """The mode, and the category counts when the column is one.

    The mode is taken for every column of values, the counts only for a column whose values
    repeat -- the same division the dataframe path makes, and for its reason: a column where
    nearly every value is distinct is an identifier, and the balance of an identifier is not a
    thing. Ties go to the first value in order, which is what `Series.mode` returns.

    Which categories survive the cut is only well defined when nothing ties across it. Where
    counts are equal on the boundary, this takes them in value order and the dataframe path
    takes them in whatever order its own version produces; both sum everything below into the
    same bucket, so the balance they report moves by the difference between two equal counts.
    """
    quoted = _quoted(stats.name)
    top = _all(
        connection,
        f"SELECT {quoted}::VARCHAR AS value, count(*) AS n FROM {relation} "
        f"WHERE {quoted} IS NOT NULL GROUP BY 1 ORDER BY n DESC, value "
        f"LIMIT {MAX_TRACKED_CATEGORIES}",
    )
    if not top:  # pragma: no cover - non_null is positive, so there is always a value
        return

    stats.mode = str(top[0][0])
    if stats.cardinality / non_null > MAX_CATEGORY_UNIQUENESS:
        return

    counts = {str(value): int(count) for value, count in top}
    tail = non_null - sum(counts.values())
    if tail:
        counts[OTHER_CATEGORY] = counts.get(OTHER_CATEGORY, 0) + tail
    stats.category_counts = counts
    if stats.cardinality <= MAX_TRACKED_CATEGORIES:
        stats.categories = sorted(counts)


def _quoted(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _one(connection: duckdb.DuckDBPyConnection, sql: str) -> tuple[Any, ...]:
    return _guarded(connection, sql).fetchone() or ()


def _all(connection: duckdb.DuckDBPyConnection, sql: str) -> list[tuple[Any, ...]]:
    return _guarded(connection, sql).fetchall()


def _guarded(connection: duckdb.DuckDBPyConnection, sql: str) -> duckdb.DuckDBPyConnection:
    """Run a statement, translating DuckDB's failures into this library's own."""
    import duckdb

    try:
        return connection.execute(sql)
    except duckdb.OutOfMemoryException as error:
        raise DuckDBError(
            f"DuckDB ran out of memory under {MEMORY_LIMIT_ENV_VAR}"
            f"={os.environ.get(MEMORY_LIMIT_ENV_VAR)!r}; raise it or use the default engine"
        ) from error
    except duckdb.Error as error:
        raise DuckDBError(f"DuckDB could not read the dataset: {error}") from error
