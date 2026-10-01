"""Typed SHA-256 identity values and raw-byte asset identity (ADR-006).

The published SHA-256 test vectors come from NIST FIPS 180-2 / the NIST ``SHA256``
example values, not from DynamisBench, so the hash itself is pinned independently of
anything in this repository.

What is proved here:

* a digest carries its algorithm explicitly and is always a lowercase 256-bit SHA-256;
* malformed digest text is rejected rather than coerced;
* a :class:`SemanticDigest` and an :class:`AssetDigest` are not interchangeable;
* raw-byte identity depends on content alone: same bytes give the same digest from any
  path, one changed byte changes the digest, and an empty asset is a valid asset;
* reading an asset is bounded in memory and never loads the file whole;
* a missing or unreadable asset raises an access error that is not a digest mismatch.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest

from dynamisbench.identity import (
    READ_CHUNK_BYTES,
    AssetAccessError,
    AssetDigest,
    DigestAlgorithm,
    SemanticDigest,
    asset_sha256,
    asset_sha256_of_file,
    asset_sha256_of_stream,
    semantic_sha256_of_canonical_bytes,
)

# NIST FIPS 180-2 SHA-256 examples.
SHA256_OF_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SHA256_OF_ABC = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

DIGEST_TYPES = (SemanticDigest, AssetDigest)

MALFORMED_HEX = (
    "",
    "0" * 63,
    "0" * 65,
    "0" * 63 + "g",
    "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855",
    " " + "0" * 64,
    "0" * 64 + "\n",
    "sha256:" + "0" * 64,
)


class _RecordingReader:
    """A byte source that records the size of every read it is asked for."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self._offset = 0
        self.requested: list[int] = []

    def read(self, size: int = READ_CHUNK_BYTES, /) -> bytes:
        self.requested.append(size)
        chunk = self._payload[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def test_the_hash_is_sha256_and_pins_the_nublished_vectors() -> None:
    assert asset_sha256(b"").hex == SHA256_OF_EMPTY
    assert asset_sha256(b"abc").hex == SHA256_OF_ABC
    assert semantic_sha256_of_canonical_bytes(b"").hex == SHA256_OF_EMPTY


@pytest.mark.parametrize("digest_type", DIGEST_TYPES, ids=lambda kind: kind.__name__)
def test_a_digest_states_its_algorithm_and_is_exactly_256_bits(digest_type: Any) -> None:
    digest = digest_type(hex="0" * 64)
    assert digest.algorithm is DigestAlgorithm.SHA256
    assert digest.algorithm == "sha256"
    assert len(digest.hex) == 64
    assert digest.hex == digest.hex.lower()
    assert digest.model_dump() == {"algorithm": "sha256", "hex": "0" * 64}
    assert digest.model_dump_json() == '{"algorithm":"sha256","hex":"%s"}' % ("0" * 64)


@pytest.mark.parametrize("digest_type", DIGEST_TYPES, ids=lambda kind: kind.__name__)
@pytest.mark.parametrize("malformed", MALFORMED_HEX, ids=range(len(MALFORMED_HEX)))
def test_a_digest_rejects_malformed_text(digest_type: Any, malformed: str) -> None:
    with pytest.raises(ValueError):
        digest_type(hex=malformed)


@pytest.mark.parametrize("digest_type", DIGEST_TYPES, ids=lambda kind: kind.__name__)
def test_a_digest_is_immutable_and_hashable(digest_type: Any) -> None:
    digest = digest_type(hex=SHA256_OF_ABC)
    with pytest.raises(ValueError):
        digest.hex = SHA256_OF_EMPTY
    assert {digest, digest_type(hex=SHA256_OF_ABC)} == {digest}


@pytest.mark.parametrize("digest_type", DIGEST_TYPES, ids=lambda kind: kind.__name__)
def test_a_digest_refuses_an_undeclared_field(digest_type: Any) -> None:
    with pytest.raises(ValueError):
        digest_type(hex="0" * 64, algorithm="sha512")


def test_a_semantic_digest_and_an_asset_digest_are_not_interchangeable() -> None:
    assert not isinstance(SemanticDigest(hex="0" * 64), AssetDigest)
    assert not isinstance(AssetDigest(hex="0" * 64), SemanticDigest)
    with pytest.raises(ValueError):
        AssetDigest.model_validate(SemanticDigest(hex="0" * 64))
    with pytest.raises(ValueError):
        SemanticDigest.model_validate(AssetDigest(hex="0" * 64))
    assert type(SemanticDigest(hex="0" * 64)) is not type(AssetDigest(hex="0" * 64))


def test_a_digest_value_is_not_a_hex_string_and_is_not_accepted_as_one() -> None:
    """A raw string is not a digest. An untyped call site must construct the value, so
    the kind of identity being claimed is always named."""
    with pytest.raises(ValueError):
        SemanticDigest.model_validate({"hex": AssetDigest(hex="0" * 64)})
    with pytest.raises(ValueError):
        AssetDigest.model_validate({"hex": SemanticDigest(hex="0" * 64)})
    assert AssetDigest(hex=SemanticDigest(hex="0" * 64).hex).hex == "0" * 64


def test_an_empty_asset_is_a_valid_and_deterministic_asset(tmp_path: Path) -> None:
    path = tmp_path / "empty.parquet"
    path.write_bytes(b"")
    assert asset_sha256_of_file(path).hex == SHA256_OF_EMPTY
    assert asset_sha256_of_file(path) == asset_sha256(b"")
    assert path.stat().st_size == 0


def test_identical_bytes_give_one_asset_digest_whatever_the_path(tmp_path: Path) -> None:
    payload = b"<mujoco model>\n  <worldbody/>\n</mujoco>\n"
    first = tmp_path / "models" / "subject.xml"
    second = tmp_path / "cache" / "copied-subject.xml"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(payload)
    second.write_bytes(payload)
    assert asset_sha256_of_file(first) == asset_sha256_of_file(second)
    assert asset_sha256_of_file(first) == asset_sha256(payload)


def test_one_changed_byte_changes_the_asset_digest(tmp_path: Path) -> None:
    original = tmp_path / "subject.xml"
    original.write_bytes(b"<worldbody/>")
    before = asset_sha256_of_file(original)
    original.write_bytes(b"<worldbody >")
    after = asset_sha256_of_file(original)
    assert before != after


def test_an_asset_is_streamed_in_bounded_chunks_and_never_loaded_whole() -> None:
    payload = b"x" * (READ_CHUNK_BYTES * 2 + 17)
    reader = _RecordingReader(payload)
    digest = asset_sha256_of_stream(reader)
    assert digest == asset_sha256(payload)
    assert reader.requested == [READ_CHUNK_BYTES] * 4


def test_an_exhausted_source_is_read_one_more_time_to_prove_the_stream_ended() -> None:
    """A source that returned a full chunk could still hold more bytes, so the loop has
    to keep going until a read comes back short or empty."""
    reader = _RecordingReader(b"x" * READ_CHUNK_BYTES)
    asset_sha256_of_stream(reader)
    assert reader.requested == [READ_CHUNK_BYTES, READ_CHUNK_BYTES]


def test_a_multi_chunk_asset_digests_to_the_same_value_as_the_whole_content(
    tmp_path: Path,
) -> None:
    payload = bytes(index % 251 for index in range(READ_CHUNK_BYTES + 4096))
    path = tmp_path / "trajectory.parquet"
    path.write_bytes(payload)
    assert asset_sha256_of_file(path) == asset_sha256(payload)
    assert asset_sha256_of_file(path).hex == hashlib.sha256(payload).hexdigest()


def test_a_missing_asset_reports_an_access_failure_rather_than_a_digest(tmp_path: Path) -> None:
    with pytest.raises(AssetAccessError) as excinfo:
        asset_sha256_of_file(tmp_path / "absent.xml")
    assert "absent.xml" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, OSError)


def test_a_directory_is_an_access_failure_and_not_a_digest(tmp_path: Path) -> None:
    directory = tmp_path / "models"
    directory.mkdir()
    with pytest.raises(AssetAccessError):
        asset_sha256_of_file(directory)


def test_an_access_failure_is_distinguishable_from_a_digest_validation_failure() -> None:
    """There is no digest to compare when the bytes were never read. Being unable to
    read an asset and finding that an asset is not the declared one are different
    claims, so the access failure is not a ``ValueError`` like a malformed digest is."""
    assert not issubclass(AssetAccessError, ValueError)
    assert issubclass(AssetAccessError, RuntimeError)
    assert AssetAccessError is not type(AssetDigest(hex="0" * 64))


def test_the_two_digest_kinds_are_produced_by_different_kinds_of_bytes() -> None:
    """The same bytes fed to the two entry points yield equal hex but different types,
    because the claim being made about them is different."""
    raw = b'{"a":1}'
    assert asset_sha256(raw).hex == semantic_sha256_of_canonical_bytes(raw).hex
    assert type(asset_sha256(raw)) is AssetDigest
    assert type(semantic_sha256_of_canonical_bytes(raw)) is SemanticDigest
