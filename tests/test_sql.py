"""Tests for reading a database table as a dataset.

Everything here runs against SQLite, which needs no server and no driver beyond the standard
library. The parts that are specific to PostgreSQL or MySQL are the URL rewrites, and those
are tested as string transformations rather than by standing a database up.
"""

from __future__ import annotations

import sqlite3

import pytest

pytest.importorskip("sqlalchemy")

from datasemver import analyze
from datasemver.formats.loader import DatasetReadError, load_frame, load_schema
from datasemver.formats.sql import (
    SqlSourceError,
    is_sql_source,
    load_sql,
    redacted,
    split_source,
)
from datasemver.formats.utils import canonical_dtype

OLD_ROWS = [
    (
        index,
        f"cliente{index}",
        600_000_000 + index,
        ["free", "pro", "team"][index % 3],
        f"LG-{index}",
    )
    for index in range(40)
]
NEW_ROWS = [
    (
        index,
        f"cliente{index}",
        f"+34 600 {index:06d}",
        ["free", "pro", "team"][index % 3],
        ["ES", "IT", "PT"][index % 3],
    )
    for index in range(48)
]


@pytest.fixture
def database(tmp_path):
    """A file holding the same dataset twice, once before a breaking change and once after."""
    path = tmp_path / "shop.db"
    connection = sqlite3.connect(path)
    connection.execute(
        "CREATE TABLE customers_v1 (id INTEGER, name TEXT, phone INTEGER, plan TEXT, legacy TEXT)"
    )
    connection.executemany("INSERT INTO customers_v1 VALUES (?,?,?,?,?)", OLD_ROWS)
    connection.execute(
        "CREATE TABLE customers_v2 (id INTEGER, name TEXT, phone TEXT, plan TEXT, country TEXT)"
    )
    connection.executemany("INSERT INTO customers_v2 VALUES (?,?,?,?,?)", NEW_ROWS)
    connection.commit()
    connection.close()
    return path


def source(path, table):
    return f"sqlite:///{path}#{table}"


# --- reading -------------------------------------------------------------------------------


def test_a_table_loads_with_its_declared_types(database):
    frame = load_frame(source(database, "customers_v1"))

    assert list(frame.columns) == ["id", "name", "phone", "plan", "legacy"]
    assert len(frame) == 40
    assert str(frame["id"].dtype) == "int64"


def test_a_column_typed_by_the_database_is_not_reinferred(database):
    """SQLite declares `phone` as TEXT in the second table, and that answer is kept.

    Asserted through `canonical_dtype` rather than the raw pandas dtype, which is `object`
    on pandas 2 and `str` on pandas 3 for the same column.
    """
    frame = load_frame(source(database, "customers_v2"))

    assert canonical_dtype(frame["phone"]) == "string"


def test_two_tables_compare_like_two_files(database):
    report = analyze(
        source(database, "customers_v1"),
        source(database, "customers_v2"),
        current_version="1.4.2",
    )

    assert report.bump.value == "major"
    assert report.next_version == "2.0.0"
    rules = {item.rule for item in report.classified}
    assert "column_removed" in rules
    assert "type_changed_incompatible" in rules


def test_the_same_data_reads_the_same_from_sql_and_csv(database, tmp_path):
    """A database and a CSV of the same rows have to reach the same verdict.

    This is the claim the feature rests on: SQL is another way in, not another analysis.
    """
    from_sql = analyze(
        source(database, "customers_v1"), source(database, "customers_v2"), current_version="1.0.0"
    )

    old_csv, new_csv = tmp_path / "old.csv", tmp_path / "new.csv"
    load_frame(source(database, "customers_v1")).to_csv(old_csv, index=False)
    load_frame(source(database, "customers_v2")).to_csv(new_csv, index=False)
    from_csv = analyze(old_csv, new_csv, current_version="1.0.0")

    assert from_sql.bump == from_csv.bump
    assert from_sql.next_version == from_csv.next_version
    assert {i.rule for i in from_sql.classified} == {i.rule for i in from_csv.classified}


# --- what a source is ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        "sqlite:///a.db",
        "postgresql://h/d",
        "postgres://h/d",
        "mysql://h/d",
        "mariadb://h/d",
        "postgresql+psycopg://h/d",
        "SQLITE:///a.db",
    ],
)
def test_database_urls_are_recognised(value):
    assert is_sql_source(value)


@pytest.mark.parametrize(
    "value",
    ["data.csv", "/tmp/a.json", "s3://bucket/key.csv", "https://example.com/a.csv", "a#b.csv"],
)
def test_everything_else_is_a_path(value):
    """A path is the default, so an unknown scheme is read as a file and fails as one."""
    assert not is_sql_source(value)


