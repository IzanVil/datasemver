"""How large an Arrow IPC file is once decoded, read from its metadata alone.

A Feather file is a sequence of messages, each a small description followed by a body. The
description says where every buffer sits in the body, and a compressed buffer begins with the
length it has once decompressed, so the decoded size of the whole file can be added up without
decompressing any of it. That matters because the unit pyarrow decodes is the record batch:
written as one batch, a file of a few hundred kilobytes is gigabytes of table before there is
anything to measure.

The description is a FlatBuffer. pyarrow hands it over as bytes and offers nothing that reads
it short of decoding the batch, so the few fields needed are read here, by the layout the
format fixes: a table starts with the offset back to its vtable, and the vtable lists where
each field is, or zero when it was left at its default.
"""

from __future__ import annotations

import struct
from pathlib import Path

MAGIC = b"ARROW1"
# The values of `MessageHeader`, the union a message's header is one of.
DICTIONARY_BATCH = 2
RECORD_BATCH = 3
# A compressed buffer starts with its decompressed length, and this in its place means the
# bytes after it were left as they were.
NOT_COMPRESSED = -1


class NotArrowFile(ValueError):
    """Raised when a file is not an Arrow IPC file this can measure."""


def decoded_size(path: Path, stop_after: int | None = None) -> int:
    """The bytes an Arrow IPC file holds once every buffer is decompressed.

    Stops adding as soon as the total passes `stop_after`, so the answer for a file that is
    too large costs no more than the answer for one that is not.
    """
    import pyarrow as pa
    import pyarrow.ipc as ipc

    total = 0
    with pa.memory_map(str(path), "r") as source:
        if source.read(len(MAGIC)) != MAGIC:
            raise NotArrowFile(f"{path.name} is not an Arrow IPC file")
        source.seek(8)  # the magic is padded to eight bytes
        reader = ipc.MessageReader.open_stream(source)
        while True:
            try:
                message = reader.read_next_message()
            except StopIteration:
                break
            if message is None:
                break
            total += _message_size(message.metadata.to_pybytes(), message.body)
            if stop_after is not None and total > stop_after:
                break
    return total


def _message_size(metadata: bytes, body: object) -> int:
    """The decoded size of the buffers one message carries; zero for a schema."""
    message = _Table(metadata, _u32(metadata, 0))
    kind = message.scalar(1, "<B", 0)
    if kind == RECORD_BATCH:
        batch = message.table(2)
    elif kind == DICTIONARY_BATCH:
        dictionary = message.table(2)
        batch = dictionary.table(1) if dictionary is not None else None
    else:
        return 0
    if batch is None:
        return 0

    compressed = batch.table(3) is not None
    view = memoryview(body)  # type: ignore[arg-type]
    total = 0
    for offset, length in batch.structs(2, "<qq"):
        if length < 0 or offset < 0 or offset + length > len(view):
            raise NotArrowFile("a buffer lies outside the body of its message")
        if not compressed or length < 8:
            total += length
            continue
        (declared,) = struct.unpack_from("<q", view, offset)
        total += length - 8 if declared == NOT_COMPRESSED else max(declared, 0)
    return total


class _Table:
    """One FlatBuffer table: enough to read a scalar, a nested table and a vector of structs."""

    def __init__(self, data: bytes, position: int) -> None:
        self.data = data
        self.position = position
        self.vtable = position - struct.unpack_from("<i", data, position)[0]
        self.vtable_size = struct.unpack_from("<H", data, self.vtable)[0]

    def _field(self, index: int) -> int | None:
        """Where field `index` is, or None when the table leaves it at its default."""
        slot = 4 + 2 * index
        if slot + 2 > self.vtable_size:
            return None
        offset = struct.unpack_from("<H", self.data, self.vtable + slot)[0]
        return self.position + offset if offset else None

    def scalar(self, index: int, layout: str, default: int) -> int:
        where = self._field(index)
        return default if where is None else int(struct.unpack_from(layout, self.data, where)[0])

    def table(self, index: int) -> _Table | None:
        where = self._field(index)
        return None if where is None else _Table(self.data, where + _u32(self.data, where))

    def structs(self, index: int, layout: str) -> list[tuple[int, ...]]:
        where = self._field(index)
        if where is None:
            return []
        start = where + _u32(self.data, where)
        count = _u32(self.data, start)
        size = struct.calcsize(layout)
        if start + 4 + count * size > len(self.data):
            raise NotArrowFile("a vector runs past the end of its message")
        return [struct.unpack_from(layout, self.data, start + 4 + i * size) for i in range(count)]


def _u32(data: bytes, position: int) -> int:
    return int(struct.unpack_from("<I", data, position)[0])
