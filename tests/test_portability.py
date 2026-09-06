"""Paths and text that behave differently depending on the operating system.

The failures these guard against do not appear on the machine most of the work happens on.
A filename with a space is fine on Linux and quoted differently on Windows; text outside
Latin-1 is fine everywhere until something opens a file without naming an encoding, at
which point Windows reaches for cp1252 and raises. So these run on all three in CI and are
the reason the matrix is worth its minutes.
"""

from __future__ import annotations

import sqlite3

import pytest

from datasemver import analyze
from datasemver.core.changelog import write_changelog
from datasemver.formats.loader import load_frame, load_schema

# Characters cp1252 cannot represent, so a read that fell back to it would raise rather
# than quietly mangle them.
BEYOND_LATIN1 = "日本語"

OLD_CSV = "id,nombre,categoría\n1,Ana Ruiz,café\n2,Bruno Sala,té\n3,Carla Díaz,café\n"
NEW_CSV = (
    "id,nombre,categoría,país\n"
    "1,Ana Ruiz,café,ES\n2,Bruno Sala,té,IT\n3,Carla Díaz,café,PT\n4,Diego Moró,mate,AR\n"
)


@pytest.fixture(params=["plain", "with spaces", "acentuación", BEYOND_LATIN1])
def awkward_directory(request, tmp_path):
    """A directory whose name is ordinary, spaced, accented, or outside Latin-1."""
    directory = tmp_path / request.param
    directory.mkdir()
    return directory


def write_pair(directory, stem="datos"):
    old = directory / f"{stem} v1.csv"
    new = directory / f"{stem} v2.csv"
    old.write_text(OLD_CSV, encoding="utf-8")
    new.write_text(NEW_CSV, encoding="utf-8")
    return old, new


def test_a_dataset_loads_from_an_awkward_path(awkward_directory):
    old, _ = write_pair(awkward_directory)

    frame = load_frame(old)

    assert list(frame.columns) == ["id", "nombre", "categoría"]
    assert frame["nombre"].iloc[0] == "Ana Ruiz"


def test_a_comparison_runs_through_an_awkward_path(awkward_directory):
    old, new = write_pair(awkward_directory)

    report = analyze(old, new, current_version="1.0.0")

    assert report.bump.value == "minor"
    assert "column_added" in {item.rule for item in report.classified}


def test_a_column_named_outside_ascii_survives_the_report(tmp_path):
    """The column name reaches the changelog, so it has to survive every hop to get there."""
    old = tmp_path / "old.csv"
    new = tmp_path / "new.csv"
    old.write_text("id,categoría\n1,café\n2,té\n", encoding="utf-8")
    new.write_text(f"id,categoría,{BEYOND_LATIN1}\n1,café,a\n2,té,b\n", encoding="utf-8")

    report = analyze(old, new, current_version="1.0.0")

    added = [item for item in report.classified if item.rule == "column_added"]
    assert BEYOND_LATIN1 in added[0].change.description


def test_a_changelog_written_to_an_awkward_path_reads_back(awkward_directory):
    old, new = write_pair(awkward_directory)
    report = analyze(old, new, current_version="1.0.0")
    target = awkward_directory / "CHANGELOG con espacios.md"

    write_changelog(report, target)

    # `país` is the column this comparison adds, so it is the non-ASCII name that has to
    # survive every hop from the CSV header to the file on disk.
    assert "país" in target.read_text(encoding="utf-8")


def test_a_changelog_is_prepended_without_mangling_what_was_there(tmp_path):
    """Reading the existing file back is where a default encoding would bite."""
    old, new = write_pair(tmp_path)
    report = analyze(old, new, current_version="1.0.0")
    target = tmp_path / "CHANGELOG.md"
    target.write_text(f"# Changelog\n\n## [0.9.0]\n\n- {BEYOND_LATIN1}\n", encoding="utf-8")

    write_changelog(report, target)

    body = target.read_text(encoding="utf-8")
    assert BEYOND_LATIN1 in body, "what was already in the file was mangled"
    assert "país" in body, "what the report added was mangled"


def test_the_report_names_the_source_as_given(awkward_directory):
    old, _ = write_pair(awkward_directory)

    schema = load_schema(old)

    assert schema.source.endswith("datos v1.csv")


def test_a_database_opens_from_an_awkward_path(awkward_directory):
    """SQLite takes the path as a string, which is where separators diverge."""
    pytest.importorskip("sqlalchemy")
    database = awkward_directory / "tienda de café.db"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE clientes (id INTEGER, categoría TEXT)")
    connection.executemany("INSERT INTO clientes VALUES (?,?)", [(1, "café"), (2, "té")])
    connection.commit()
    connection.close()

    frame = load_frame(f"sqlite:///{database}#clientes")

    assert list(frame.columns) == ["id", "categoría"]
    assert frame["categoría"].iloc[0] == "café"


def test_carriage_returns_do_not_reach_the_delimiter_decision(tmp_path):
    """A file written on Windows ends its lines with \\r\\n, which is not a delimiter."""
    path = tmp_path / "crlf.csv"
    path.write_bytes(b"id;nombre\r\n1;ana\r\n2;bruno\r\n")

    frame = load_frame(path)

    assert list(frame.columns) == ["id", "nombre"]
    assert frame["nombre"].iloc[1] == "bruno"
