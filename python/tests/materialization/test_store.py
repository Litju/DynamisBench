"""DB-3.3A create-if-absent publication, cache reuse and store verification."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, cast

import pytest

from dynamisbench.materialization import (
    MaterializationError,
    MaterializationRefusalCode,
    MaterializationStore,
    canonical_input_manifest_bytes,
)
from dynamisbench.materialization.schema import MAX_DEFINITION_BYTES
from tests.materialization.conftest import ReferenceBundle
from tests.workspace.links import make_directory_link, require_directory_link


def _publish_worker(
    source_root: str,
    evidence_root: str,
    payload: bytes,
    digest: str,
    barrier: Any,
    results: Any,
) -> None:
    """Cross-process publisher used by the quarantine interleaving regression."""
    from dynamisbench.materialization import MaterializationStore
    from dynamisbench.workspace import open_workspace

    store = MaterializationStore(open_workspace(source_root, evidence_root))
    barrier.wait(timeout=30)
    try:
        key = store.publish_bytes(payload, expected_sha256=digest, max_bytes=1024)
        results.put(("ok", key))
    except MaterializationError as error:
        results.put(("refused", error.code.value))
    except BaseException as error:  # noqa: BLE001 - the child reports any unexpected failure
        results.put(("error", repr(error)))


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
    assert not object_path.exists()
    quarantined = list(
        (materialization_store.root / "quarantine").glob(f"{asset.observed_sha256}.*")
    )
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"different bytes"

    retried = reference_bundle.materialize()
    assert retried.manifest_digest == first.manifest_digest
    assert object_path.is_file()


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
    assert not path.exists()
    quarantined = list((materialization_store.root / "quarantine").glob(f"{digest}.*"))
    assert len(quarantined) == 1
    assert quarantined[0].read_bytes() == b"corrupt"

    repeated = materialization_store.publish_bytes(
        payload,
        expected_sha256=digest,
        max_bytes=1024,
    )
    assert repeated == key
    assert path.read_bytes() == payload


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


def test_verify_manifest_refuses_objects_directory_link(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
    tmp_path: Path,
) -> None:
    result = reference_bundle.materialize()
    objects = materialization_store.root / "objects"
    moved = tmp_path / "real-objects"
    shutil.move(str(objects), str(moved))
    mechanism = make_directory_link(objects, moved)
    require_directory_link(mechanism, "a linked objects directory is refused on read")

    try:
        with pytest.raises(MaterializationError) as caught:
            materialization_store.verify_manifest(result.manifest)
        assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED
    finally:
        if os.name == "nt":
            objects.rmdir()
        else:
            objects.unlink()


def test_read_manifest_refuses_manifests_directory_link(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
    tmp_path: Path,
) -> None:
    result = reference_bundle.materialize()
    manifests = materialization_store.root / "manifests"
    moved = tmp_path / "real-manifests"
    shutil.move(str(manifests), str(moved))
    mechanism = make_directory_link(manifests, moved)
    require_directory_link(mechanism, "a linked manifests directory is refused on read")

    try:
        with pytest.raises(MaterializationError) as caught:
            materialization_store.read_manifest(result.manifest_digest)
        assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED
    finally:
        if os.name == "nt":
            manifests.rmdir()
        else:
            manifests.unlink()


def test_read_manifest_refuses_final_symlink_without_no_follow(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = reference_bundle.materialize()
    path = materialization_store.manifest_path(result.manifest_digest.hex)
    target = tmp_path / "manifest-copy.json"
    shutil.move(str(path), str(target))
    try:
        os.symlink(target, path)
    except OSError:
        pytest.skip("this host does not permit a file symlink for the read-path probe")
    monkeypatch.setattr(os, "O_NOFOLLOW", 0, raising=False)

    try:
        with pytest.raises(MaterializationError) as caught:
            materialization_store.read_manifest(result.manifest_digest)
        assert caught.value.code is MaterializationRefusalCode.INPUT_LINK_REFUSED
    finally:
        path.unlink()


def test_verify_manifest_bounds_realization_reread_after_verification(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = reference_bundle.materialize()
    realization = next(
        item for item in result.manifest.definitions if item.kind.value == "realization"
    )
    path = materialization_store.object_path(realization.semantic_digest.hex)
    original_verify = MaterializationStore._verify_object

    def verified_then_mutated(
        self: MaterializationStore, object_key: str, expected_size: int
    ) -> None:
        original_verify(self, object_key, expected_size)
        if object_key == realization.object:
            path.write_bytes(b"x" * (MAX_DEFINITION_BYTES + 1))

    monkeypatch.setattr(MaterializationStore, "_verify_object", verified_then_mutated)
    monkeypatch.setattr(
        Path,
        "read_bytes",
        lambda self: (_ for _ in ()).throw(AssertionError("unbounded realization read")),
    )
    with pytest.raises(MaterializationError) as caught:
        materialization_store.verify_manifest(result.manifest)
    assert caught.value.code in {
        MaterializationRefusalCode.INPUT_LIMIT_EXCEEDED,
        MaterializationRefusalCode.INPUT_OBJECT_CORRUPT,
    }


def test_three_process_quarantine_recovery_never_removes_new_object(
    reference_bundle: ReferenceBundle,
    materialization_store: MaterializationStore,
) -> None:
    import multiprocessing

    payload = b"healthy replacement"
    digest = hashlib.sha256(payload).hexdigest()
    materialization_store.ensure_layout()
    canonical = materialization_store.object_path(digest)
    canonical.write_bytes(b"corrupt old object")

    context = multiprocessing.get_context("spawn")
    barrier = context.Barrier(3)
    results = context.Queue()
    processes = [
        context.Process(
            target=_publish_worker,
            args=(
                str(reference_bundle.workspace.source_root),
                str(reference_bundle.workspace.evidence_root),
                payload,
                digest,
                barrier,
                results,
            ),
        )
        for _ in range(3)
    ]
    for process in processes:
        process.start()
    outcomes = [results.get(timeout=60) for _ in processes]
    for process in processes:
        process.join(timeout=60)

    assert all(process.exitcode == 0 for process in processes)
    assert canonical.read_bytes() == payload
    assert any(outcome[0] == "ok" for outcome in outcomes)
    assert not any(outcome[0] == "error" for outcome in outcomes)
    quarantine = materialization_store.root / "quarantine"
    preserved = list(quarantine.glob(f"{digest}.*"))
    assert len(preserved) >= 1
    assert preserved[0].read_bytes() == b"corrupt old object"
