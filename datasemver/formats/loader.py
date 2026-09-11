"""Dataset loading for the supported input formats."""

from __future__ import annotations

import gzip
import json
import os
import re
from collections.abc import Callable
from enum import Enum
from pathlib import Path

import pandas as pd

from datasemver.core.models import DatasetSchema
from datasemver.core.profile import PROFILE_SUFFIX, is_profile, read_profile
from datasemver.formats.duck import DUCKDB_EXTENSIONS, is_duckdb_readable, profile_source
from datasemver.formats.excel import EXCEL_EXTENSIONS, is_excel_source, load_excel
from datasemver.formats.excel import split_source as split_sheet
from datasemver.formats.metadata import schema_from_metadata
from datasemver.formats.sql import SqlSourceError, is_sql_source, load_sql, redacted
from datasemver.formats.sql import split_source as split_table
from datasemver.formats.utils import infer_types, profile_frame

CSV_EXTENSIONS = {".csv", ".tsv", ".csv.gz", ".tsv.gz"}
DELIMITER_CANDIDATES = (",", ";", "\t", "|")
DEFAULT_DELIMITER = ","
DELIMITER_ENV_VAR = "DATASEMVER_CSV_DELIMITER"
ESCAPED_DELIMITERS = {"\\t": "\t"}
SNIFF_LINES = 20
JSON_EXTENSIONS = {".json", ".jsonl", ".ndjson"}
PARQUET_EXTENSIONS = {".parquet", ".pq"}
# Feather is the Arrow IPC file format, and both spellings are in use: pandas writes
# `.feather`, Arrow's own tooling tends to write `.arrow` for the same bytes.
FEATHER_EXTENSIONS = {".feather", ".arrow"}
SUPPORTED_EXTENSIONS = (
    CSV_EXTENSIONS | JSON_EXTENSIONS | PARQUET_EXTENSIONS | FEATHER_EXTENSIONS | EXCEL_EXTENSIONS
)
NESTED_SEPARATOR = "."

ENGINE_ENV_VAR = "DATASEMVER_ENGINE"


class Engine(str, Enum):
    """How a dataset is profiled: by loading it, or by aggregating over it.

    `pandas` loads the dataset. `duckdb` aggregates over the file instead, which costs about
    half the memory and answers identically, down to float rounding. `duckdb-sketch` is the
    same with the quantile grid estimated rather than computed, which is a third of the memory
    again and the only one of the three whose numbers differ -- by 0.23% of a column's range at
    worst, measured, and by more than that on a dataset small enough to read by hand.

    Chosen rather than guessed. Switching engine for someone because their file looked large
    would trade one surprise for another: a run that refuses a workbook it read yesterday,
    because these two read fewer formats than the library does.
    """

    PANDAS = "pandas"
    DUCKDB = "duckdb"
    DUCKDB_SKETCH = "duckdb-sketch"

    @property
    def is_duckdb(self) -> bool:
        return self in {Engine.DUCKDB, Engine.DUCKDB_SKETCH}


def resolve_engine(engine: str | None) -> Engine:
    """The engine to profile with: the argument, then the environment, then the default.

    The environment is read here rather than in the CLI so that every caller obeys it -- the
    dashboard, the DVC run and the pull request script reach profiling through this module and
    none of them grew an option.
    """
    chosen = engine or os.environ.get(ENGINE_ENV_VAR) or Engine.PANDAS.value
    try:
        return Engine(str(chosen).lower())
    except ValueError as error:
        raise UnsupportedFormatError(
            f"unknown engine {chosen!r}, expected one of {[item.value for item in Engine]}"
        ) from error


# What a table or sheet name may keep when it becomes a file name: letters, digits,
# underscores, dots and dashes. Everything else -- separators above all -- becomes a dash.
_UNSAFE_IN_NAME = re.compile(r"[^\w.-]+")


class UnsupportedFormatError(ValueError):
    """Raised when a file extension is not one of the supported formats."""


class DatasetReadError(ValueError):
    """Raised when a file has a supported extension but cannot be read."""


