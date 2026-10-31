"""DB-3.3A create-if-absent publication, cache reuse and store verification."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import cast

import pytest

from dynamisbench.materialization import (
    MaterializationError,
    MaterializationRefusalCode,
    MaterializationStore,
    canonical_input_manifest_bytes,
)
from tests.materialization.conftest import ReferenceBundle


def _manifest_files(store: MaterializationStore) -> list[Path]:
    return sorted(path for path in (store.root / "manifests").glob("*.json"))


def test_second_materialization_reuses_objects_and_manifest(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    first = reference_bundle.materialize()
    asset = first.manifest.assets[0]
    object_path = materialization_store.object_path(asset.observed_sha256)
    before = object_path.read_bytes()

    second = reference_bundle.materialize()

    assert second.manifest_digest == first.manifest_digest
    assert second.manifest == first.manifest
    assert object_path.read_bytes() == before
    assert len(_manifest_files(materialization_store)) == 1


def test_concurrent_materializations_converge_on_one_manifest_and_object(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda _: reference_bundle.materialize(), range(8)))

    digests = {result.manifest_digest.hex for result in results}
    assert len(digests) == 1
    assert len(_manifest_files(materialization_store)) == 1
    asset = results[0].manifest.assets[0]
    assert materialization_store.object_path(asset.observed_sha256).is_file()


def test_existing_corrupt_object_is_refused_not_overwritten(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    first = reference_bundle.materialize()
    asset = first.manifest.assets[0]
    object_path = materialization_store.object_path(asset.observed_sha256)
    object_path.write_bytes(b"different bytes")

    with pytest.raises(MaterializationError) as caught:
        reference_bundle.materialize()

    assert caught.value.code is MaterializationRefusalCode.INPUT_OBJECT_CORRUPT
    assert object_path.read_bytes() == b"different bytes"


def test_interrupted_publication_leaves_no_manifest_and_is_retryable(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = MaterializationStore._publish_temporary

    def interrupted(*args: object, **kwargs: object) -> str:
        raise OSError("simulated interrupted publication")

    monkeypatch.setattr(MaterializationStore, "_publish_temporary", interrupted)
    with pytest.raises(OSError, match="interrupted"):
        reference_bundle.materialize()
    assert _manifest_files(materialization_store) == []

    monkeypatch.setattr(MaterializationStore, "_publish_temporary", original)
    result = reference_bundle.materialize()
    assert result.manifest_digest.hex in result.manifest_locator
    assert _manifest_files(materialization_store) == [
        materialization_store.manifest_path(result.manifest_digest.hex)
    ]


def test_read_manifest_rejects_noncanonical_rewrite(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    result = reference_bundle.materialize()
    path = materialization_store.manifest_path(result.manifest_digest.hex)
    value = json.loads(path.read_text(encoding="utf-8"))
    path.write_text(json.dumps(value, indent=2), encoding="utf-8")

    with pytest.raises(MaterializationError) as caught:
        materialization_store.read_manifest(result.manifest_digest)

    assert caught.value.code is MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="this host has no FIFO primitive")
def test_read_manifest_refuses_a_fifo(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    result = reference_bundle.materialize()
    path = materialization_store.manifest_path(result.manifest_digest.hex)
    path.unlink()
    mkfifo = cast(Callable[[str], None], os.mkfifo)  # type: ignore[attr-defined]
    mkfifo(str(path))
    try:
        with pytest.raises(MaterializationError) as caught:
            materialization_store.read_manifest(result.manifest_digest)
        assert caught.value.code is MaterializationRefusalCode.INPUT_OBJECT_CORRUPT
    finally:
        path.unlink()


def test_verify_manifest_refuses_a_missing_object(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    result = reference_bundle.materialize()
    asset = result.manifest.assets[0]
    materialization_store.object_path(asset.observed_sha256).unlink()

    with pytest.raises(MaterializationError) as caught:
        materialization_store.verify_manifest(result.manifest)

    assert caught.value.code is MaterializationRefusalCode.INPUT_OBJECT_MISSING


def test_publish_bytes_never_replaces_an_existing_final_name(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    payload = b"same bytes"
    digest = hashlib.sha256(payload).hexdigest()
    key = materialization_store.publish_bytes(
        payload,
        expected_sha256=digest,
        max_bytes=1024,
    )
    path = materialization_store.object_path(digest)
    assert key == f"sha256/{digest}"
    assert path.read_bytes() == payload

    path.write_bytes(b"corrupt")
    with pytest.raises(MaterializationError) as caught:
        materialization_store.publish_bytes(
            payload,
            expected_sha256=digest,
            max_bytes=1024,
        )
    assert caught.value.code is MaterializationRefusalCode.INPUT_OBJECT_CORRUPT
    assert path.read_bytes() == b"corrupt"


def test_manifest_bytes_are_the_only_manifest_identity(
    reference_bundle: ReferenceBundle,
) -> None:
    result = reference_bundle.materialize()
    first = canonical_input_manifest_bytes(result.manifest)
    second = canonical_input_manifest_bytes(result.manifest)
    assert first == second
    assert hashlib.sha256(first).hexdigest() == result.manifest_digest.hex


def test_read_manifest_refuses_omitted_declared_asset(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    from dynamisbench.materialization import InputManifest

    result = reference_bundle.materialize()
    value = result.manifest.model_dump(mode="json")
    value["assets"] = []
    incomplete = InputManifest.model_validate(value)
    digest, _ = materialization_store.publish_manifest(incomplete)
    with pytest.raises(MaterializationError) as caught:
        materialization_store.read_manifest(digest)
    assert caught.value.code is MaterializationRefusalCode.INPUT_MANIFEST_MISMATCH


def test_store_refuses_intermediate_objects_link(
    materialization_store: MaterializationStore,
    tmp_path: Path,
) -> None:
    import os
    import subprocess

    materialization_store.ensure_layout()
    objects = materialization_store.root / "objects"
    (objects / "sha256").rmdir()
    objects.rmdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    if os.name == "nt":
        subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(objects), str(outside)],
            check=True,
            capture_output=True,
        )
    else:
        objects.symlink_to(outside, target_is_directory=True)
    try:
        with pytest.raises(MaterializationError) as caught:
            materialization_store.ensure_layout()
        assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED
        assert list(outside.iterdir()) == []
    finally:
        if os.name == "nt":
            objects.rmdir()
        else:
            objects.unlink()
