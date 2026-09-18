"""Guards for the measured numbers, so they cannot go stale in silence.

The numbers the changelog publishes are measurements, and no test kept them honest: a change
that reintroduces a full read on the `--schema-only` path, or that materialises a stream the
bounded readers consume a chunk at a time, passes every functional test, and the numbers stop
matching what the code produces. So the invariants the timings come from are pinned here,
each as the kind of assertion it actually satisfies.

The footer invariant is exact, because it is binary: `--schema-only` promises not to read
rows. A spy stands on every entry point that decodes rows and fails the run the moment one
is touched, on every route that reaches the footer: the library's `load_schema`, which the
dashboard, the DVC run and the pull request script all go through, and both commands that
take the flag, `diff --schema-only` and `profile --schema-only`. Walking the footer's own
row-group statistics (`metadata.row_group(group).column(index)` in `formats/metadata.py`)
is reading metadata, not rows, and the spy leaves it alone.

The chunked invariant is a proportion, because its failure is one: the bounded upload
readers must never hold the whole body. The peak is taken over a generated file with the
ceiling stated as a multiple of the file's size on disk rather than an absolute number of
megabytes, so a runner whose constant overhead differs stays green while a reader that
swallowed the stream whole still turns red. The plain-upload copy path keeps the absolute
ceiling in `test_web.py`: a body large enough to test that proportionally cannot pass
through the test client without the client's own copy of the body being the allocation
measured.

What the numbers are measured on, so a future re-measurement is a rerun of the listed
commands:

- `--schema-only` (changelog 0.6.0: 5.4s and 641 MB against 1s and 137 MB): two Parquet
  files of about 60 MB (five million rows of an integer key, a number, a count, a region
  and a label), `datasemver diff old.parquet new.parquet --json` against the same command
  with `--schema-only`, wall clock and peak RSS of the whole process, interpreter and
  imports included. Checked 2026-09-18 on an Apple Silicon laptop, CPython 3.10: 5.8s and
  1.2 GB against 0.4s and 105 MB. The ratios, not the digits, are the claim; the footer
  test holds the part of the ratio that is exact.
- the chunked read (changelog 0.3.0: a pair of 60 MB files, 18.1s end to end against
  8.5s): the memory half of that story is what
  `test_refusing_an_expansion_never_holds_the_file` pins, on the upload path the dashboard
  actually serves.
"""

from __future__ import annotations

import gzip
import json
import tracemalloc

import pandas as pd
import pyarrow.parquet as pq
import pytest
from typer.testing import CliRunner

from datasemver.cli.main import app
from datasemver.formats.loader import load_schema

pytestmark = pytest.mark.perf

runner = CliRunner()

# The geometry of the generated bomb, and the ceiling as a multiple of the file's size on
# disk. The block repeats inside the deflate window, so the archive is a thousandth of its
# content: that ratio is what leaves room for the ceiling to sit -- above the honest cost,
# which the 1 MB read cap dominates and which measured 1.5 to 3.9 MB across runs, and far
# below a whole-body materialisation, which would peak at the decompressed size.
UPLOAD_LIMIT = 1 * 1024 * 1024
CEILING_MULTIPLE = 64
BOMB_BLOCK = b"".join(f"{index:04d},0123456789abcdef\n".encode() for index in range(80)) * 5
BOMB_BLOCKS = 8000

# Every entry point that decodes rows. The footer path may construct `ParquetFile` and read
# its `.metadata`; anything here is a full read by definition. The spy does not record and
# assert afterwards: it fails the run at the moment of touch, so no regression can slip
# through between two statements, and the error names the reader.
ROW_READERS = (
    (pq, "read_table"),
    (pq, "read_pandas"),
    (pq.ParquetFile, "read"),
    (pq.ParquetFile, "read_row_group"),
    (pq.ParquetFile, "iter_batches"),
    (pd, "read_parquet"),
)


