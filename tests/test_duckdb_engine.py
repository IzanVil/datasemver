"""Tests for the DuckDB engine, whose whole promise is that it changes nothing but the cost.

A second way to compute a profile is only worth having if it answers the same question the
same way, so what is asserted here is agreement with the dataframe path, everywhere and to the
last float: the same types, null ratios, cardinalities, categories and quantile grids, and the
same bump from the same pair of files. Nothing is sketched, which is what makes the choice of
engine a question about what a run can afford rather than about what its answer means.

What the engine will not do is also pinned, because refusing is the alternative to answering
differently in silence: a format it cannot read, a nested column it cannot flatten and a
database URL are all errors naming themselves rather than a quiet fall back to the other path.
"""

from __future__ import annotations

import gzip
import json
import sys

import numpy
import pandas as pd
import pytest

pytest.importorskip("duckdb")

from typer.testing import CliRunner

from datasemver import analyze
from datasemver.cli.main import app
from datasemver.core.profile import DEFAULT_ENGINE, Profile, write_profile
from datasemver.formats.duck import (
    MEMORY_LIMIT_ENV_VAR,
    DuckDBError,
    _connect,
    is_duckdb_readable,
    profile_source,
)
from datasemver.formats.loader import (
    DELIMITER_ENV_VAR,
    Engine,
    UnsupportedFormatError,
    load_schema,
    resolve_engine,
)
from datasemver.utils.statistics import OTHER_CATEGORY

pytestmark = pytest.mark.duckdb

# Two engines adding the same numbers in a different order do not land on the same bits. The
# measured worst case over the fixtures is 2.2e-16, so this fails on an engine that computes
# something else and not on IEEE 754.
FLOAT_TOLERANCE = 1e-12

# What the sketched grid is allowed to be out by, as a fraction of the column's range. The
# measured worst case is 0.23% on 16M rows of lognormal data.
SKETCH_TOLERANCE = 0.02


def duck(path, engine: str = "duckdb") -> object:
    return load_schema(path, engine=engine)


@pytest.fixture
def lognormal(tmp_path):
    """Enough rows, skewed enough, for a sketched grid to be a sketch rather than the data."""
    rng = numpy.random.default_rng(11)
    path = tmp_path / "amounts.parquet"
    pd.DataFrame(
        {
            "amount": rng.lognormal(3.0, 1.1, 20_000),
            "country": rng.choice(["ES", "PT", "FR"], 20_000, p=[0.6, 0.25, 0.15]),
        }
    ).to_parquet(path)
    return path


# --- the promise ---------------------------------------------------------------------------


@pytest.mark.parametrize("fixture", ["csv", "parquet"])
@pytest.mark.parametrize("engine", ["duckdb", "duckdb-sketch"])
def test_the_engine_does_not_change_the_verdict(request, fixture, engine):
    """The point of the whole module: a cheaper profile that suggests the same bump.

    The sketch is held to this too. Its grid differs from the computed one, and a bump that
    moved with the engine would mean the difference had reached the answer -- which is the
    only thing anyone is deciding from.
    """
    old = request.getfixturevalue(f"old_{fixture}")
    new = request.getfixturevalue(f"new_{fixture}")

    with_pandas = analyze(old, new, current_version="1.4.2")
    with_duckdb = analyze(old, new, current_version="1.4.2", engine=engine)

    assert with_duckdb.bump == with_pandas.bump
    assert with_duckdb.next_version == with_pandas.next_version
    assert sorted(change.description for change in with_duckdb.diff.changes) == sorted(
        change.description for change in with_pandas.diff.changes
    )


@pytest.mark.parametrize("fixture", ["csv", "parquet"])
def test_every_column_is_profiled_the_same_way(request, fixture):
    """Exact means equal: the categorical half of a profile, compared field by field."""
    source = request.getfixturevalue(f"old_{fixture}")
    reference = load_schema(source)
    measured = duck(source)

    assert measured.row_count == reference.row_count
    assert measured.column_names == reference.column_names
    for name, expected in reference.columns.items():
        actual = measured.columns[name]
        assert (actual.dtype, actual.null_ratio) == (expected.dtype, expected.null_ratio), name
        assert actual.cardinality == expected.cardinality, name
        assert actual.categories == expected.categories, name
        assert actual.category_counts == expected.category_counts, name
        assert actual.mode == expected.mode, name


