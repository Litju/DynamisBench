"""Deterministic bounded-input Arrow expansion fixtures for RES-566.

Both streams are valid IPC produced by PyArrow 26.0.0. The first has 25.6 million logical
null cells in a 15 KiB stream with no body buffers. The second compresses 8.64 MB of string
data to about 1 KiB. Neither fixture is fed to an unbounded materializer in this repository.
"""

from __future__ import annotations

import argparse
import base64
import struct
from pathlib import Path

import pyarrow as pa

from dynamisbench.transport.arrow_preflight import _FlatBuffer

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "apps" / "workbench" / "src" / "test" / "fixtures" / "arrow"


def expanded_null_cells(rows: int = 100_000, columns: int = 256) -> bytes:
    """A small valid stream at the row limit with excessive row × column work."""
    nulls = pa.nulls(rows)
    schema = pa.schema([pa.field(f"n{index:03d}", pa.null()) for index in range(columns)])
    table = pa.Table.from_arrays([nulls] * columns, schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def null_rows(rows: int = 100_001) -> bytes:
    """One primitive Null column above the preserved per-stream row limit."""
    schema = pa.schema([pa.field("n", pa.null())])
    table = pa.Table.from_arrays([pa.nulls(rows)], schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def nested_list_stream() -> bytes:
    """A valid nested list schema, outside the current flat-scalar transport profile."""
    schema = pa.schema([pa.field("items", pa.list_(pa.int64()))])
    table = pa.Table.from_arrays(
        [pa.array([[1, 2], None], type=schema.field(0).type)], schema=schema
    )
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def dictionary_stream() -> bytes:
    """A valid dictionary-encoded stream, outside the current transport profile."""
    dictionary = pa.array(["left", "right"], type=pa.string())
    indices = pa.array([0, 1, 0, 1], type=pa.int8())
    encoded = pa.DictionaryArray.from_arrays(indices, dictionary)
    schema = pa.schema([pa.field("side", encoded.type)])
    table = pa.Table.from_arrays([encoded], schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def small_compressed_stream() -> bytes:
    """A bounded compressed scalar stream used to preserve Python's read contract."""
    schema = pa.schema([pa.field("payload", pa.string())])
    table = pa.Table.from_arrays([pa.array(["small"] * 8)], schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(
        sink, schema, options=pa.ipc.IpcWriteOptions(compression="zstd")
    ) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def malformed_string_offsets_stream() -> bytes:
    """A tiny valid string stream with its final offset forged past the data buffer."""
    schema = pa.schema([pa.field("text", pa.string())])
    table = pa.Table.from_arrays([pa.array(["a", "b"], type=pa.string())], schema=schema)
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, schema) as writer:
        writer.write_table(table)
    payload = bytearray(sink.getvalue().to_pybytes())
    position = 0
    while position < len(payload):
        prefix = struct.unpack_from("<I", payload, position)[0]
        position += 4
        if prefix == 0xFFFF_FFFF:
            metadata_length = struct.unpack_from("<I", payload, position)[0]
            position += 4
        else:
            metadata_length = prefix
        metadata_start = position
        metadata_end = metadata_start + metadata_length
        fb = _FlatBuffer(memoryview(payload)[metadata_start:metadata_end])
        message = fb.root_table()
        message_type = fb.scalar(message, 1, "<B")
        body_length = fb.scalar(message, 3, "<q")
        if message_type == 3:
            batch = fb.table_field(message, 2)
            if batch is None:
                raise RuntimeError("fixture record batch has no metadata")
            buffers_start, _ = fb.vector(batch, 2, 16, 4_096)
            offsets_region = buffers_start + 16  # validity buffer, then UTF-8 offsets
            offsets = fb.i64(offsets_region)
            size = fb.i64(offsets_region + 8)
            if size < 12 or offsets + 12 > body_length:
                raise RuntimeError("fixture has an unexpected UTF-8 offset buffer")
            struct.pack_into("<i", payload, metadata_end + offsets + 8, 0x7FFF_FFFF)
            return bytes(payload)
        position = metadata_end + body_length
    raise RuntimeError("fixture has no record batch")


def compressed_buffer_expansion() -> bytes:
    """An 8.64 MB decoded string buffer compressed into a roughly 1 KiB IPC stream."""
    if not pa.Codec.is_available("zstd"):
        raise RuntimeError("the locked PyArrow build has no zstd codec")
    value = "Arrow allocation preflight " * 40_000
    values = [value] * 8
    schema = pa.schema([pa.field("payload", pa.string())])
    table = pa.Table.from_arrays([pa.array(values, type=pa.string())], schema=schema)
    sink = pa.BufferOutputStream()
    options = pa.ipc.IpcWriteOptions(compression="zstd")
    with pa.ipc.new_stream(sink, schema, options=options) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def _write(name: str, payload: bytes) -> None:
    FIXTURE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    encoded = base64.b64encode(payload).decode("ascii") + "\n"
    (FIXTURE_DIRECTORY / name).write_text(encoded, encoding="ascii", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="write the test fixtures")
    args = parser.parse_args()
    if not args.write:
        parser.error("pass --write to create the fixtures")
    fixtures = {
        "expanded-null-columns.arrow.b64": expanded_null_cells(),
        "compressed-buffer-expansion.arrow.b64": compressed_buffer_expansion(),
        "rows-over-limit.arrow.b64": null_rows(),
        "columns-over-limit.arrow.b64": expanded_null_cells(columns=257),
        "nested-list.arrow.b64": nested_list_stream(),
        "dictionary.arrow.b64": dictionary_stream(),
        "small-compressed.arrow.b64": small_compressed_stream(),
        "malformed-string-offsets.arrow.b64": malformed_string_offsets_stream(),
    }
    for name, payload in fixtures.items():
        _write(name, payload)


if __name__ == "__main__":
    main()