def dataset_suffix(path: str | Path) -> str:
    """Return the effective dataset suffix, including supported compound suffixes.

    ``Path.suffix`` returns only ``.gz`` for a compressed CSV or TSV. Keeping this
    rule here gives every integration one definition of a dataset's format.
    """
    path = Path(path)
    name = path.name.lower()
    for extension in sorted(SUPPORTED_EXTENSIONS, key=len, reverse=True):
        if name.endswith(extension):
            return extension
    return path.suffix.lower()


def load_frame(path: str | Path) -> pd.DataFrame:
    """Read a file or a database table into a flat dataframe with usable types.

    Dispatching here rather than in the CLI is what lets every other caller read a database
    too: the Python API, the dashboard and the pull request script all arrive through this
    function, and none of them had to learn what a connection URL is.
    """
    if isinstance(path, str) and is_sql_source(path):
        return infer_types(load_sql(path))

    # Before `_existing_path`, because a workbook source may carry a sheet after `#` and the
    # whole string is not a path that exists.
    if is_excel_source(path):
        return infer_types(load_excel(path))

    path = _existing_path(path)
    suffix = dataset_suffix(path)

    if suffix in PARQUET_EXTENSIONS:
        return load_parquet(path)

    if suffix in FEATHER_EXTENSIONS:
        return load_feather(path)

    if suffix in CSV_EXTENSIONS:
        frame = _read_csv(path)
    elif suffix in JSON_EXTENSIONS:
        frame = _read_json(path)
    else:
        raise UnsupportedFormatError(
            f"unsupported extension '{suffix}', expected one of {sorted(SUPPORTED_EXTENSIONS)}"
        )
    return infer_types(frame)


def load_parquet(path: str | Path) -> pd.DataFrame:
    """Read a Parquet file into a flat dataframe, trusting its declared schema.

    Unlike the text formats, Parquet carries its own types, so no inference is applied:
    a column stored as a string stays a string even when every value looks numeric.
    """
    return _read_arrow(_existing_path(path), pd.read_parquet, "Parquet")


def load_feather(path: str | Path) -> pd.DataFrame:
    """Read a Feather file into a flat dataframe, trusting its declared schema.

    Trusted for the same reason as Parquet, and it is literally the same reason: both are
    Arrow, so the file states the type of every column. Inferring here would be second-
    guessing a schema that was written down, where the CSV path infers because there is
    none to read -- a column of postcodes stays strings instead of becoming integers with
    the leading zero gone.
    """
    return _read_arrow(_existing_path(path), pd.read_feather, "Feather")


def _read_arrow(path: Path, read: Callable[[Path], pd.DataFrame], label: str) -> pd.DataFrame:
    """Read one of the Arrow-backed formats, failing the same way for both."""
    try:
        frame = read(path)
    except ImportError as error:
        raise DatasetReadError(
            f"reading {label} files requires the 'pyarrow' package: pip install pyarrow"
        ) from error
    except Exception as error:
        raise DatasetReadError(f"could not read {label} file {path}: {error}") from error
    return _flatten_structs(frame)


def load_schema(
    path: str | Path, schema_only: bool = False, engine: str | None = None
) -> DatasetSchema:
    """Load a dataset and return its profile, or read a profile that was already stored.

    Dispatching on the source here rather than in the CLI is what gives every caller the
    stored profile for free -- the Python API, the dashboard, the DVC run and the pull
    request script all arrive through this function, exactly as they do for a database URL.
    A comparison against a profile never loads the dataset behind it, because there may not
    be one any more.

    `engine` chooses how a dataset that does have to be read is profiled. The default loads
    it into a dataframe; `duckdb` aggregates over the file instead, which is what makes a
    dataset larger than memory profilable at all.
    """
    if is_profile(path):
        return read_profile(path)
    if schema_only and _is_parquet_file(path):
        return schema_from_metadata(_existing_path(path), source=describe_source(path))
    chosen = resolve_engine(engine)
    if chosen.is_duckdb:
        return duckdb_schema(path, sketch=chosen is Engine.DUCKDB_SKETCH)
    frame = load_frame(path)
    return schema_from_frame(frame, source=describe_source(path))


