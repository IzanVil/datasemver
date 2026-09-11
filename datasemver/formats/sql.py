"""Reading a database table as a dataset.

A source is a SQLAlchemy URL with the table in its fragment:

    sqlite:////data/snapshots.db#customers
    postgresql://reader:secret@warehouse:5432/analytics#customers
    mysql://reader:secret@warehouse/analytics#customers

The fragment is not part of a SQLAlchemy URL, which is exactly why it is a good place to
put the table: it cannot collide with anything the URL itself means.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from datasemver.utils.extras import install_hint as _install_hint

if TYPE_CHECKING:  # pragma: no cover
    import pandas as pd

TABLE_SEPARATOR = "#"

# Schemes this module will claim from a command line. `postgres` is here because people
# write it, not because SQLAlchemy accepts it; see `_normalised`.
SQL_SCHEMES = (
    "sqlite",
    "postgresql",
    "postgres",
    "mysql",
    "mariadb",
)


def install_hint() -> str:
    """Read at call time: the advice differs inside the standalone executable."""
    return _install_hint("sql", "reading a database")


class SqlSourceError(ValueError):
    """Raised when a source names a database but cannot be understood as one."""


def is_sql_source(source: str) -> bool:
    """Whether a source should be read as a database table rather than a file.

    Matches on the scheme rather than on the presence of `://`, so a path that happens to
    contain one is still treated as a path.
    """
    scheme, separator, _ = source.partition("://")
    if not separator:
        return False
    return scheme.split("+", 1)[0].lower() in SQL_SCHEMES


def split_source(source: str) -> tuple[str, str]:
    """Separate the connection URL from the table named after `#`."""
    url, separator, table = source.partition(TABLE_SEPARATOR)
    if not separator or not table.strip():
        raise SqlSourceError(
            f"no table in '{redacted(source)}': name one after '{TABLE_SEPARATOR}', "
            f"as in 'sqlite:///data.db{TABLE_SEPARATOR}customers'"
        )
    if not url.strip():
        raise SqlSourceError("no connection URL before the table name")
    return url, table.strip()


def redacted(source: str) -> str:
    """The source with its password removed, safe to put in a report.

    The source travels into the analysis report, which reaches a changelog entry, a pull
    request comment and `--json` output. A connection string carries a password, and none of
    those places should be where it ends up.
    """
    url, separator, table = source.partition(TABLE_SEPARATOR)
    try:
        from sqlalchemy.engine import make_url

        hidden = make_url(url).render_as_string(hide_password=True)
    except Exception:
        # Redaction must not depend on the URL parsing, or a malformed URL leaks in the
        # error message that reports it as malformed.
        hidden = _blunt_redaction(url)
    return f"{hidden}{separator}{table}" if separator else hidden


def _blunt_redaction(url: str) -> str:
    scheme, separator, rest = url.partition("://")
    if not separator or "@" not in rest:
        return url
    credentials, _, host = rest.partition("@")
    user = credentials.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


def load_sql(source: str) -> pd.DataFrame:
    """Read one table into a dataframe.

    The whole table is read: the profile compares row counts and column statistics, and a
    partial read would describe the query rather than the dataset.
    """
    import pandas as pd

    url, table = split_source(source)
    engine = _engine(url, source)
    try:
        with engine.connect() as connection:
            return pd.read_sql_table(table, connection)
    except Exception as error:
        raise _read_error(error, table, source) from error
    finally:
        engine.dispose()


def _engine(url: str, source: str) -> Any:
    """Build an engine, turning the ways that fails into one sentence each."""
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.exc import ArgumentError, NoSuchModuleError
    except ImportError as error:  # pragma: no cover - exercised by the extra being absent
        raise _dataset_read_error(install_hint()) from error

    try:
        return create_engine(_normalised(url))
    except NoSuchModuleError as error:
        raise _dataset_read_error(
            f"no driver for '{redacted(source)}': {error}. {install_hint()}"
        ) from error
    except ModuleNotFoundError as error:
        raise _dataset_read_error(
            f"the driver for '{redacted(source)}' is not installed: {error}. {install_hint()}"
        ) from error
    except (ArgumentError, ValueError) as error:
        # A port that is not a number arrives as a bare ValueError from int(), which would
        # otherwise reach the caller as `invalid literal for int() with base 10`.
        raise SqlSourceError(
            f"could not read '{redacted(source)}' as a connection URL: {error}"
        ) from error


def _normalised(url: str) -> str:
    """Rewrite the two spellings people use that SQLAlchemy does not accept.

    `postgres://` lost its alias in SQLAlchemy 2.0 and now fails with "Can't load plugin",
    which says nothing about the scheme being the problem. A bare `mysql://` resolves to
    MySQLdb rather than the PyMySQL the sql extra installs, and fails with "No module named
    'MySQLdb'". Both are the URL every tutorial prints, so both are met where they are.

    A driver the caller spelled out is never rewritten.
    """
    scheme, separator, rest = url.partition("://")
    if not separator or "+" in scheme:
        return url
    lowered = scheme.lower()
    if lowered == "postgres":
        return f"postgresql://{rest}"
    if lowered in {"mysql", "mariadb"}:
        return f"{lowered}+pymysql://{rest}"
    return url


def _read_error(error: Exception, table: str, source: str) -> Exception:
    from sqlalchemy.exc import OperationalError

    where = redacted(source)
    if isinstance(error, ValueError) and "not found" in str(error).lower():
        return _dataset_read_error(f"no table named '{table}' in {where}")
    if isinstance(error, OperationalError):
        return _dataset_read_error(f"could not connect to {where}: {_first_line(error)}")
    return _dataset_read_error(f"could not read {where}: {_first_line(error)}")


def _first_line(error: Exception) -> str:
    """One line of a driver error, which otherwise arrives as a paragraph and a traceback."""
    return str(error).strip().splitlines()[0][:200]


def _dataset_read_error(message: str) -> Exception:
    from datasemver.formats.loader import DatasetReadError

    return DatasetReadError(message)
