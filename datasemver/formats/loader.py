"""Dataset loading for the supported input formats."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pandas as pd

from datasemver.core.models import DatasetSchema
from datasemver.formats.utils import infer_types, profile_frame

CSV_EXTENSIONS = {".csv", ".tsv"}
DELIMITER_CANDIDATES = (",", ";", "\t", "|")
DEFAULT_DELIMITER = ","
DELIMITER_ENV_VAR = "DATASEMVER_CSV_DELIMITER"
ESCAPED_DELIMITERS = {"\\t": "\t"}
SNIFF_LINES = 20
JSON_EXTENSIONS = {".json", ".jsonl", ".ndjson"}
PARQUET_EXTENSIONS = {".parquet", ".pq"}
SUPPORTED_EXTENSIONS = CSV_EXTENSIONS | JSON_EXTENSIONS | PARQUET_EXTENSIONS
NESTED_SEPARATOR = "."


class UnsupportedFormatError(ValueError):
    """Raised when a file extension is not one of the supported formats."""


class DatasetReadError(ValueError):
    """Raised when a file has a supported extension but cannot be read."""


def load_frame(path: str | Path) -> pd.DataFrame:
    """Read a CSV, JSON or Parquet file into a flat dataframe with usable types."""
    path = _existing_path(path)
    suffix = path.suffix.lower()

    if suffix in PARQUET_EXTENSIONS:
        return load_parquet(path)

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
    path = _existing_path(path)
    try:
        frame = pd.read_parquet(path)
    except ImportError as error:
        raise DatasetReadError(
            "reading Parquet files requires the 'pyarrow' package: pip install pyarrow"
        ) from error
    except Exception as error:
        raise DatasetReadError(f"could not read Parquet file {path}: {error}") from error
    return _flatten_structs(frame)


def load_schema(path: str | Path) -> DatasetSchema:
    """Load a dataset and return its profile."""
    frame = load_frame(path)
    return schema_from_frame(frame, source=str(path))


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
    `.tsv` extension otherwise forces; write a tab as the two characters `\\t`, which an
    environment variable can carry, and leave the variable empty to mean unset. Without an
    override, `.tsv` is a tab and any other extension is sniffed by `detect_delimiter`.
    """
    override = _delimiter_override()
    if override is not None:
        return override
    if Path(path).suffix.lower() == ".tsv":
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
    with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
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
