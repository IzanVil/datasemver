"""Tests for reading a worksheet as a dataset.

A workbook is the first format here that holds more than one dataset per file and is also a
path, so most of what can go wrong is in the source string rather than in the parsing: which
sheet was meant, and what to say when it is not there.
"""

from __future__ import annotations

import pandas as pd
import pytest

pytest.importorskip("openpyxl")

from datasemver import analyze
from datasemver.core.models import Severity
from datasemver.formats.excel import (
    ExcelSourceError,
    is_excel_source,
    load_excel,
    split_source,
)
from datasemver.formats.loader import DatasetReadError, load_frame


@pytest.fixture
def workbook(tmp_path):
    """Two sheets, so "which one" is always a real question."""
    path = tmp_path / "quarterly.xlsx"
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame({"id": [1, 2, 3], "region": ["n", "s", "n"]}).to_excel(
            writer, sheet_name="Q1", index=False
        )
        pd.DataFrame({"id": [1, 2, 3, 4]}).to_excel(writer, sheet_name="Q2", index=False)
    return path


# --- naming a sheet ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("book.xlsx", ("book.xlsx", None)),
        ("book.xlsx#Q3", ("book.xlsx", "Q3")),
        ("book.xlsx#2", ("book.xlsx", 2)),
        ("book.xlsx#'2'", ("book.xlsx", "2")),
        ("/data/a b/book.xlsm#Sheet 1", ("/data/a b/book.xlsm", "Sheet 1")),
    ],
)
def test_the_sheet_is_read_off_the_source(source, expected):
    assert split_source(source) == expected


def test_a_bare_hash_says_what_to_do_instead():
    with pytest.raises(ExcelSourceError, match="name one, or drop"):
        split_source("book.xlsx#")


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("book.xlsx", True),
        ("book.XLSX#Q1", True),
        ("book.xlsm", True),
        ("book.csv", False),
        ("sqlite:///data.db#customers", False),
    ],
)
def test_only_a_workbook_is_dispatched_as_one(source, expected):
    assert is_excel_source(source) is expected


# --- reading ----------------------------------------------------------------------------------


def test_the_first_sheet_is_read_when_none_is_named(workbook):
    """A single-sheet export is the common case and should need no fragment."""
    assert list(load_excel(workbook).columns) == ["id", "region"]


def test_a_sheet_can_be_named(workbook):
    assert list(load_excel(f"{workbook}#Q2").columns) == ["id"]


def test_a_sheet_can_be_taken_by_position(workbook):
    assert list(load_excel(f"{workbook}#1").columns) == ["id"]


def test_a_workbook_reaches_the_loader_like_any_other_source(workbook):
    """The dispatch has to happen before the path check, since `#Q2` is not a path."""
    assert list(load_frame(f"{workbook}#Q2").columns) == ["id"]


def test_types_are_inferred_the_way_they_are_for_text_formats(tmp_path):
    """Excel stores numbers as text often enough that trusting the cell type is not enough."""
    path = tmp_path / "typed.xlsx"
    pd.DataFrame({"n": ["1", "2", "3"]}).to_excel(path, index=False)

    assert str(load_frame(path)["n"].dtype) == "int64"


# --- what it says when it cannot --------------------------------------------------------------


def test_a_missing_sheet_names_the_sheets_there_are(workbook):
    """The next thing the reader needs is the spelling, not the fact that they got it wrong."""
    with pytest.raises(DatasetReadError, match="Q1, Q2"):
        load_excel(f"{workbook}#Q3")


def test_a_missing_workbook_is_reported_as_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="dataset not found"):
        load_excel(f"{tmp_path / 'absent.xlsx'}#Q1")


def test_a_file_that_is_not_a_workbook_is_refused(tmp_path):
    broken = tmp_path / "broken.xlsx"
    broken.write_text("not a workbook", encoding="utf-8")

    with pytest.raises(DatasetReadError, match="could not read the workbook"):
        load_excel(broken)


# --- end to end ---------------------------------------------------------------------------------


def test_two_sheets_of_one_workbook_can_be_compared(workbook):
    """The case a spreadsheet user actually has: last quarter and this one, one file."""
    report = analyze(f"{workbook}#Q1", f"{workbook}#Q2", current_version="1.0.0")

    assert report.bump is Severity.MAJOR
    assert any(change.column == "region" for change in report.diff.changes)


def test_a_workbook_compares_against_any_other_format(workbook, new_csv):
    """Nothing about the comparison knows where a frame came from, and that has to stay true."""
    assert analyze(f"{workbook}#Q1", new_csv, current_version="1.0.0").bump is Severity.MAJOR


def test_a_zip_that_is_not_a_workbook_is_refused(tmp_path):
    """A valid archive with the right extension fails past the sheet lookup, not at it."""
    import zipfile

    pretend = tmp_path / "pretend.xlsx"
    with zipfile.ZipFile(pretend, "w") as archive:
        archive.writestr("hello.txt", "not a workbook")

    with pytest.raises(DatasetReadError, match="could not read the workbook"):
        load_excel(pretend)
