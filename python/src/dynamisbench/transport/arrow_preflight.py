"""Pure-Python Arrow IPC framing and allocation preflight.

This module reads only the bounded IPC envelope and FlatBuffers metadata. It never imports
PyArrow, builds an Arrow array, or expands values. ``read_ipc_stream`` must finish this pass
before invoking the official reader or converting the table to Python rows.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

from dynamisbench.transport.arrow_limits import (
    MAX_ARROW_BUFFERS,
    MAX_ARROW_COLUMNS,
    MAX_ARROW_DECODED_BYTES,
    MAX_ARROW_FIELD_DEPTH,
    MAX_ARROW_FIELD_NAME_BYTES,
    MAX_ARROW_FIELD_NODES,
    MAX_ARROW_IPC_BYTES,
    MAX_ARROW_LOGICAL_VALUES,
    MAX_ARROW_MESSAGE_METADATA_BYTES,
    MAX_ARROW_MESSAGES,
    MAX_ARROW_METADATA_ENTRIES,
    MAX_ARROW_METADATA_STRING_BYTES,
    MAX_ARROW_RECORD_BATCHES,
    MAX_ARROW_ROWS,
    MAX_ARROW_TOTAL_METADATA_BYTES,
)

_CONTINUATION = 0xFFFFFFFF
_MESSAGE_SCHEMA = 1
_MESSAGE_DICTIONARY_BATCH = 2
_MESSAGE_RECORD_BATCH = 3
_COMPRESSION_BUFFER = 0
_COMPRESSION_LZ4_FRAME = 0
_COMPRESSION_ZSTD = 1
_UNCOMPRESSED_BUFFER = -1


class ArrowPreflightError(ValueError):
    """A closed refusal reason; never includes offsets, bytes, or reader diagnostics."""

    def __init__(self, reason: str) -> None:
        super().__init__(f"the Arrow IPC payload was refused ({reason})")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ArrowPreflight:
    """Resource dimensions established from the stream metadata before materialization."""

    message_count: int
    record_batch_count: int
    row_count: int
    column_count: int
    field_node_count: int
    logical_value_count: int
    metadata_bytes: int
    encoded_body_bytes: int
    decoded_buffer_bytes: int


@dataclass(frozen=True, slots=True)
class _Table:
    position: int
    vtable: int
    vtable_size: int
    object_size: int


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    type_code: int
    value_width: int = 0
    offset_width: int = 0
    buffer_count: int = 0


@dataclass(frozen=True, slots=True)
class _BufferSpec:
    offset: int
    length: int
    decoded_length: int
    data_offset: int | None


class _FlatBuffer:
    """Minimal bounds-checked FlatBuffers reader for Arrow IPC metadata fields."""

    def __init__(self, data: memoryview) -> None:
        self.data = data
        self.size = len(data)

    def _range(self, position: int, size: int) -> None:
        if position < 0 or size < 0 or position > self.size or size > self.size - position:
            raise ArrowPreflightError("malformed")

    def u8(self, position: int) -> int:
        self._range(position, 1)
        return self.data[position]

    def i8(self, position: int) -> int:
        self._range(position, 1)
        return struct.unpack_from("<b", self.data, position)[0]

    def u16(self, position: int) -> int:
        self._range(position, 2)
        return struct.unpack_from("<H", self.data, position)[0]

    def u32(self, position: int) -> int:
        self._range(position, 4)
        return struct.unpack_from("<I", self.data, position)[0]

    def i32(self, position: int) -> int:
        self._range(position, 4)
        return struct.unpack_from("<i", self.data, position)[0]

    def i64(self, position: int) -> int:
        self._range(position, 8)
        return struct.unpack_from("<q", self.data, position)[0]

    def table(self, position: int) -> _Table:
        self._range(position, 4)
        vtable = position - self.i32(position)
        self._range(vtable, 4)
        vtable_size = self.u16(vtable)
        object_size = self.u16(vtable + 2)
        if vtable_size < 4 or vtable_size % 2 != 0 or object_size < 4:
            raise ArrowPreflightError("malformed")
        self._range(vtable, vtable_size)
        self._range(position, object_size)
        return _Table(position, vtable, vtable_size, object_size)

    def root_table(self) -> _Table:
        return self.table(self.u32(0))

    def field(self, table: _Table, index: int, size: int) -> int | None:
        slot = table.vtable + 4 + index * 2
        if slot + 2 > table.vtable + table.vtable_size:
            return None
        relative = self.u16(slot)
        if relative == 0:
            return None
        if relative + size > table.object_size:
            raise ArrowPreflightError("malformed")
        position = table.position + relative
        self._range(position, size)
        return position

    def scalar(self, table: _Table, index: int, fmt: str, default: int = 0) -> int:
        size = struct.calcsize(fmt)
        position = self.field(table, index, size)
        if position is None:
            return default
        self._range(position, size)
        return struct.unpack_from(fmt, self.data, position)[0]

    def offset(self, table: _Table, index: int) -> int | None:
        position = self.field(table, index, 4)
        if position is None:
            return None
        relative = self.u32(position)
        if relative == 0:
            raise ArrowPreflightError("malformed")
        target = position + relative
        self._range(target, 4)
        return target

    def table_field(self, table: _Table, index: int) -> _Table | None:
        position = self.offset(table, index)
        return None if position is None else self.table(position)

    def vector(
        self,
        table: _Table,
        index: int,
        item_size: int,
        maximum: int,
        refusal: str = "too_many_metadata_entries",
    ) -> tuple[int, int]:
        position = self.offset(table, index)
        if position is None:
            return 0, 0
        count = self.u32(position)
        if count > maximum:
            raise ArrowPreflightError(refusal)
        start = position + 4
        if item_size < 0 or count > (self.size - start) // max(item_size, 1):
            raise ArrowPreflightError("malformed")
        self._range(start, count * item_size)
        return start, count

    def vector_table(self, start: int, index: int) -> _Table:
        position = start + index * 4
        relative = self.u32(position)
        if relative == 0:
            raise ArrowPreflightError("malformed")
        return self.table(position + relative)

    def string(self, table: _Table, index: int, maximum: int) -> int:
        position = self.offset(table, index)
        if position is None:
            return 0
        length = self.u32(position)
        if length > maximum:
            raise ArrowPreflightError("too_large_metadata")
        start = position + 4
        self._range(start, length + 1)
        if self.u8(start + length) != 0:
            raise ArrowPreflightError("malformed")
        try:
            self.data[start : start + length].tobytes().decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise ArrowPreflightError("malformed") from None
        return length


def _metadata_entries(
    fb: _FlatBuffer,
    table: _Table,
    field_index: int,
    total: list[int],
) -> None:
    start, count = fb.vector(table, field_index, 4, MAX_ARROW_METADATA_ENTRIES)
    total[0] += count
    if total[0] > MAX_ARROW_METADATA_ENTRIES:
        raise ArrowPreflightError("too_many_metadata_entries")
    for index in range(count):
        entry = fb.vector_table(start, index)
        fb.string(entry, 0, MAX_ARROW_FIELD_NAME_BYTES)
        fb.string(entry, 1, MAX_ARROW_METADATA_STRING_BYTES)


def _type_spec(fb: _FlatBuffer, field: _Table, type_code: int) -> _FieldSpec:
    data_type = fb.table_field(field, 3)
    if data_type is None:
        raise ArrowPreflightError("malformed")

    if type_code == 1:  # Null
        return _FieldSpec(type_code, buffer_count=0)
    if type_code == 6:  # Bool (bit-packed values)
        return _FieldSpec(type_code, buffer_count=2)
    if type_code in (4, 5):  # Binary, Utf8 (32-bit offsets)
        return _FieldSpec(type_code, offset_width=4, buffer_count=3)
    if type_code in (19, 20):  # LargeBinary, LargeUtf8 (64-bit offsets)
        return _FieldSpec(type_code, offset_width=8, buffer_count=3)
    if type_code == 2:  # Int
        bit_width = fb.scalar(data_type, 0, "<i")
        signed = fb.scalar(data_type, 1, "<b")
        if bit_width not in (8, 16, 32, 64) or signed not in (0, 1):
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=bit_width // 8, buffer_count=2)
    if type_code == 3:  # FloatingPoint
        precision = fb.scalar(data_type, 0, "<h")
        widths = {0: 2, 1: 4, 2: 8}  # Half, Single, Double
        if precision not in widths:
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=widths[precision], buffer_count=2)
    if type_code == 7:  # Decimal
        precision = fb.scalar(data_type, 0, "<i")
        scale = fb.scalar(data_type, 1, "<i")
        bit_width = fb.scalar(data_type, 2, "<i", 128)
        if (
            precision < 1
            or precision > 76
            or abs(scale) > 76
            or bit_width not in (32, 64, 128, 256)
        ):
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=bit_width // 8, buffer_count=2)
    if type_code == 8:  # Date
        unit = fb.scalar(data_type, 0, "<h", 1)  # DateUnit.MILLISECOND
        if unit not in (0, 1):
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=4 if unit == 0 else 8, buffer_count=2)
    if type_code == 9:  # Time
        unit = fb.scalar(data_type, 0, "<h", 1)  # TimeUnit.MILLISECOND
        bit_width = fb.scalar(data_type, 1, "<i", 32)
        if unit not in (0, 1, 2, 3) or bit_width not in (32, 64):
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=bit_width // 8, buffer_count=2)
    if type_code == 10:  # Timestamp
        unit = fb.scalar(data_type, 0, "<h")
        if unit not in (0, 1, 2, 3):
            raise ArrowPreflightError("unsupported_schema")
        fb.string(data_type, 1, MAX_ARROW_METADATA_STRING_BYTES)
        return _FieldSpec(type_code, value_width=8, buffer_count=2)
    if type_code == 11:  # Interval
        unit = fb.scalar(data_type, 0, "<h")
        widths = {0: 4, 1: 8, 2: 16}
        if unit not in widths:
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=widths[unit], buffer_count=2)
    if type_code == 15:  # FixedSizeBinary
        width = fb.scalar(data_type, 0, "<i")
        if width < 1 or width > MAX_ARROW_DECODED_BYTES:
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=width, buffer_count=2)
    if type_code == 18:  # Duration
        unit = fb.scalar(data_type, 0, "<h", 1)  # TimeUnit.MILLISECOND
        if unit not in (0, 1, 2, 3):
            raise ArrowPreflightError("unsupported_schema")
        return _FieldSpec(type_code, value_width=8, buffer_count=2)
    # Nested, dictionary, union, view, and extension-backed arrays are not part of the current
    # application transport contract. Their decoded shape requires additional type-specific
    # budgets; refuse them until that contract is explicitly extended.
    raise ArrowPreflightError("unsupported_schema")


def _inspect_field(
    fb: _FlatBuffer,
    field: _Table,
    depth: int,
    counts: list[int],
    metadata_entries: list[int],
) -> _FieldSpec:
    if depth > MAX_ARROW_FIELD_DEPTH:
        raise ArrowPreflightError("too_many_columns")
    counts[0] += 1
    if counts[0] > MAX_ARROW_FIELD_NODES:
        raise ArrowPreflightError("too_many_columns")
    fb.string(field, 0, MAX_ARROW_FIELD_NAME_BYTES)
    _metadata_entries(fb, field, 6, metadata_entries)
    if fb.table_field(field, 4) is not None:
        raise ArrowPreflightError("unsupported_schema")
    _children_start, children_count = fb.vector(
        field, 5, 4, MAX_ARROW_FIELD_NODES, "too_many_columns"
    )
    if children_count:
        raise ArrowPreflightError("unsupported_schema")
    type_code = fb.scalar(field, 2, "<B")
    if type_code == 0:
        raise ArrowPreflightError("unsupported_schema")
    return _type_spec(fb, field, type_code)


def _inspect_schema(
    fb: _FlatBuffer,
    schema: _Table,
    metadata_entries: list[int],
) -> tuple[list[_FieldSpec], int]:
    endianness = fb.scalar(schema, 0, "<h")
    if endianness != 0:
        raise ArrowPreflightError("unsupported_schema")
    _metadata_entries(fb, schema, 2, metadata_entries)
    features_start, feature_count = fb.vector(schema, 3, 8, 64)
    for index in range(feature_count):
        feature = fb.i64(features_start + index * 8)
        if feature not in (1, 2):  # DICTIONARY_REPLACEMENT, COMPRESSED_BODY
            raise ArrowPreflightError("unsupported_schema")
    columns_start, columns = fb.vector(schema, 1, 4, MAX_ARROW_COLUMNS, "too_many_columns")
    field_nodes = [0]
    fields = [
        _inspect_field(
            fb,
            fb.vector_table(columns_start, index),
            1,
            field_nodes,
            metadata_entries,
        )
        for index in range(columns)
    ]
    return fields, field_nodes[0]


@dataclass(frozen=True, slots=True)
class _BatchStats:
    rows: int
    field_nodes: int
    logical_values: int
    decoded_bytes: int


def _inspect_batch(
    fb: _FlatBuffer,
    batch: _Table,
    body: memoryview,
    fields: list[_FieldSpec],
) -> _BatchStats:
    rows = fb.scalar(batch, 0, "<q")
    if rows < 0:
        raise ArrowPreflightError("malformed")
    if rows > MAX_ARROW_ROWS:
        raise ArrowPreflightError("too_many_rows")

    nodes_start, node_count = fb.vector(batch, 1, 16, MAX_ARROW_FIELD_NODES, "too_many_columns")
    if node_count != len(fields):
        raise ArrowPreflightError("malformed")
    logical_values = 0
    node_null_counts: list[int] = []
    for index in range(node_count):
        position = nodes_start + index * 16
        length = fb.i64(position)
        null_count = fb.i64(position + 8)
        if length != rows:
            raise ArrowPreflightError("malformed")
        if length < 0 or length > MAX_ARROW_LOGICAL_VALUES:
            raise ArrowPreflightError("too_many_values")
        if null_count < -1 or (null_count >= 0 and null_count > length):
            raise ArrowPreflightError("malformed")
        node_null_counts.append(null_count)
        logical_values += length
        if logical_values > MAX_ARROW_LOGICAL_VALUES:
            raise ArrowPreflightError("too_many_values")

    buffers_start, buffer_count = fb.vector(
        batch, 2, 16, MAX_ARROW_BUFFERS, "too_many_metadata_entries"
    )
    compression = fb.table_field(batch, 3)
    if compression is not None:
        codec = fb.scalar(compression, 0, "<b")
        method = fb.scalar(compression, 1, "<b")
        if method != 0 or codec not in (0, 1):
            raise ArrowPreflightError("malformed")

    variadic_start, variadic_count = fb.vector(
        batch, 4, 8, MAX_ARROW_FIELD_NODES, "too_many_columns"
    )
    variadic_total = 0
    for index in range(variadic_count):
        value = fb.i64(variadic_start + index * 8)
        if value < 0:
            raise ArrowPreflightError("malformed")
        variadic_total += value
        if variadic_total > MAX_ARROW_BUFFERS:
            raise ArrowPreflightError("too_many_metadata_entries")
    if variadic_total:
        raise ArrowPreflightError("unsupported_schema")

    expected_buffer_count = sum(field.buffer_count for field in fields)
    if buffer_count != expected_buffer_count:
        raise ArrowPreflightError("malformed")

    decoded_bytes = 0
    buffers: list[_BufferSpec] = []
    for index in range(buffer_count):
        position = buffers_start + index * 16
        offset = fb.i64(position)
        size = fb.i64(position + 8)
        if offset < 0 or size < 0 or offset > len(body) or size > len(body) - offset:
            raise ArrowPreflightError("malformed")
        if size == 0:
            decoded_size = 0
            data_offset: int | None = offset
        elif compression is None:
            decoded_size = size
            data_offset = offset
        else:
            if size < 8:
                raise ArrowPreflightError("malformed")
            uncompressed_size = struct.unpack_from("<q", body, offset)[0]
            if uncompressed_size == -1:
                decoded_size = size - 8
                data_offset = offset + 8
            elif uncompressed_size >= 0:
                decoded_size = uncompressed_size
                data_offset = None
            else:
                raise ArrowPreflightError("malformed")
        buffers.append(_BufferSpec(offset, size, decoded_size, data_offset))
        decoded_bytes += decoded_size
        if decoded_bytes > MAX_ARROW_DECODED_BYTES:
            raise ArrowPreflightError("too_large_decoded")
    cursor = 0
    for field, null_count in zip(fields, node_null_counts, strict=True):
        if field.type_code == 1:  # Null arrays have no buffers and no non-null values.
            if null_count not in (-1, rows):
                raise ArrowPreflightError("malformed")
            continue
        validity = buffers[cursor]
        cursor += 1
        bitmap_bytes = (rows + 7) // 8
        if validity.decoded_length and validity.decoded_length < bitmap_bytes:
            raise ArrowPreflightError("malformed")
        if null_count > 0 and validity.decoded_length < bitmap_bytes:
            raise ArrowPreflightError("malformed")

        if field.offset_width:
            offsets = buffers[cursor]
            values = buffers[cursor + 1]
            cursor += 2
            required_offsets = (rows + 1) * field.offset_width if rows else 0
            if offsets.decoded_length < required_offsets:
                raise ArrowPreflightError("malformed")
            if offsets.data_offset is not None and required_offsets:
                fmt = "<i" if field.offset_width == 4 else "<q"
                previous = struct.unpack_from(fmt, body, offsets.data_offset)[0]
                if previous != 0:
                    raise ArrowPreflightError("malformed")
                for row in range(1, rows + 1):
                    current = struct.unpack_from(
                        fmt, body, offsets.data_offset + row * field.offset_width
                    )[0]
                    if current < previous or current > values.decoded_length:
                        raise ArrowPreflightError("malformed")
                    previous = current
        else:
            values = buffers[cursor]
            cursor += 1
            minimum = (rows + 7) // 8 if field.type_code == 6 else rows * field.value_width
            if values.decoded_length < minimum:
                raise ArrowPreflightError("malformed")
    if cursor != len(buffers):
        raise ArrowPreflightError("malformed")
    return _BatchStats(rows, node_count, logical_values, decoded_bytes)


def preflight_ipc_stream(payload: bytes) -> ArrowPreflight:
    """Bound a stream's dimensions and decoded buffers without invoking PyArrow.

    The IPC message header and Arrow FlatBuffers vectors are inspected from the supplied bytes.
    All offsets and vector lengths are checked before iteration, so malformed metadata cannot
    create unbounded Python objects. The official reader is called only after this function
    returns.
    """
    if not payload:
        raise ArrowPreflightError("empty")
    if len(payload) > MAX_ARROW_IPC_BYTES:
        raise ArrowPreflightError("too_large")

    source = memoryview(payload)
    position = 0
    metadata_bytes = 0
    encoded_body_bytes = 0
    decoded_buffer_bytes = 0
    message_count = 0
    batch_count = 0
    row_count = 0
    logical_value_count = 0
    schema_fields: list[_FieldSpec] | None = None
    schema_field_nodes: int | None = None
    metadata_entries = [0]

    while position < len(source):
        if len(source) - position < 4:
            raise ArrowPreflightError("malformed")
        prefix = struct.unpack_from("<I", source, position)[0]
        position += 4
        if prefix == 0:
            if position != len(source):
                raise ArrowPreflightError("malformed")
            break
        if prefix == 0xFFFFFFFF:
            if len(source) - position < 4:
                raise ArrowPreflightError("malformed")
            metadata_length = struct.unpack_from("<I", source, position)[0]
            position += 4
            if metadata_length == 0:
                if position != len(source):
                    raise ArrowPreflightError("malformed")
                break
        else:
            metadata_length = prefix
        if metadata_length < 8:
            raise ArrowPreflightError("malformed")
        if metadata_length > len(source) - position:
            raise ArrowPreflightError("malformed")
        if metadata_length > MAX_ARROW_MESSAGE_METADATA_BYTES:
            raise ArrowPreflightError("too_large_metadata")
        metadata_bytes += metadata_length
        if metadata_bytes > MAX_ARROW_TOTAL_METADATA_BYTES:
            raise ArrowPreflightError("too_large_metadata")
        if message_count >= MAX_ARROW_MESSAGES:
            raise ArrowPreflightError("too_many_messages")
        message_count += 1

        metadata_start = position
        metadata_end = metadata_start + metadata_length
        fb = _FlatBuffer(source[metadata_start:metadata_end])
        message = fb.root_table()
        version = fb.scalar(message, 0, "<h")
        if version not in (0, 1, 2, 3, 4):
            raise ArrowPreflightError("unsupported_schema")
        message_type = fb.scalar(message, 1, "<B")
        body_length = fb.scalar(message, 3, "<q")
        if body_length < 0 or body_length % 8 != 0:
            raise ArrowPreflightError("malformed")
        header = fb.table_field(message, 2)
        if header is None:
            raise ArrowPreflightError("malformed")
        _metadata_entries(fb, message, 4, metadata_entries)
        position = metadata_end
        if body_length > len(source) - position:
            raise ArrowPreflightError("malformed")
        body_start = position
        body_end = body_start + body_length
        body = source[body_start:body_end]
        encoded_body_bytes += body_length
        if encoded_body_bytes > MAX_ARROW_IPC_BYTES:
            raise ArrowPreflightError("too_large")

        if message_type == _MESSAGE_SCHEMA:
            if schema_fields is not None or message_count != 1 or body_length != 0:
                raise ArrowPreflightError("malformed")
            schema_fields, schema_field_nodes = _inspect_schema(fb, header, metadata_entries)
        elif message_type == _MESSAGE_RECORD_BATCH:
            if schema_fields is None or schema_field_nodes is None:
                raise ArrowPreflightError("malformed")
            batch_count += 1
            if batch_count > MAX_ARROW_RECORD_BATCHES:
                raise ArrowPreflightError("too_many_batches")
            stats = _inspect_batch(fb, header, body, schema_fields)
            if stats.field_nodes != schema_field_nodes:
                raise ArrowPreflightError("malformed")
            row_count += stats.rows
            if row_count > MAX_ARROW_ROWS:
                raise ArrowPreflightError("too_many_rows")
            logical_value_count += stats.logical_values if schema_fields else stats.rows
            decoded_buffer_bytes += stats.decoded_bytes
        elif message_type == _MESSAGE_DICTIONARY_BATCH:
            # Dictionary value expansion needs an explicit index/value budget. It is not part
            # of the current scalar transport profile, so fail closed before materialization.
            raise ArrowPreflightError("unsupported_schema")
        else:
            raise ArrowPreflightError("unsupported_schema")

        if logical_value_count > MAX_ARROW_LOGICAL_VALUES:
            raise ArrowPreflightError("too_many_values")
        if decoded_buffer_bytes > MAX_ARROW_DECODED_BYTES:
            raise ArrowPreflightError("too_large_decoded")
        position = body_end

    if schema_fields is None or schema_field_nodes is None:
        raise ArrowPreflightError("malformed")
    return ArrowPreflight(
        message_count=message_count,
        record_batch_count=batch_count,
        row_count=row_count,
        column_count=len(schema_fields),
        field_node_count=schema_field_nodes,
        logical_value_count=logical_value_count,
        metadata_bytes=metadata_bytes,
        encoded_body_bytes=encoded_body_bytes,
        decoded_buffer_bytes=decoded_buffer_bytes,
    )


__all__ = ["ArrowPreflight", "ArrowPreflightError", "preflight_ipc_stream"]