def test_the_numbers_agree_to_the_last_float(old_parquet):
    """The numeric half, including the quantile grid a distribution shift is measured from."""
    reference = load_schema(old_parquet)
    measured = duck(old_parquet)

    compared = 0
    for name, expected in reference.columns.items():
        actual = measured.columns[name]
        for field in ("mean", "std", "minimum", "maximum"):
            if getattr(expected, field) is None:
                continue
            assert getattr(actual, field) == pytest.approx(
                getattr(expected, field), rel=FLOAT_TOLERANCE
            ), f"{name}.{field}"
        if expected.quantiles:
            compared += 1
            assert actual.quantiles == pytest.approx(expected.quantiles, rel=FLOAT_TOLERANCE), name
    assert compared, "the fixture stopped having a numeric column to compare"


# --- the sketch, and what it does and does not cost -----------------------------------------


def test_the_sketch_stays_inside_the_error_it_claims(lognormal):
    """0.23% of the range at worst on 16M rows; this asserts an order of magnitude above it."""
    expected = load_schema(lognormal).columns["amount"].quantiles
    actual = duck(lognormal, "duckdb-sketch").columns["amount"].quantiles

    span = max(expected) - min(expected)
    worst = max(abs(a - b) for a, b in zip(actual, expected, strict=True)) / span

    assert worst <= SKETCH_TOLERANCE, f"{worst:.4%}"


def test_the_sketch_does_not_estimate_the_ends(lognormal):
    """`min` and `max` are exact aggregates already computed, and where a sketch is worst."""
    expected = load_schema(lognormal).columns["amount"]
    actual = duck(lognormal, "duckdb-sketch").columns["amount"]

    assert actual.quantiles[0] == expected.quantiles[0] == actual.minimum
    assert actual.quantiles[-1] == expected.quantiles[-1] == actual.maximum


def test_the_sketch_estimates_the_grid_and_nothing_else(lognormal):
    """Cardinality and category balance stay exact: a sketch of those invents changes."""
    expected = load_schema(lognormal)
    actual = duck(lognormal, "duckdb-sketch")

    for name, column in expected.columns.items():
        assert actual.columns[name].cardinality == column.cardinality, name
        assert actual.columns[name].category_counts == column.category_counts, name
        assert actual.columns[name].null_ratio == column.null_ratio, name
        assert actual.columns[name].mean == pytest.approx(column.mean, rel=FLOAT_TOLERANCE), name


# --- what it reads -------------------------------------------------------------------------


def test_a_compressed_csv_is_read(old_csv, tmp_path):
    compressed = tmp_path / "old.csv.gz"
    with gzip.open(compressed, "wb") as stream:
        stream.write(old_csv.read_bytes())

    assert duck(compressed).row_count == load_schema(old_csv).row_count


def test_the_delimiter_override_reaches_the_engine(tmp_path, monkeypatch):
    """The engine takes the delimiter the library resolved, not the one DuckDB would guess."""
    path = tmp_path / "sales.csv"
    path.write_text("id|city\n1|Madrid\n2|Sevilla\n", encoding="utf-8")
    monkeypatch.setenv(DELIMITER_ENV_VAR, "|")

    assert duck(path).column_names == ["id", "city"]


def test_a_tab_separated_file_is_read_as_one(tmp_path):
    path = tmp_path / "sales.tsv"
    path.write_text("id\tcity\n1\tMadrid\n2\tSevilla\n", encoding="utf-8")

    assert duck(path).column_names == ["id", "city"]


@pytest.mark.parametrize(
    ("source", "readable"),
    [
        ("data.parquet", True),
        ("data.pq", True),
        ("data.csv", True),
        ("DATA.CSV.GZ", True),
        ("data.tsv.gz", True),
        ("data.json", False),
        ("data.xlsx", False),
        ("data.feather", False),
    ],
)
def test_what_the_engine_claims_to_read(source, readable):
    assert is_duckdb_readable(source) is readable


def test_a_csv_without_a_resolved_delimiter_is_sniffed(old_csv):
    """The engine takes a delimiter when the library resolved one, and manages without."""
    sniffed = profile_source(old_csv, source=str(old_csv))

    assert sniffed.column_names == load_schema(old_csv).column_names