def duckdb_schema(path: str | Path, sketch: bool = False) -> DatasetSchema:
    """Profile a file with DuckDB, refusing by name what that engine cannot read.

    Refused rather than quietly handed back to the dataframe path. The engines agree on what
    they both read, and that is exactly why a silent fall back is wrong: it would hide that a
    memory ceiling someone chose this engine for is not being held for this file.
    """
    if isinstance(path, str) and is_sql_source(path):
        raise UnsupportedFormatError(
            "the duckdb engine reads files; a database table is read through the default engine"
        )
    existing = _existing_path(path)
    suffix = dataset_suffix(existing)
    if not is_duckdb_readable(existing):
        raise UnsupportedFormatError(
            f"the duckdb engine does not read '{suffix}', only {sorted(DUCKDB_EXTENSIONS)}; "
            f"profile it with the default engine"
        )
    delimiter = csv_delimiter(existing) if suffix in CSV_EXTENSIONS else None
    return profile_source(
        existing, source=describe_source(path), delimiter=delimiter, sketch=sketch
    )


def _is_parquet_file(path: str | Path) -> bool:
    """Only a Parquet file has a footer to read instead of rows; everything else is read."""
    if isinstance(path, str) and is_sql_source(path):
        return False
    return Path(path).suffix.lower() in PARQUET_EXTENSIONS


def describe_source(path: str | Path) -> str:
    """How a source should be named in a report.

    The name reaches a changelog entry, a pull request comment and the JSON output, so a
    connection URL arrives there without its password.
    """
    if isinstance(path, str) and is_sql_source(path):
        return redacted(path)
    return str(path)


def default_profile_path(source: str | Path) -> Path:
    """Where a profile goes when the caller does not say.

    Beside the dataset it describes, under the same name with the format suffix replaced --
    and everything before that suffix is kept. `sales.2024.csv` and `sales.2025.csv` are two
    versions of one dataset, which is the case this tool exists for, and naming both of them
    `sales.profile.json` made the second overwrite the first without saying so.

    A source that is not a file has nothing to sit beside, so a table and a sheet are named
    after what they hold, in the working directory. A connection URL never reaches the name:
    it carries a password, a file name is not a place to keep one, and the profile's own
    contents are redacted for that same reason.

    This lives here rather than beside `write_profile` because naming a profile means knowing
    what a dataset suffix is and what a connection URL is, which is what this module knows.
    `core.profile` reaching for either would close the import circle it is already written
    around.
    """
    if isinstance(source, str) and is_sql_source(source):
        return Path(f"{_as_file_name(_table_of(source))}{PROFILE_SUFFIX}")

    if is_excel_source(source):
        workbook, sheet = split_sheet(str(source))
        path = Path(workbook)
        stem = _dataset_stem(path)
        if sheet is not None:
            stem = f"{stem}-{_as_file_name(str(sheet))}"
        return path.with_name(f"{stem}{PROFILE_SUFFIX}")

    path = Path(str(source))
    return path.with_name(f"{_dataset_stem(path)}{PROFILE_SUFFIX}")


def _dataset_stem(path: Path) -> str:
    """The file name without the suffix that says which format it is in."""
    suffix = dataset_suffix(path)
    if suffix and path.name.lower().endswith(suffix):
        return path.name[: -len(suffix)] or path.name
    return path.name


def _table_of(source: str) -> str:
    """The table a database source names, or a stand-in when it names none.

    A source with no table never reaches a profile -- reading it fails first -- but naming
    one must not raise on its own.
    """
    try:
        return split_table(source)[1]
    except SqlSourceError:
        return "dataset"


def _as_file_name(name: str) -> str:
    """A table or sheet name made safe to use as a file name.

    It comes from a database or a workbook rather than from a file system, so nothing stopped
    it holding a separator: `sales/2024` would otherwise name a directory that is not there.
    """
    return _UNSAFE_IN_NAME.sub("-", name).strip("-.") or "dataset"


def schema_from_frame(frame: pd.DataFrame, source: str) -> DatasetSchema:
    """Profile an already loaded dataframe."""
    return DatasetSchema(
        source=source,
        row_count=len(frame),
        columns=profile_frame(frame),
    )


