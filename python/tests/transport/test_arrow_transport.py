"""Arrow IPC transport: deterministic bytes, a frozen contract, and a lazy dependency.

The golden fixture is one base64 text file read by both this suite and the JavaScript suite.
Python must reproduce it byte for byte, decode it with the official reader, and refuse
malformed or oversized input without importing the columnar stack merely by being imported.
"""

from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path

import pytest

from dynamisbench.transport.arrow import (
    ARROW_IPC_STREAM_CONTENT_TYPE,
    MAX_ARROW_IPC_BYTES,
    ArrowFailure,
    ArrowTransportError,
    decode_qualification_stream,
    encode_qualification_stream,
    qualification_rows,
    qualification_schema,
    read_ipc_stream,
)

FIXTURE = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "workbench"
    / "src"
    / "test"
    / "fixtures"
    / "qualification.arrow.b64"
)

_IMPORT_PROBE = "\n".join(
    [
        "import sys",
        "import dynamisbench",
        "import dynamisbench.api",
        "import dynamisbench.transport.arrow as arrow",
        "assert 'pyarrow' not in sys.modules",
        "encoded = arrow.encode_qualification_stream()",
        "assert 'pyarrow' in sys.modules",
        "print(len(encoded))",
    ]
)


def encoded_fixture() -> bytes:
    return base64.b64decode(FIXTURE.read_text(encoding="ascii").strip())


def test_the_encoder_reproduces_the_cross_language_golden_fixture() -> None:
    encoded = encode_qualification_stream()

    assert encoded == encoded_fixture()
    assert encode_qualification_stream() == encoded


def test_the_python_reader_decodes_the_frozen_schema_and_values() -> None:
    table = decode_qualification_stream(encoded_fixture())

    assert table.content_type == ARROW_IPC_STREAM_CONTENT_TYPE
    assert table.fields == qualification_schema()
    assert [(field.name, field.type, field.nullable) for field in table.fields] == [
        ("sample_index", "int64", False),
        ("label", "string", False),
        ("measurement", "double", True),
        ("note", "string", True),
    ]
    assert table.num_rows == 4
    assert table.rows == qualification_rows()
    assert table.rows[0]["measurement"] == 1.5
    assert table.rows[0]["note"] is None
    assert table.rows[2]["measurement"] is None
    assert table.rows[2]["note"] == "not measured"


def test_a_generic_reader_returns_the_same_table() -> None:
    table = read_ipc_stream(encoded_fixture())

    assert table.num_rows == 4
    assert table.rows[3]["label"] == "recovered"
    assert table.rows[3]["measurement"] == -0.5


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"", ArrowFailure.EMPTY),
        (b"not an arrow stream", ArrowFailure.MALFORMED),
        (b"\x00" * 64, ArrowFailure.MALFORMED),
        (b"x" * (MAX_ARROW_IPC_BYTES + 1), ArrowFailure.TOO_LARGE),
    ],
    ids=["empty", "text", "null-bytes", "oversize"],
)
def test_bounded_refusals_have_a_closed_reason(payload: bytes, reason: ArrowFailure) -> None:
    with pytest.raises(ArrowTransportError) as raised:
        read_ipc_stream(payload)

    assert raised.value.reason is reason
    assert reason.value in str(raised.value)
    assert "ArrowInvalid" not in str(raised.value)
    assert "Traceback" not in str(raised.value)


def test_the_qualification_helper_refuses_a_different_table() -> None:
    import pyarrow as pa

    sink = pa.BufferOutputStream()
    table = pa.table({"sample_index": [0], "label": ["other"]})
    with pa.ipc.new_stream(sink, table.schema) as writer:
        writer.write_table(table)

    with pytest.raises(ArrowTransportError) as raised:
        decode_qualification_stream(sink.getvalue().to_pybytes())

    assert raised.value.reason is ArrowFailure.MALFORMED


def test_importing_the_transport_does_not_load_pyarrow() -> None:
    result = subprocess.run(
        [sys.executable, "-c", _IMPORT_PROBE],
        capture_output=True,
        text=True,
        check=True,
    )

    assert result.stdout.strip() == str(len(encoded_fixture()))
    assert "pyarrow" not in result.stderr