def test_a_column_of_only_nulls_is_profiled_like_one(tmp_path):
    path = tmp_path / "empty_column.parquet"
    pd.DataFrame({"id": [1, 2], "note": pd.Series([None, None], dtype="float64")}).to_parquet(path)

    note = duck(path).columns["note"]

    assert (note.null_ratio, note.cardinality) == (1.0, 0)
    assert note.mean is None and note.quantiles is None


def test_a_column_past_the_tracked_limit_keeps_its_tail_in_one_bucket(tmp_path):
    """More categories than are tracked individually, summed the way the other path sums."""
    path = tmp_path / "cities.parquet"
    cities = [f"city-{index:03d}" for index in range(260)]
    pd.DataFrame({"city": cities * 3}).to_parquet(path)

    expected = load_schema(path).columns["city"]
    actual = duck(path).columns["city"]

    assert OTHER_CATEGORY in actual.category_counts
    assert actual.category_counts == expected.category_counts
    assert actual.categories is expected.categories is None


# --- what it refuses, by name rather than in silence ----------------------------------------


def test_a_format_it_cannot_read_is_refused_rather_than_handed_over(old_json):
    """Falling back would make the same command answer two ways depending on the file."""
    with pytest.raises(UnsupportedFormatError, match="duckdb engine does not read"):
        duck(old_json)


def test_a_database_table_is_refused():
    with pytest.raises(UnsupportedFormatError, match="database table"):
        duck("postgresql://reader:secret@warehouse/analytics#customers")


def test_a_nested_column_is_refused_rather_than_profiled_differently(tmp_path):
    """The dataframe path flattens a struct into dotted columns; this engine does not yet."""
    path = tmp_path / "nested.parquet"
    pd.DataFrame({"id": [1, 2], "user": [{"name": "ana"}, {"name": "bruno"}]}).to_parquet(path)

    with pytest.raises(DuckDBError, match="does not flatten"):
        duck(path)


def test_a_key_cannot_be_combined_with_the_engine(old_csv, new_csv):
    """Matching rows needs the rows, and not loading them is the engine's whole point."""
    with pytest.raises(ValueError, match="duckdb engine never loads them"):
        analyze(old_csv, new_csv, key=["id"], engine="duckdb")


def test_the_connection_never_draws_on_the_output():
    """A progress bar is fine in a shell and fatal in a pipeline.

    DuckDB draws one on a query that takes a while, straight onto the terminal -- which on a
    dataset big enough to want this engine means a bar in the middle of `--json`. Asserted on
    the connection rather than on an output, because reproducing it needs a slow query and the
    setting is the guarantee.
    """
    connection = _connect()
    try:
        assert (
            connection.execute("SELECT current_setting('enable_progress_bar')").fetchone()[0]
            is False
        )
    finally:
        connection.close()


def test_without_the_extra_the_error_says_how_to_get_it(monkeypatch, old_parquet):
    """The engine is opt-in, so the first thing most people meet is its absence."""
    monkeypatch.setitem(sys.modules, "duckdb", None)

    with pytest.raises(DuckDBError, match="pip install"):
        duck(old_parquet)


def test_a_file_it_cannot_parse_is_reported_as_unreadable(tmp_path):
    path = tmp_path / "broken.parquet"
    path.write_bytes(b"this is not a parquet file")

    with pytest.raises(DuckDBError, match="could not read"):
        duck(path)


def test_a_memory_limit_duckdb_cannot_parse_is_reported_as_such(monkeypatch, old_parquet):
    monkeypatch.setenv(MEMORY_LIMIT_ENV_VAR, "as much as it takes")

    with pytest.raises(DuckDBError, match=MEMORY_LIMIT_ENV_VAR):
        duck(old_parquet)


