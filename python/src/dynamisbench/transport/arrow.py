"""Arrow IPC stream primitives, imported lazily and kept out of the startup path.

Apache Arrow is a transport format here, not a storage layer and not a scientific model. This
module can encode a small, fixed, in-memory table to an IPC stream and read one back; it
cannot append, persist, index or serve a dataset. The qualification payload below is
synthetic and exists to prove interoperability, not to be demo data.

**`pyarrow` is imported inside functions.** Importing ``dynamisbench``, ``dynamisbench.api``,
``dynamisbench.transport`` or this module itself must not load the columnar stack; only
calling :func:`encode_qualification_stream`, :func:`read_ipc_stream` or one of the small
schema helpers does. That is a measured property, not a comment: the API-startup import gate
and this module's own qualification both assert that ``pyarrow`` is absent from
``sys.modules`` after import.

**Refusals are bounded before materialization.** A pure-stdlib FlatBuffers preflight checks
message/metadata sizes, the supported flat-scalar schema, rows, columns, logical values,
buffers and declared decompressed sizes before PyArrow opens the stream. The matching browser
decoder uses the same resource profile. The frozen cross-language scalar fixture remains
unchanged. Compressed buffers are accepted only after their declared decoded sizes fit the
aggregate cap; PyArrow's available codec runs only after that preflight. The browser package
has no codec and keeps its existing closed refusal. Nested/dictionary/view schemas fail
closed until their decoded shape has an explicit budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from dynamisbench.transport.arrow_limits import (
    MAX_ARROW_BUFFERS,
    MAX_ARROW_COLUMNS,
    MAX_ARROW_DECODED_BYTES,
    MAX_ARROW_FIELD_DEPTH,
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
from dynamisbench.transport.arrow_preflight import ArrowPreflightError, preflight_ipc_stream

if TYPE_CHECKING:  # pragma: no cover - typing only, and deliberately erased at runtime
    pass

ARROW_IPC_STREAM_CONTENT_TYPE: Final = "application/vnd.apache.arrow.stream"
"""The registered media type for an Arrow IPC stream. No endpoint publishes it in M2."""

QUALIFICATION_FIELDS: Final[tuple[tuple[str, str, bool], ...]] = (
    ("sample_index", "int64", False),
    ("label", "string", False),
    ("measurement", "double", True),
    ("note", "string", True),
)
"""The frozen schema: name, Arrow type spelling, nullability, in this exact order."""

QUALIFICATION_ROWS: Final[tuple[tuple[int, str, float | None, str | None], ...]] = (
    (0, "baseline", 1.5, None),
    (1, "perturbed", 2.25, "first trial"),
    (2, "baseline", None, "not measured"),
    (3, "recovered", -0.5, None),
)
"""The frozen rows. Nulls are deliberate: two nullable columns, two kinds of null."""


class ArrowFailure(StrEnum):
    """The closed reasons an Arrow read can be refused."""

    EMPTY = "empty"
    TOO_LARGE = "too_large"
    TOO_LARGE_METADATA = "too_large_metadata"
    TOO_LARGE_DECODED = "too_large_decoded"
    MALFORMED = "malformed"
    UNSUPPORTED_SCHEMA = "unsupported_schema"
    UNSUPPORTED_COMPRESSION = "unsupported_compression"
    TOO_MANY_ROWS = "too_many_rows"
    TOO_MANY_COLUMNS = "too_many_columns"
    TOO_MANY_VALUES = "too_many_values"
    TOO_MANY_BATCHES = "too_many_batches"
    TOO_MANY_MESSAGES = "too_many_messages"
    TOO_MANY_METADATA_ENTRIES = "too_many_metadata_entries"


class ArrowTransportError(ValueError):
    """A bounded Arrow refusal: a closed reason and no underlying exception text."""

    def __init__(self, reason: ArrowFailure) -> None:
        super().__init__(f"the Arrow IPC payload was refused ({reason.value})")
        self.reason = reason


@dataclass(frozen=True, slots=True)
class ArrowField:
    """One field as a reader observes it, without a ``pyarrow`` type in the value."""

    name: str
    type: str
    nullable: bool


@dataclass(frozen=True, slots=True)
class ArrowTable:
    """A decoded table: schema, rows and count. Transport output, not authority."""

    fields: tuple[ArrowField, ...]
    rows: tuple[dict[str, object], ...]
    num_rows: int
    content_type: str = ARROW_IPC_STREAM_CONTENT_TYPE


def _pyarrow():
    """Import the optional columnar stack at call time.

    Kept as one function so the lazy boundary is visible and every entry point shares it.
    """
    import pyarrow as pa

    return pa


def _schema(pa):
    """The qualification schema, constructed only when ``pyarrow`` is present."""
    return pa.schema(
        [
            pa.field("sample_index", pa.int64(), nullable=False),
            pa.field("label", pa.string(), nullable=False),
            pa.field("measurement", pa.float64(), nullable=True),
            pa.field("note", pa.string(), nullable=True),
        ]
    )


def qualification_schema() -> tuple[ArrowField, ...]:
    """The frozen schema as portable field descriptions."""
    return tuple(
        ArrowField(name=name, type=arrow_type, nullable=nullable)
        for name, arrow_type, nullable in QUALIFICATION_FIELDS
    )


def qualification_rows() -> tuple[dict[str, object], ...]:
    """The frozen rows as dictionaries, in schema order."""
    names = [name for name, _, _ in QUALIFICATION_FIELDS]
    return tuple(dict(zip(names, row, strict=True)) for row in QUALIFICATION_ROWS)


def build_qualification_table():
    """The deterministic in-memory Arrow table. The caller owns the returned object."""
    pa = _pyarrow()
    return pa.Table.from_arrays(
        [
            pa.array([row[0] for row in QUALIFICATION_ROWS], type=pa.int64()),
            pa.array([row[1] for row in QUALIFICATION_ROWS], type=pa.string()),
            pa.array([row[2] for row in QUALIFICATION_ROWS], type=pa.float64()),
            pa.array([row[3] for row in QUALIFICATION_ROWS], type=pa.string()),
        ],
        schema=_schema(pa),
    )


def encode_qualification_stream() -> bytes:
    """Encode the frozen payload as one Arrow IPC stream.

    Deterministic: the fixed schema, fixed rows and stream format carry no clock, path or
    random identifier, so two calls produce identical bytes.
    """
    pa = _pyarrow()
    sink = pa.BufferOutputStream()
    table = build_qualification_table()
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)
    return sink.getvalue().to_pybytes()


def read_ipc_stream(payload: bytes) -> ArrowTable:
    """Read one supported Arrow IPC stream after preflighting all resource dimensions.

    :raises ArrowTransportError: with a closed reason for empty, oversized, malformed or
        unsupported input. The underlying Arrow exception is discarded. The checked profile
        preserves the cross-language fixture's flat scalar types and admits compressed
        buffers only when their declared output fits the decoded-byte cap. Nested, dictionary
        and view schemas require separately qualified budgets.
    """
    if not payload:
        raise ArrowTransportError(ArrowFailure.EMPTY)
    if len(payload) > MAX_ARROW_IPC_BYTES:
        raise ArrowTransportError(ArrowFailure.TOO_LARGE)

    try:
        budget = preflight_ipc_stream(payload)
    except ArrowPreflightError as error:
        raise ArrowTransportError(ArrowFailure(error.reason)) from None

    pa = _pyarrow()
    try:
        reader = pa.ipc.open_stream(payload)
        table = reader.read_all()
    except (pa.ArrowException, ValueError, TypeError, OSError):
        raise ArrowTransportError(ArrowFailure.MALFORMED) from None

    if table.num_rows != budget.row_count or table.num_columns != budget.column_count:
        raise ArrowTransportError(ArrowFailure.MALFORMED)
    if table.num_rows > MAX_ARROW_ROWS:
        raise ArrowTransportError(ArrowFailure.TOO_MANY_ROWS)

    fields = tuple(
        ArrowField(
            name=field.name,
            type=str(field.type),
            nullable=bool(field.nullable),
        )
        for field in table.schema
    )
    rows = tuple(dict(row) for row in table.to_pylist())
    return ArrowTable(
        fields=fields,
        rows=rows,
        num_rows=table.num_rows,
    )


def decode_qualification_stream(payload: bytes) -> ArrowTable:
    """Read a payload and assert it is exactly the frozen qualification contract.

    A qualification helper, not a general reader: it fails if a field, type, nullability,
    row count or value differs from the contract both languages share.
    """
    table = read_ipc_stream(payload)
    if table.fields != qualification_schema():
        raise ArrowTransportError(ArrowFailure.MALFORMED)
    if table.num_rows != len(QUALIFICATION_ROWS):
        raise ArrowTransportError(ArrowFailure.MALFORMED)
    if table.rows != qualification_rows():
        raise ArrowTransportError(ArrowFailure.MALFORMED)
    return table


__all__ = [
    "ARROW_IPC_STREAM_CONTENT_TYPE",
    "MAX_ARROW_BUFFERS",
    "MAX_ARROW_COLUMNS",
    "MAX_ARROW_DECODED_BYTES",
    "MAX_ARROW_FIELD_DEPTH",
    "MAX_ARROW_FIELD_NODES",
    "MAX_ARROW_IPC_BYTES",
    "MAX_ARROW_LOGICAL_VALUES",
    "MAX_ARROW_MESSAGE_METADATA_BYTES",
    "MAX_ARROW_MESSAGES",
    "MAX_ARROW_METADATA_ENTRIES",
    "MAX_ARROW_METADATA_STRING_BYTES",
    "MAX_ARROW_RECORD_BATCHES",
    "MAX_ARROW_ROWS",
    "MAX_ARROW_TOTAL_METADATA_BYTES",
    "QUALIFICATION_FIELDS",
    "QUALIFICATION_ROWS",
    "ArrowFailure",
    "ArrowField",
    "ArrowTable",
    "ArrowTransportError",
    "build_qualification_table",
    "decode_qualification_stream",
    "encode_qualification_stream",
    "qualification_rows",
    "qualification_schema",
    "read_ipc_stream",
]
