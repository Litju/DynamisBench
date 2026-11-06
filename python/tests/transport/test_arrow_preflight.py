"""Pre-materialization Arrow IPC budgets and adversarial expansion coverage for RES-566."""

from __future__ import annotations

import base64
import struct
from pathlib import Path

import pytest
from tools.arrow_adversarial_fixtures import (
    compressed_buffer_expansion,
    dictionary_stream,
    expanded_null_cells,
    malformed_string_offsets_stream,
    nested_list_stream,
    null_rows,
    small_compressed_stream,
)

from dynamisbench.transport import arrow as arrow_module
from dynamisbench.transport import arrow_preflight
from dynamisbench.transport.arrow import (
    MAX_ARROW_DECODED_BYTES,
    MAX_ARROW_IPC_BYTES,
    MAX_ARROW_MESSAGE_METADATA_BYTES,
    MAX_ARROW_ROWS,
    ArrowFailure,
    ArrowTransportError,
    read_ipc_stream,
)
from dynamisbench.transport.arrow_preflight import preflight_ipc_stream

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
FIXTURE_DIRECTORY = REPOSITORY_ROOT / "apps" / "workbench" / "src" / "test" / "fixtures" / "arrow"


def _fixture(name: str) -> bytes:
    return base64.b64decode((FIXTURE_DIRECTORY / name).read_text(encoding="ascii").strip())


def _forbid_pyarrow() -> None:
    pytest.fail("hostile IPC reached PyArrow before preflight refusal")


def test_the_checked_in_expansion_fixtures_are_reproducible() -> None:
    assert expanded_null_cells() == _fixture("expanded-null-columns.arrow.b64")
    assert compressed_buffer_expansion() == _fixture("compressed-buffer-expansion.arrow.b64")
    assert null_rows() == _fixture("rows-over-limit.arrow.b64")
    assert expanded_null_cells(columns=257) == _fixture("columns-over-limit.arrow.b64")
    assert nested_list_stream() == _fixture("nested-list.arrow.b64")
    assert dictionary_stream() == _fixture("dictionary.arrow.b64")
    assert small_compressed_stream() == _fixture("small-compressed.arrow.b64")
    assert malformed_string_offsets_stream() == _fixture("malformed-string-offsets.arrow.b64")


def test_frozen_qualification_fixture_passes_with_the_same_dimensions() -> None:
    encoded = arrow_module.encode_qualification_stream()
    assert len(encoded) == 832
    report = preflight_ipc_stream(encoded)
    assert (report.row_count, report.column_count, report.logical_value_count) == (4, 4, 16)
    assert read_ipc_stream(encoded).rows == arrow_module.qualification_rows()


def test_small_valid_stream_with_25m_null_cells_is_refused_before_pyarrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture("expanded-null-columns.arrow.b64")
    assert len(payload) < 64 * 1024 < MAX_ARROW_IPC_BYTES
    assert MAX_ARROW_ROWS == 100_000
    monkeypatch.setattr(arrow_module, "_pyarrow", _forbid_pyarrow)

    with pytest.raises(ArrowTransportError) as raised:
        read_ipc_stream(payload)

    assert raised.value.reason is ArrowFailure.TOO_MANY_VALUES


def test_compressed_buffer_over_8mib_is_refused_before_pyarrow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture("compressed-buffer-expansion.arrow.b64")
    assert len(payload) < 4 * 1024
    monkeypatch.setattr(arrow_module, "_pyarrow", _forbid_pyarrow)

    with pytest.raises(ArrowTransportError) as raised:
        read_ipc_stream(payload)

    assert raised.value.reason is ArrowFailure.TOO_LARGE_DECODED


def test_bounded_compressed_stream_remains_readable_after_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _fixture("small-compressed.arrow.b64")
    preflights = []
    original_preflight = arrow_module.preflight_ipc_stream
    original_pyarrow = arrow_module._pyarrow

    def record_preflight(data: bytes):
        report = original_preflight(data)
        preflights.append(report)
        return report

    def require_bounded_preflight():
        assert len(preflights) == 1
        assert preflights[0].decoded_buffer_bytes <= MAX_ARROW_DECODED_BYTES
        return original_pyarrow()

    monkeypatch.setattr(arrow_module, "preflight_ipc_stream", record_preflight)
    monkeypatch.setattr(arrow_module, "_pyarrow", require_bounded_preflight)

    table = read_ipc_stream(payload)

    assert table.num_rows == 8
    assert table.fields[0].name == "payload"
    assert table.rows == tuple({"payload": "small"} for _ in range(8))
    assert len(preflights) == 1


@pytest.mark.parametrize(
    ("fixture_name", "reason"),
    [
        ("rows-over-limit.arrow.b64", ArrowFailure.TOO_MANY_ROWS),
        ("columns-over-limit.arrow.b64", ArrowFailure.TOO_MANY_COLUMNS),
        ("nested-list.arrow.b64", ArrowFailure.UNSUPPORTED_SCHEMA),
        ("dictionary.arrow.b64", ArrowFailure.UNSUPPORTED_SCHEMA),
        ("malformed-string-offsets.arrow.b64", ArrowFailure.MALFORMED),
    ],
    ids=[
        "rows",
        "columns",
        "nested",
        "dictionary",
        "string-offset-out-of-bounds",
    ],
)
def test_dimension_and_unsupported_profiles_fail_before_pyarrow(
    monkeypatch: pytest.MonkeyPatch,
    fixture_name: str,
    reason: ArrowFailure,
) -> None:
    monkeypatch.setattr(arrow_module, "_pyarrow", _forbid_pyarrow)
    with pytest.raises(ArrowTransportError) as raised:
        read_ipc_stream(_fixture(fixture_name))
    assert raised.value.reason is reason


def test_metadata_length_above_budget_fails_before_flatbuffer_parse() -> None:
    metadata_length = MAX_ARROW_MESSAGE_METADATA_BYTES + 1
    payload = b"\xff\xff\xff\xff" + struct.pack("<I", metadata_length) + b"\x00" * metadata_length
    assert len(payload) < MAX_ARROW_IPC_BYTES
    with pytest.raises(ArrowTransportError) as raised:
        read_ipc_stream(payload)
    assert raised.value.reason is ArrowFailure.TOO_LARGE_METADATA


def test_forged_schema_vector_count_fails_before_reader_materialization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = bytearray(_fixture("expanded-null-columns.arrow.b64"))
    metadata_length = struct.unpack_from("<I", payload, 4)[0]
    metadata_start = 8
    fb = arrow_preflight._FlatBuffer(
        memoryview(payload)[metadata_start : metadata_start + metadata_length]
    )
    message = fb.root_table()
    schema = fb.table_field(message, 2)
    assert schema is not None
    fields_start, fields_count = fb.vector(schema, 1, 4, 256)
    assert fields_count == 256
    # Forge the vector length while leaving its bounded bytes unchanged. The preflight must
    # reject the declared dimension before iterating it or invoking PyArrow.
    struct.pack_into("<I", payload, metadata_start + fields_start - 4, 0xFFFF_FFFF)
    monkeypatch.setattr(arrow_module, "_pyarrow", _forbid_pyarrow)

    with pytest.raises(ArrowTransportError) as raised:
        read_ipc_stream(bytes(payload))

    assert raised.value.reason is ArrowFailure.TOO_MANY_COLUMNS