@pytest.fixture
def forbid_row_reads(monkeypatch):
    """Replace every row-reading entry point with a failing stand-in."""
    touched = []

    def stand_in(owner, name):
        def reject(*args, **kwargs):
            touched.append(f"{owner}.{name}")
            raise AssertionError(f"the --schema-only path decoded rows via {owner}.{name}")

        return reject

    for owner, name in ROW_READERS:
        label = getattr(owner, "__name__", str(owner))
        monkeypatch.setattr(owner, name, stand_in(label, name))
    return touched


def _parquet_file(path, rows):
    """A small Parquet file carrying the column shapes the footer answers for."""
    pd.DataFrame(
        {
            "id": range(rows),
            "amount": [float(index) for index in range(rows)],
            "label": ["a", "b"] * (rows // 2),
        }
    ).to_parquet(path, index=False)
    return path


def test_load_schema_reads_the_footer_alone(tmp_path, forbid_row_reads):
    """Every profiling caller arrives through `load_schema`, so this guards them all at once."""
    path = _parquet_file(tmp_path / "data.parquet", rows=200)

    schema = load_schema(path, schema_only=True)

    assert schema.row_count == 200
    assert schema.columns["amount"].quantiles is None


def test_diff_schema_only_reads_the_footer_alone(tmp_path, forbid_row_reads):
    old = _parquet_file(tmp_path / "old.parquet", rows=200)
    new = _parquet_file(tmp_path / "new.parquet", rows=260)

    result = runner.invoke(
        app, ["diff", str(old), str(new), "--schema-only", "--json", "-c", "1.0.0"]
    )

    assert result.exit_code == 0
    assert json.loads(result.output)["diff"]["new"]["row_count"] == 260


def test_profile_schema_only_reads_the_footer_alone(tmp_path, forbid_row_reads):
    """The second route to the footer, opened when `profile` took the flag (#19)."""
    path = _parquet_file(tmp_path / "data.parquet", rows=200)
    stored = tmp_path / "data.profile.json"

    result = runner.invoke(app, ["profile", str(path), "--schema-only", "-o", str(stored)])

    assert result.exit_code == 0
    profile = json.loads(stored.read_text(encoding="utf-8"))
    assert profile["dataset"]["row_count"] == 200
    assert profile["dataset"]["schema_only"] is True


def test_refusing_an_expansion_never_holds_the_file(tmp_path, monkeypatch):
    """The refusal stays cheap at any file size: the peak is held under a multiple of the
    file's size on disk.

    The bomb arrives small enough to pass the copy limit and decompresses far past it, so
    the refusal happens in `_expands_past_limit`. The peak is held under a multiple of the
    file's size on disk: a reader that swallowed the stream whole would peak at the
    decompressed size, and the geometry asserted below keeps that an order of magnitude
    past the ceiling.
    """
    pytest.importorskip("fastapi")
    pytest.importorskip("httpx")

    from fastapi.testclient import TestClient

    from datasemver_web.backend.config import Settings
    from datasemver_web.backend.main import app as web_app

    settings = Settings(
        datasets_dir=tmp_path / "datasets",
        max_upload_bytes=UPLOAD_LIMIT,
        frontend_dir=tmp_path / "frontend",
    )
    monkeypatch.setattr("datasemver_web.backend.main.get_settings", lambda: settings)

    bomb = tmp_path / "bomb.csv.gz"
    with gzip.open(bomb, "wb") as stream:
        for _ in range(BOMB_BLOCKS):
            stream.write(BOMB_BLOCK)
    compressed = bomb.stat().st_size
    decompressed = len(BOMB_BLOCK) * BOMB_BLOCKS
    ceiling = CEILING_MULTIPLE * compressed
    # The geometry the catch depends on: small enough to pass the copy, and whole-body
    # materialisation an order of magnitude past the ceiling, or the assertion at the end
    # would pass for the wrong reason.
    assert compressed < UPLOAD_LIMIT
    assert decompressed > ceiling * 2

    with TestClient(web_app) as client:
        tracemalloc.start()
        with bomb.open("rb") as old, bomb.open("rb") as new:
            response = client.post(
                "/api/diff",
                files={
                    "old": (bomb.name, old, "text/csv"),
                    "new": (bomb.name, new, "text/csv"),
                },
            )
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()

    assert response.status_code == 413
    assert "once decompressed" in response.json()["detail"]
    assert peak < ceiling