def test_a_source_without_a_table_says_how_to_name_one():
    with pytest.raises(SqlSourceError, match="name one after"):
        split_source("sqlite:///a.db")


def test_a_trailing_separator_is_not_a_table():
    with pytest.raises(SqlSourceError, match="name one after"):
        split_source("sqlite:///a.db#   ")


def test_a_table_with_no_url_is_rejected():
    with pytest.raises(SqlSourceError, match="no connection URL"):
        split_source("#customers")


# --- credentials ---------------------------------------------------------------------------


def test_a_password_never_reaches_the_report(database, tmp_path):
    """The source is rendered into changelogs, comments and JSON. Passwords are not."""
    assert redacted("postgresql://reader:hunter2@host:5432/db#customers") == (
        "postgresql://reader:***@host:5432/db#customers"
    )


def test_redaction_survives_a_url_it_cannot_parse():
    """A malformed URL is reported in an error message, which must not carry the password."""
    hidden = redacted("postgresql://reader:hunter2@host:not-a-port/db#customers")

    assert "hunter2" not in hidden
    assert "reader" in hidden


def test_a_source_with_no_password_is_left_alone():
    assert redacted("sqlite:///a.db#customers") == "sqlite:///a.db#customers"


def test_the_report_names_the_table_without_the_password(database):
    schema = load_schema(source(database, "customers_v1"))

    assert schema.source.endswith("#customers_v1")
    assert "***" not in schema.source


# --- failure -------------------------------------------------------------------------------


def test_a_missing_table_is_named(database):
    with pytest.raises(DatasetReadError, match="no table named 'nope'"):
        load_sql(source(database, "nope"))


def test_a_database_that_is_not_there_reports_rather_than_traces(tmp_path):
    with pytest.raises(DatasetReadError):
        load_sql(f"sqlite:///{tmp_path / 'absent.db'}#customers")


def test_an_unreachable_server_reports_rather_than_traces():
    """The point is the shape of the failure: one sentence, not a driver traceback."""
    with pytest.raises(DatasetReadError) as raised:
        load_sql("postgresql://someone:secret@127.0.0.1:59999/nothing#customers")

    message = str(raised.value)
    assert "secret" not in message
    assert "\n" not in message


def test_an_unsupported_scheme_reaches_the_file_reader():
    """`oracle://` is not claimed, so it is read as a path and fails as a missing file."""
    with pytest.raises(FileNotFoundError):
        load_frame("oracle://host/db#customers")


# --- the two URLs people write that SQLAlchemy does not accept -----------------------------


def test_postgres_is_read_as_postgresql():
    """Asserted through the error, which names the driver the rewritten URL resolves to.

    Without the rewrite this fails with "Can't load plugin: sqlalchemy.dialects:postgres",
    which says nothing about the scheme being the thing to change.
    """
    with pytest.raises(DatasetReadError, match="psycopg2"):
        load_sql("postgres://user:secret@host/db#customers")


def test_bare_mysql_is_pointed_at_the_driver_that_ships():
    """A bare `mysql://` resolves to MySQLdb, which the sql extra does not install."""
    with pytest.raises(DatasetReadError, match="pymysql"):
        load_sql("mysql://user:secret@host/db#customers")


def test_a_driver_the_caller_named_is_left_alone():
    with pytest.raises(DatasetReadError, match=r"mysqldb|MySQLdb"):
        load_sql("mysql+mysqldb://user:secret@host/db#customers")


def test_a_driver_error_keeps_the_password_out():
    with pytest.raises(DatasetReadError) as raised:
        load_sql("postgresql://user:hunter2@host/db#customers")

    assert "hunter2" not in str(raised.value)


def test_a_url_that_is_not_a_url_is_rejected_as_one():
    with pytest.raises(SqlSourceError, match="connection URL"):
        load_sql("://nothing#customers")


def test_a_port_that_is_not_a_number_is_a_url_problem():
    """int() raises a bare ValueError here, which would otherwise reach the caller as
    `invalid literal for int() with base 10` and say nothing about the URL."""
    with pytest.raises(SqlSourceError, match="connection URL"):
        load_sql("postgresql://user:secret@host:notaport/db#customers")


def test_a_bad_port_does_not_leak_the_password():
    with pytest.raises(SqlSourceError) as raised:
        load_sql("postgresql://user:hunter2@host:notaport/db#customers")

    assert "hunter2" not in str(raised.value)
