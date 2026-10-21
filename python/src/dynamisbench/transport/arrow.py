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

**Refusals are bounded.** Empty input, input above :data:`MAX_ARROW_IPC_BYTES`, a stream that
is not Arrow IPC, and a table larger than :data:`MAX_ARROW_ROWS` all raise
:class:`ArrowTransportError` with a closed reason. The underlying Arrow exception text is
never attached: it can quote bytes, offsets or a type name that this layer has no reason to
publish.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:  # pragma: no cover - typing only, and deliberately erased at runtime
    pass

ARROW_IPC_STREAM_CONTENT_TYPE: Final = "application/vnd.apache.arrow.stream"
"""The registered media type for an Arrow IPC stream. No endpoint publishes it in M2."""

MAX_ARROW_IPC_BYTES: Final = 1 * 1024 * 1024
"""The largest IPC stream this utility will read: one mebibyte.

The qualification payload is a few kilobytes. The bound is deliberately two orders of
magnitude above it, so it is a transport guard rather than a dataset limit.
"""

MAX_ARROW_ROWS: Final = 100_000
"""A structural ceiling on one decoded table, independent of its byte size."""

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
    MALFORMED = "malformed"
    TOO_MANY_ROWS = "too_many_rows"


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
    """Read one Arrow IPC stream, within the byte and row bounds.

    :raises ArrowTransportError: with a closed reason for empty, oversized, malformed or
        over-large input. The underlying Arrow exception is discarded.
    """
    if not payload:
        raise ArrowTransportError(ArrowFailure.EMPTY)
    if len(payload) > MAX_ARROW_IPC_BYTES:
        raise ArrowTransportError(ArrowFailure.TOO_LARGE)

    pa = _pyarrow()
    try:
        reader = pa.ipc.open_stream(payload)
        table = reader.read_all()
    except (pa.ArrowException, ValueError, TypeError, OSError):
        raise ArrowTransportError(ArrowFailure.MALFORMED) from None

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
    "MAX_ARROW_IPC_BYTES",
    "MAX_ARROW_ROWS",
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
