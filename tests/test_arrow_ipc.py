"""The decoded size of an Arrow IPC file, read from its metadata instead of by decoding it."""

from __future__ import annotations

import pytest

pa = pytest.importorskip("pyarrow")
pytest.importorskip("fastapi", reason="the dashboard is not installed")

import pyarrow.ipc as ipc  # noqa: E402

from datasemver_web.backend.arrow_ipc import NotArrowFile, decoded_size  # noqa: E402

pytestmark = pytest.mark.web

ROWS = 20_000


def a_table():
    """One column of every shape the layout treats differently."""
    return pa.table(
        {
            "integers": pa.array(range(ROWS)),
            "floats": pa.array([index / 3 for index in range(ROWS)]),
            "strings": pa.array([f"name-{index % 97}" for index in range(ROWS)]),
            "nulls": pa.array(
                [None if index % 7 == 0 else index for index in range(ROWS)], type=pa.int32()
            ),
            "booleans": pa.array([index % 2 == 0 for index in range(ROWS)]),
            "dictionary": pa.array([f"c{index % 5}" for index in range(ROWS)]).dictionary_encode(),
            "lists": pa.array([[index, index + 1] for index in range(ROWS)]),
        }
    )


def written(path, table, compression, chunk=None):
    options = ipc.IpcWriteOptions(compression=compression)
    with ipc.new_file(path, table.schema, options=options) as writer:
        writer.write_table(table, max_chunksize=chunk)
    return path


def decoded_by_pyarrow(path):
    with ipc.open_file(path) as reader:
        return reader.read_all().get_total_buffer_size()


@pytest.mark.parametrize("compression", [None, "lz4", "zstd"])
@pytest.mark.parametrize("chunk", [None, 3_000])
def test_the_size_read_from_the_metadata_is_the_size_pyarrow_decodes(tmp_path, compression, chunk):
    path = written(tmp_path / "table.feather", a_table(), compression, chunk)

    assert decoded_size(path) == decoded_by_pyarrow(path)


def test_one_enormous_batch_is_measured_from_a_file_a_thousandth_its_size(tmp_path):
    """The case a batch at a time cannot see: there is only one batch, and it is the bomb."""
    rows = 8_000_000
    block = pa.record_batch([pa.array([0] * 1_000_000, type=pa.int64())], names=["value"])
    big = pa.Table.from_batches([block] * (rows // 1_000_000)).combine_chunks()
    path = written(tmp_path / "bomb.feather", big, "zstd")

    with ipc.open_file(path) as reader:
        assert reader.num_record_batches == 1
    assert path.stat().st_size < 64 * 1024
    assert decoded_size(path) >= rows * 8


def test_it_stops_adding_once_it_is_past_what_was_asked(tmp_path):
    path = written(tmp_path / "table.feather", a_table(), "zstd", chunk=1_000)

    whole = decoded_size(path)
    stopped = decoded_size(path, stop_after=whole // 10)

    assert whole // 10 < stopped < whole


def test_a_file_that_is_not_arrow_is_said_to_be_so(tmp_path):
    other = tmp_path / "not.feather"
    other.write_bytes(b"FEA1" + b"\0" * 64)

    with pytest.raises(NotArrowFile):
        decoded_size(other)


def test_a_buffer_that_claims_to_lie_outside_its_message_is_refused(tmp_path):
    from datasemver_web.backend import arrow_ipc

    path = written(tmp_path / "table.feather", a_table(), None)
    with pa.memory_map(str(path), "r") as source:
        source.seek(8)
        reader = ipc.MessageReader.open_stream(source)
        reader.read_next_message()  # the schema
        message = reader.read_next_message()
        metadata = message.metadata.to_pybytes()

    with pytest.raises(NotArrowFile):
        arrow_ipc._message_size(metadata, b"")