def _existing_path(path: str | Path) -> Path:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"dataset not found: {path}")
    return path


def _flatten_structs(frame: pd.DataFrame) -> pd.DataFrame:
    """Expand Parquet struct columns into dotted columns, as json_normalize does."""
    nested = [name for name in frame.columns if _holds_mappings(frame[name])]
    if not nested:
        return frame

    flat = frame.drop(columns=nested)
    for name in nested:
        records = frame[name].map(lambda value: value if isinstance(value, dict) else {})
        expanded = pd.json_normalize(records, sep=NESTED_SEPARATOR)
        expanded.columns = [f"{name}{NESTED_SEPARATOR}{field}" for field in expanded.columns]
        expanded.index = frame.index
        flat = pd.concat([flat, expanded], axis=1)
    return flat


def _holds_mappings(series: pd.Series) -> bool:
    non_null = series.dropna()
    return not non_null.empty and isinstance(non_null.iloc[0], dict)


def _read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, sep=csv_delimiter(path), keep_default_na=True)


def csv_delimiter(path: str | Path) -> str:
    """Resolve the delimiter a delimited text file should be read with.

    An explicit `DATASEMVER_CSV_DELIMITER` wins over everything, including the tab that a
    `.tsv` or `.tsv.gz` extension otherwise forces; write a tab as the two characters `\\t`,
    which an environment variable can carry, and leave the variable empty to mean unset.
    Without an override, `.tsv` and `.tsv.gz` are tabs and any other extension is sniffed
    by `detect_delimiter`.
    """
    override = _delimiter_override()
    if override is not None:
        return override
    suffix = dataset_suffix(path)
    if suffix in (".tsv", ".tsv.gz"):
        return "\t"
    return detect_delimiter(path)


def _delimiter_override() -> str | None:
    raw = os.environ.get(DELIMITER_ENV_VAR)
    if not raw:
        return None

    delimiter = ESCAPED_DELIMITERS.get(raw, raw)
    if len(delimiter) != 1:
        raise DatasetReadError(f"{DELIMITER_ENV_VAR} must be a single character, got {raw!r}")
    return delimiter


def detect_delimiter(path: str | Path, default: str = DEFAULT_DELIMITER) -> str:
    """Guess the delimiter of a delimited text file from its first lines.

    A candidate only wins if it appears in the header and splits every sampled line into
    the same number of fields, which rules out characters that merely happen to occur
    inside values. Ties keep the order of `DELIMITER_CANDIDATES`, so a comma wins over a
    semicolon when both describe the file equally well.
    """
    lines = _sample_lines(Path(path))
    if not lines:
        return default

    best = default
    best_count = 0
    for candidate in DELIMITER_CANDIDATES:
        counts = [_count_outside_quotes(line, candidate) for line in lines]
        if counts[0] == 0 or len(set(counts)) > 1:
            continue
        if counts[0] > best_count:
            best, best_count = candidate, counts[0]
    return best


def _sample_lines(path: Path) -> list[str]:
    """Read the first few non-empty lines from a plain or gzip-compressed text file."""
    opener = gzip.open if path.name.lower().endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace", newline="") as handle:
        lines = []
        for line in handle:
            stripped = line.strip("\r\n")
            if stripped:
                lines.append(stripped)
            if len(lines) == SNIFF_LINES:
                break
    return lines


def _count_outside_quotes(line: str, delimiter: str) -> int:
    """Count delimiters that are not inside a quoted field."""
    count = 0
    quoted = False
    for character in line:
        if character == '"':
            quoted = not quoted
        elif character == delimiter and not quoted:
            count += 1
    return count


def _read_json(path: Path) -> pd.DataFrame:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return pd.DataFrame()

    records = _parse_json_document(text)
    if not isinstance(records, list):
        records = [records]
    return pd.json_normalize(records, sep=NESTED_SEPARATOR)


def _parse_json_document(text: str) -> object:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return [json.loads(line) for line in text.splitlines() if line.strip()]