def test_running_out_of_memory_says_which_ceiling_was_hit(monkeypatch, old_parquet):
    """The ceiling is the reason someone chose this engine, so hitting it names itself."""
    import duckdb as duckdb_module

    class OutOfMemory:
        """A connection that accepts its ceiling and then cannot work within it."""

        def execute(self, sql, *args, **kwargs):
            if sql.startswith("SET"):
                return self
            raise duckdb_module.OutOfMemoryException("no room")

        def close(self) -> None:
            pass

    monkeypatch.setenv(MEMORY_LIMIT_ENV_VAR, "1GB")
    monkeypatch.setattr(duckdb_module, "connect", lambda *a, **k: OutOfMemory())

    with pytest.raises(DuckDBError, match="ran out of memory"):
        duck(old_parquet)


# --- choosing it ----------------------------------------------------------------------------


def test_the_environment_chooses_the_engine(monkeypatch, old_json):
    """Set once, obeyed by every caller -- the dashboard and the DVC run take no option."""
    monkeypatch.setenv("DATASEMVER_ENGINE", "duckdb")

    assert resolve_engine(None) is Engine.DUCKDB
    with pytest.raises(UnsupportedFormatError, match="duckdb engine does not read"):
        load_schema(old_json)


def test_an_explicit_engine_wins_over_the_environment(monkeypatch, old_json):
    monkeypatch.setenv("DATASEMVER_ENGINE", "duckdb")

    assert resolve_engine("pandas") is Engine.PANDAS
    assert load_schema(old_json, engine="pandas").row_count


def test_an_unknown_engine_is_refused():
    with pytest.raises(UnsupportedFormatError, match="unknown engine"):
        resolve_engine("polars")


@pytest.mark.parametrize(
    ("name", "engine", "duckdb_backed"),
    [
        ("pandas", Engine.PANDAS, False),
        ("duckdb", Engine.DUCKDB, True),
        ("duckdb-sketch", Engine.DUCKDB_SKETCH, True),
    ],
)
def test_every_engine_is_reachable_by_name(name, engine, duckdb_backed):
    assert resolve_engine(name) is engine
    assert engine.is_duckdb is duckdb_backed


# --- through the command line ---------------------------------------------------------------


def test_the_command_line_records_the_engine_the_environment_chose(
    tmp_path, old_parquet, monkeypatch
):
    """The engine that ran is the one recorded, not the one that was typed.

    `--engine` and `DATASEMVER_ENGINE` choose equally, and a profile that claimed the dataframe
    path because the flag was absent would be a false record in the one file kept to be read
    back months later.
    """
    monkeypatch.setenv("DATASEMVER_ENGINE", "duckdb")
    destination = tmp_path / "customers.profile.json"

    result = CliRunner().invoke(app, ["profile", str(old_parquet), "-o", str(destination)])

    assert result.exit_code == 0
    assert Profile.model_validate_json(destination.read_text(encoding="utf-8")).engine == "duckdb"
    assert "duckdb" in result.output


def test_a_sketched_run_says_so_in_its_report(old_csv, new_csv):
    """The grid a distribution shift was measured from is part of reading the answer."""
    result = CliRunner().invoke(
        app, ["diff", str(old_csv), str(new_csv), "--engine", "duckdb-sketch"]
    )

    assert result.exit_code == 0
    assert "quantiles estimated" in " ".join(result.output.split())


def test_json_output_is_not_drawn_on(old_csv, new_csv):
    """Whatever the engine prints for itself must not reach a pipeline's stdout."""
    result = CliRunner().invoke(
        app, ["diff", str(old_csv), str(new_csv), "--engine", "duckdb", "--json"]
    )

    assert json.loads(result.output)["bump"] == "major"


# --- what a stored profile remembers --------------------------------------------------------


@pytest.mark.parametrize("engine", ["duckdb", "duckdb-sketch"])
def test_a_profile_records_the_engine_that_wrote_it(tmp_path, old_parquet, engine):
    """A profile outlives its dataset, so what computed it is part of what it says."""
    path = write_profile(
        duck(old_parquet, engine), tmp_path / "customers.profile.json", engine=engine
    )

    assert Profile.model_validate_json(path.read_text(encoding="utf-8")).engine == engine


def test_a_profile_that_says_nothing_came_from_the_dataframe_path(tmp_path, old_parquet):
    """Every profile written before the field existed did, so reading it so is a fact."""
    path = write_profile(load_schema(old_parquet), tmp_path / "customers.profile.json")

    assert Profile.model_validate_json(path.read_text(encoding="utf-8")).engine == DEFAULT_ENGINE
