"""Reading a worksheet as a dataset.

A workbook holds several sheets, so the source names one the way a database source names a
table -- after a `#`:

    quarterly.xlsx
    quarterly.xlsx#Q3
    quarterly.xlsx#2

Without a fragment the first sheet is read, which is what a single-sheet export is. The same
separator as the SQL sources on purpose: a workbook and a database are the two formats here
that hold more than one dataset per source, and learning one spelling should be enough.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from datasemver.utils.extras import install_hint as _install_hint

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

EXCEL_EXTENSIONS = {".xlsx", ".xlsm"}
SHEET_SEPARATOR = "#"


def install_hint() -> str:
    """Read at call time: the advice differs inside the standalone executable."""
    return _install_hint("excel", "reading a workbook")


class ExcelSourceError(ValueError):
    """Raised when a source names a workbook but cannot be understood as one."""


def split_source(source: str) -> tuple[str, str | int | None]:
    """Separate the workbook path from the sheet named after `#`.

    A fragment of digits is a position rather than a name, because `#2` is what someone means
    by the second sheet and a sheet literally called "2" is rarer than the mistake would be
    annoying. Quote it as `#'2'` to mean the name.
    """
    path, separator, sheet = source.partition(SHEET_SEPARATOR)
    if not separator:
        return source, None
    sheet = sheet.strip()
    if not sheet:
        raise ExcelSourceError(
            f"no sheet after '{SHEET_SEPARATOR}' in '{source}': name one, or drop the "
            f"'{SHEET_SEPARATOR}' to read the first"
        )
    if sheet.startswith("'") and sheet.endswith("'") and len(sheet) > 1:
        return path, sheet[1:-1]
    if sheet.isdigit():
        return path, int(sheet)
    return path, sheet


def is_excel_source(source: str | Path) -> bool:
    """Whether a source names a workbook, with or without a sheet after it."""
    path, _, _ = str(source).partition(SHEET_SEPARATOR)
    return Path(path).suffix.lower() in EXCEL_EXTENSIONS


def load_excel(source: str | Path) -> pd.DataFrame:
    """Read one worksheet into a dataframe.

    Only the sheet asked for is parsed. `read_excel` will happily return every sheet in the
    book as a dict when asked for none, and a caller expecting one dataset would get a
    mapping it has no idea what to do with.
    """
    import pandas as pd

    path, sheet = split_source(str(source))
    location = Path(path)
    if not location.exists():
        raise FileNotFoundError(f"dataset not found: {location}")

    try:
        frame = pd.read_excel(location, sheet_name=0 if sheet is None else sheet)
    except ImportError as error:  # pragma: no cover - exercised by the extra being absent
        raise _read_error(f"{install_hint()} ({error})") from error
    except ValueError as error:
        raise _sheet_error(error, sheet, location) from error
    except Exception as error:
        detail = _first_line(error)
        raise _read_error(f"could not read the workbook {location}: {detail}") from error

    return frame


def _sheet_error(error: Exception, sheet: str | int | None, path: Path) -> Exception:
    """Name the sheets there are, since a wrong one is usually a typo or a renamed tab."""
    if "Worksheet" not in str(error) and "sheet" not in str(error).lower():
        return _read_error(f"could not read the workbook {path}: {_first_line(error)}")
    return _read_error(
        f"the workbook {path} has no sheet {sheet!r}. It has: {', '.join(sheet_names(path))}"
    )


def sheet_names(path: str | Path) -> list[str]:
    """Every sheet in a workbook, for an error message that saves a second attempt."""
    import pandas as pd

    try:
        with pd.ExcelFile(path) as book:
            return [str(name) for name in book.sheet_names]
    except Exception:  # pragma: no cover - the caller is already reporting a failure
        return []


def _first_line(error: Exception) -> str:
    return str(error).strip().splitlines()[0][:200]


def _read_error(message: str) -> Exception:
    from datasemver.formats.loader import DatasetReadError

    return DatasetReadError(message)
